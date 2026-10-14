import { expect, test } from "@playwright/test";

import { findClinicalValues } from "@/lib/redaction/clinical";
import { redact } from "@/lib/redaction/redact";
import { createStreamRehydrator, rehydrate } from "@/lib/redaction/rehydrate";
import type { Span } from "@/lib/redaction/types";

// ---------------------------------------------------------------------------
// The rule that matters more than coverage: clinical numbers survive.
// ---------------------------------------------------------------------------

// Every line is something a parent or a report really contains. None holds an
// identifier, so redact() must return each one byte for byte, with an empty
// map. The values are chosen to be the ones a sloppy pattern would eat: long
// digit runs, five-digit counts, dates, dotted thousands, 9-digit-looking
// groups and numbers right next to units.
const CLINICAL_LINES = [
  "Tiene fiebre de 38.2 °C desde ayer, ayer llegó a 39,1ºC.",
  "Pesa 8.350 kg y mide 72 cm; perímetro cefálico 44,5 cm.",
  "Peso al nacer 3.150 g, talla 50 cm, Apgar 9/10 al minuto y 10/10 a los 5.",
  "Paracetamol 120 mg/5 ml, 3,5 ml cada 6 horas (15 mg/kg/dosis).",
  "Ibuprofeno 100 mg/5 ml: 2,5 ml cada 8 h, máximo 30 mg/kg/día.",
  "Vitamina D 400 UI al día, hierro 2 mg/kg/día.",
  "Hemoglobina 12.5 g/dL, hematocrito 37 %, VCM 82 fL.",
  "Leucocitos 12500/µL, neutrófilos 4.800/µL, plaquetas 250000/µL.",
  "Plaquetas 650.000 x10^3/L, recuento 12.500.000.",
  "PCR 120 mg/L, glucosa 90 mg/dL, sodio 138 mmol/L, potasio 4,2 mEq/L.",
  "Saturación 97%, FC 140 lpm, FR 40 rpm, TA 90/60 mmHg.",
  "Vacuna hexavalente (2ª dosis) el 15/03/2025; la siguiente el 15/05/2025.",
  "Cita de control el 20/04/2025 a las 10:30 en el centro de salud.",
  "Desde el 3 de marzo de 2025 tose y tiene mocos, 5 días de evolución.",
  "Peso 8.350 kg el 12/03/2025, 8.900 kg el 12/04/2025.",
  "Ferritina 25 ng/mL, vitamina B12 450 pg/mL, TSH 2,3 µUI/mL.",
  "Dosis de 1.500.000 UI y 100000 UI; 12345 gotas no, 12 gotas sí.",
  "Nació a las 38+2 semanas con 3.150 g y 49 cm, ingresó 5 días.",
  "Le dimos 5 ml de Dalsy 100 mg y a las 2 horas 80 mg de Apiretal.",
  "Bilirrubina 14,2 mg/dL a las 72 horas, 6 días de vida, 2 meses y 3 semanas.",
  "Le bébé a 38,5°C, pèse 7,2 kg, doliprane 15 mg/kg toutes les 6 h.",
  "CRP 12 mg/L, vaccin du 12/02/2025, rendez-vous le 03/04/2025 à 14h30.",
  "Fever of 101.3 F, weight 17 lb 4 oz, 120 mg every 6 hours since 03/04/2025.",
];

test("a text full of clinical values passes through unchanged", () => {
  const text = CLINICAL_LINES.join("\n");
  const result = redact(text);
  expect(result.text).toBe(text);
  expect(result.map).toEqual({});
});

test("each clinical line passes through unchanged on its own", () => {
  for (const line of CLINICAL_LINES) {
    const result = redact(line);
    expect(result.text, line).toBe(line);
    expect(result.map, line).toEqual({});
  }
});

test("clinical values survive next to identifiers that ARE masked", () => {
  const text =
    "Lucía tiene 38.2 °C, pesa 8.350 kg y toma paracetamol 120 mg/5 ml. " +
    "Mi teléfono es 612 345 678 y mi DNI 12345678Z. Peso el 12/03/2025: 8.350 kg.";
  const { text: out, map } = redact(text);
  expect(out).toBe(
    "Lucía tiene 38.2 °C, pesa 8.350 kg y toma paracetamol 120 mg/5 ml. " +
      "Mi teléfono es [TELEFONO_1] y mi DNI [DNI_1]. Peso el 12/03/2025: 8.350 kg.",
  );
  expect(map).toEqual({ "[TELEFONO_1]": "612 345 678", "[DNI_1]": "12345678Z" });
});

test("a hit that overlaps a clinical quantity is dropped, whichever detector made it", () => {
  // A phone-shaped run followed by a unit is a quantity. Without the guard the
  // Spanish phone pattern would take it.
  const text = "Recuento 612345678 /µL";
  expect(findClinicalValues(text)).toHaveLength(1);
  expect(redact(text).text).toBe(text);
});

test.describe("clinical quantity recogniser", () => {
  test("doses and measures are told apart, compound units win over simple ones", () => {
    const kinds = (text: string) => findClinicalValues(text).map((v) => [text.slice(v.start, v.end), v.kind]);
    expect(kinds("120 mg/5 ml")).toEqual([["120 mg/5 ml", "dose"]]);
    expect(kinds("15 mg/kg/día")).toEqual([["15 mg/kg/día", "dose"]]);
    expect(kinds("90 mg/dL")).toEqual([["90 mg/dL", "measure"]]);
    expect(kinds("12,5 g/dL")).toEqual([["12,5 g/dL", "measure"]]);
    expect(kinds("38,2 °C")).toEqual([["38,2 °C", "measure"]]);
    expect(kinds("8.350 kg")).toEqual([["8.350 kg", "measure"]]);
    expect(kinds("100 mg")).toEqual([["100 mg", "dose"]]);
    expect(kinds("10-15 mg/kg")).toEqual([["10-15 mg/kg", "dose"]]);
  });

  test("ages are not clinical quantities", () => {
    expect(findClinicalValues("tiene 4 meses y 2 semanas, 3 años")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Placeholders: stable, deterministic, idempotent, reversible.
// ---------------------------------------------------------------------------

const PII_TEXT =
  "Mi DNI es 12345678Z y el de mi pareja X1234567L. Escribid a papa@example.com o llamad al " +
  "612 345 678. Mi marido: 12345678Z. Lucía nació el 12/03/2024 (CP 28001), tarjeta sanitaria " +
  "AB123456. Carte vitale 1 85 05 78 006 084 91.";

test("replaces each identifier with a stable placeholder and returns the way back", () => {
  const { text, map } = redact(PII_TEXT);
  expect(text).toBe(
    "Mi DNI es [DNI_1] y el de mi pareja [NIE_1]. Escribid a [EMAIL_1] o llamad al " +
      "[TELEFONO_1]. Mi marido: [DNI_1]. Lucía nació el [FECHA_NACIMIENTO_1] (CP [CODIGO_POSTAL_1]), " +
      "tarjeta sanitaria [TARJETA_SANITARIA_1]. Carte vitale [NIR_1].",
  );
  expect(map).toEqual({
    "[DNI_1]": "12345678Z",
    "[NIE_1]": "X1234567L",
    "[EMAIL_1]": "papa@example.com",
    "[TELEFONO_1]": "612 345 678",
    "[FECHA_NACIMIENTO_1]": "12/03/2024",
    "[CODIGO_POSTAL_1]": "28001",
    "[TARJETA_SANITARIA_1]": "AB123456",
    "[NIR_1]": "1 85 05 78 006 084 91",
  });
});

test("the same value gets the same placeholder, a different value the next one", () => {
  const { text, map } = redact("DNI 12345678Z, otro 87654321X, de nuevo 12345678Z.");
  expect(text).toBe("DNI [DNI_1], otro [DNI_2], de nuevo [DNI_1].");
  expect(map).toEqual({ "[DNI_1]": "12345678Z", "[DNI_2]": "87654321X" });
});

test("deterministic: the same input always gives the same output", () => {
  const a = redact(PII_TEXT);
  const b = redact(PII_TEXT);
  expect(b).toEqual(a);
});

test("idempotent: redacting the output again changes nothing", () => {
  const first = redact(PII_TEXT);
  const second = redact(first.text);
  expect(second.text).toBe(first.text);
  expect(second.map).toEqual({});
  // And with the mapping handed back in, the result is the same, map included.
  expect(redact(first.text, { seed: first.map })).toEqual(first);
});

test("idempotent on clinical text and on an empty string", () => {
  const text = CLINICAL_LINES.join("\n");
  expect(redact(redact(text).text).text).toBe(text);
  expect(redact("")).toEqual({ text: "", map: {} });
});

test("reversible: rehydrating the redacted text gives the original back", () => {
  const corpus = [PII_TEXT, CLINICAL_LINES.join("\n"), "", "sin nada que ocultar", "12.345.678-Z y 12345678Z"];
  for (const original of corpus) {
    const { text, map } = redact(original);
    expect(rehydrate(text, map), original).toBe(original);
  }
});

test("reversible even when the same value is written two ways", () => {
  // Same DNI, two spellings: they get two placeholders so each comes back as typed.
  const original = "12.345.678-Z y 12345678Z";
  const { text, map } = redact(original);
  expect(text).toBe("[DNI_1] y [DNI_2]");
  expect(rehydrate(text, map)).toBe(original);
});

test("a placeholder already in the text is neither matched nor minted again", () => {
  const { text, map } = redact("[DNI_1] y mi DNI 12345678Z");
  expect(text).toBe("[DNI_1] y mi DNI [DNI_2]");
  expect(map).toEqual({ "[DNI_2]": "12345678Z" });
});

test("seed: a conversation keeps its numbering across messages", () => {
  const turn1 = redact("Mi DNI es 12345678Z");
  const turn2 = redact("El otro es 87654321X y el mío sigue siendo 12345678Z", { seed: turn1.map });
  expect(turn1.text).toBe("Mi DNI es [DNI_1]");
  expect(turn2.text).toBe("El otro es [DNI_2] y el mío sigue siendo [DNI_1]");
  expect(turn2.map).toEqual({ "[DNI_1]": "12345678Z", "[DNI_2]": "87654321X" });
});

test("overlaps: the more specific detector wins", () => {
  // The digits inside the address are also a phone number; the email wins.
  expect(redact("a 612345678@example.com b").text).toBe("a [EMAIL_1] b");
  // A valid NIR is one NIR, not a phone number plus leftovers.
  expect(redact("1 85 05 78 006 084 91").text).toBe("[NIR_1]");
});

test("surrounding text, spacing and punctuation are preserved exactly", () => {
  const text = "  ¿Mi DNI (12345678Z)?\n\tSí: papa@example.com.  ";
  expect(redact(text).text).toBe("  ¿Mi DNI ([DNI_1])?\n\tSí: [EMAIL_1].  ");
});

// ---------------------------------------------------------------------------
// Names the app already knows.
// ---------------------------------------------------------------------------

test.describe("known names", () => {
  test("masks the full name and each part of it, accents ignored", () => {
    const { text, map } = redact("Lucia Pérez tiene fiebre. Lucía come bien. Dile a Perez.", {
      names: ["Lucía Pérez"],
    });
    expect(text).toBe("[NOMBRE_1] tiene fiebre. [NOMBRE_2] come bien. Dile a [NOMBRE_3].");
    expect(map["[NOMBRE_1]"]).toBe("Lucia Pérez");
  });

  test("a name that is also a word is only masked when capitalised", () => {
    const names = ["Luz"];
    expect(redact("le molesta la luz del cuarto", { names }).text).toBe("le molesta la luz del cuarto");
    expect(redact("Luz tiene fiebre", { names }).text).toBe("[NOMBRE_1] tiene fiebre");
  });

  test("never inside a longer word, and particles alone are not names", () => {
    expect(redact("Lucianos y Lucía", { names: ["Lucía"] }).text).toBe("Lucianos y [NOMBRE_1]");
    expect(redact("Ana de la Cruz", { names: ["Ana de la Cruz"] }).text).toBe("[NOMBRE_1]");
    expect(redact("Cruz de la plaza, de nada", { names: ["Ana de la Cruz"] }).text).toBe(
      "[NOMBRE_1] de la plaza, de nada",
    );
  });

  test("a name is never masked inside a clinical quantity or an existing placeholder", () => {
    expect(redact("[NOMBRE_1] y Lucía", { names: ["Lucía"] }).text).toBe("[NOMBRE_1] y [NOMBRE_2]");
  });
});

// ---------------------------------------------------------------------------
// Spans from the model are vetted before they are used.
// ---------------------------------------------------------------------------

function person(text: string, word: string, from = 0): Span {
  const start = text.indexOf(word, from);
  return { start, end: start + word.length, kind: "NOMBRE", score: 0.99 };
}

test.describe("model spans", () => {
  test("a person the model found is masked", () => {
    const text = "Mi hija Valentina tiene tos";
    expect(redact(text, { modelSpans: [person(text, "Valentina")] }).text).toBe("Mi hija [NOMBRE_1] tiene tos");
  });

  test("a capitalised word right before a dose is a drug, not a person", () => {
    const text = "Le di Dalsy 100 mg y Apiretal 5 ml";
    const spans = [person(text, "Dalsy"), person(text, "Apiretal")];
    expect(redact(text, { modelSpans: spans }).text).toBe(text);
  });

  test("but a name before a weight or an age is still a person", () => {
    const text = "Lucía 5 kg, Mateo 4 meses";
    const spans = [person(text, "Lucía"), person(text, "Mateo")];
    expect(redact(text, { modelSpans: spans }).text).toBe("[NOMBRE_1] 5 kg, [NOMBRE_2] 4 meses");
  });

  test("a span with a digit, a lower-case start or the wrong kind is refused", () => {
    const text = "Dalsy2 fiebre Lucía";
    expect(redact(text, { modelSpans: [{ start: 0, end: 6, kind: "NOMBRE" }] }).text).toBe(text);
    expect(redact(text, { modelSpans: [{ start: 7, end: 13, kind: "NOMBRE" }] }).text).toBe(text);
    expect(redact(text, { modelSpans: [{ start: 14, end: 19, kind: "DNI" }] }).text).toBe(text);
  });

  test("a model span overlapping a clinical value is refused", () => {
    const text = "Valor 38.2 °C";
    expect(redact(text, { modelSpans: [{ start: 6, end: 13, kind: "NOMBRE" }] }).text).toBe(text);
  });

  test("the word inside an existing placeholder is never taken for a person", () => {
    // Redacted text read again by the model: it can tag NOMBRE in [NOMBRE_1].
    const text = "Hola [NOMBRE_1] y Marta";
    const spans = [
      { start: 6, end: 12, kind: "NOMBRE" as const, score: 0.99 },
      person(text, "Marta"),
    ];
    expect(redact(text, { modelSpans: spans }).text).toBe("Hola [NOMBRE_1] y [NOMBRE_2]");
  });

  test("a validated identifier beats a model span over the same characters", () => {
    const text = "DNI 12345678Z";
    const out = redact(text, { modelSpans: [{ start: 4, end: 13, kind: "NOMBRE" }] });
    expect(out.text).toBe("DNI [DNI_1]");
  });
});

// ---------------------------------------------------------------------------
// rehydrate
// ---------------------------------------------------------------------------

test.describe("rehydrate", () => {
  test("puts the original text back, everywhere a placeholder appears", () => {
    const map = { "[NOMBRE_1]": "Lucía", "[DNI_1]": "12345678Z" };
    expect(rehydrate("[NOMBRE_1] tiene fiebre. Sí, [NOMBRE_1]. DNI [DNI_1]", map)).toBe(
      "Lucía tiene fiebre. Sí, Lucía. DNI 12345678Z",
    );
  });

  test("an unknown placeholder, a citation marker and plain brackets are left alone", () => {
    const map = { "[NOMBRE_1]": "Lucía" };
    const text = "[NOMBRE_7] y [ev_1] y [1] y [texto] y [NOMBRE_1";
    expect(rehydrate(text, map)).toBe(text);
  });

  test("a value is inserted literally: $ sequences are not replacement patterns", () => {
    expect(rehydrate("x [NOMBRE_1] y", { "[NOMBRE_1]": "$& $1 $$" })).toBe("x $& $1 $$ y");
  });

  test("a map key that is not a placeholder cannot be reached", () => {
    expect(rehydrate("[__proto__] [constructor]", {})).toBe("[__proto__] [constructor]");
  });
});

test.describe("streamed rehydration", () => {
  const map = { "[NOMBRE_1]": "Lucía", "[TARJETA_SANITARIA_1]": "AB123456", "[DNI_2]": "87654321X" };
  const answer = "Hola [NOMBRE_1], la [TARJETA_SANITARIA_1] y el [DNI_2] son suyos. Ver [ev_1] y [1].";
  const expected = rehydrate(answer, map);

  function stream(chunks: string[]): string {
    const r = createStreamRehydrator(map);
    return chunks.map((c) => r.push(c)).join("") + r.flush();
  }

  test("any single cut of the stream gives the same text as rehydrating it whole", () => {
    for (let i = 0; i <= answer.length; i++) {
      expect(stream([answer.slice(0, i), answer.slice(i)]), `cut at ${i}`).toBe(expected);
    }
  });

  test("any two cuts, and one character at a time", () => {
    for (let i = 0; i < answer.length; i += 3) {
      for (let j = i; j < answer.length; j += 5) {
        expect(stream([answer.slice(0, i), answer.slice(i, j), answer.slice(j)])).toBe(expected);
      }
    }
    expect(stream([...answer])).toBe(expected);
  });

  test("a half placeholder is never shown to the parent", () => {
    const r = createStreamRehydrator(map);
    expect(r.push("Hola [NOM")).toBe("Hola ");
    expect(r.push("BRE_1], buenos")).toBe("Lucía, buenos");
    expect(r.flush()).toBe("");
  });

  test("a bracket that turns out not to be a placeholder is released", () => {
    const r = createStreamRehydrator(map);
    expect(r.push("ver [")).toBe("ver ");
    expect(r.push("ev_1] fin")).toBe("[ev_1] fin");
    expect(r.push("[AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")).toBe(
      "[AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    );
  });

  test("flush returns what was held when the stream ends mid-placeholder", () => {
    const r = createStreamRehydrator(map);
    expect(r.push("fin [NOMBRE_")).toBe("fin ");
    expect(r.flush()).toBe("[NOMBRE_");
    expect(r.flush()).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Property: no clinical sentence is ever changed.
// ---------------------------------------------------------------------------

// A seeded generator (mulberry32), so a failure is reproducible: the same
// sentences are produced on every run and on every machine.
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test("500 generated clinical sentences are never changed", () => {
  const rand = rng(20260914);
  const int = (lo: number, hi: number) => lo + Math.floor(rand() * (hi - lo + 1));
  const dec = (lo: number, hi: number, places: number) => {
    const v = (lo + rand() * (hi - lo)).toFixed(places);
    return rand() < 0.5 ? v : v.replace(".", ",");
  };
  const thousands = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, rand() < 0.5 ? "." : "");
  const date = () => {
    const d = String(int(1, 28)).padStart(2, "0");
    const m = String(int(1, 12)).padStart(2, "0");
    return `${d}/${m}/${int(2023, 2026)}`;
  };
  const pick = <T,>(xs: T[]): T => xs[int(0, xs.length - 1)];

  const makers: Array<() => string> = [
    () => `Fiebre de ${dec(36, 41, 1)} °C`,
    () => `Temperatura ${dec(36, 41, 1)}ºC desde el ${date()}`,
    () => `Pesa ${dec(2, 15, 3)} kg`,
    () => `Peso ${thousands(int(2000, 15000))} g el ${date()}`,
    () => `Mide ${int(45, 95)} cm, perímetro cefálico ${dec(33, 50, 1)} cm`,
    () => `Paracetamol ${int(60, 500)} mg/5 ml, ${dec(1, 10, 1)} ml cada ${int(4, 8)} h`,
    () => `Ibuprofeno ${int(5, 40)} mg/kg/día repartido en 3 tomas`,
    () => `Vitamina D ${thousands(int(100, 2000))} UI al día`,
    () => `Hemoglobina ${dec(6, 18, 1)} g/dL, hematocrito ${int(20, 50)} %`,
    () => `Leucocitos ${thousands(int(2000, 30000))}/µL, plaquetas ${thousands(int(50000, 900000))}/µL`,
    () => `PCR ${int(0, 300)} mg/L, glucosa ${int(40, 300)} mg/dL, sodio ${int(125, 150)} mmol/L`,
    () => `Saturación ${int(85, 100)}%, FC ${int(60, 200)} lpm, FR ${int(15, 70)} rpm`,
    () => `TA ${int(60, 120)}/${int(30, 90)} mmHg`,
    () => `Recuento ${thousands(int(100000000, 999999999))} /µL`,
    () => `Plaquetas ${int(10000, 99999)} y leucocitos ${int(10000, 99999)}`,
    () => `Vacuna el ${date()}, cita el ${date()} a las ${int(8, 20)}:${pick(["00", "15", "30", "45"])}`,
    () => `Tiene ${int(1, 24)} meses y ${int(1, 4)} semanas, lleva ${int(1, 9)} días con tos`,
    () => `Nació con ${thousands(int(2000, 4500))} g a las ${int(34, 42)}+${int(0, 6)} semanas, Apgar ${int(5, 10)}/10`,
    () => `Le bébé a ${dec(37, 40, 1)}°C et pèse ${dec(3, 12, 1)} kg, rendez-vous le ${date()}`,
    () => `Doliprane ${int(10, 15)} mg/kg toutes les ${int(4, 8)} h, ${int(1, 5)} fois par jour`,
  ];

  for (let i = 0; i < 500; i++) {
    const sentence = Array.from({ length: int(1, 4) }, () => pick(makers)()).join(". ") + ".";
    const out = redact(sentence);
    expect(out.text, sentence).toBe(sentence);
    expect(out.map, sentence).toEqual({});
  }
});
