import { expect, test } from "@playwright/test";

import {
  detectBirthDate,
  detectCarteVitale,
  detectDni,
  detectEmail,
  detectHealthCardEs,
  detectNie,
  detectNir,
  detectPhoneEs,
  detectPhoneFr,
  detectPhoneInternational,
  detectPostalCodeEs,
  detectPostalCodeFr,
  dniLetter,
  isValidDni,
  isValidNie,
  isValidNir,
  nieLetter,
  nirKey,
} from "@/lib/redaction/patterns";
import type { Detector } from "@/lib/redaction/types";

// Pure functions: no browser, no server. The values below are shaped like real
// identifiers and are fake. Every check letter and check key was computed
// separately (a throwaway script, not the code under test), and the NIR
// formula was first confirmed against a published example (2 69 05 49 588 157
// -> key 80).

/** The substrings a detector claims, which is what the tests care about. */
function found(detect: Detector, text: string): string[] {
  return detect(text).map((s) => text.slice(s.start, s.end));
}

test.describe("DNI (Spain)", () => {
  test("check letter is the number mod 23 in the official table", () => {
    expect(dniLetter(12345678)).toBe("Z");
    expect(dniLetter(0)).toBe("T");
    expect(dniLetter(87654321)).toBe("X");
    expect(dniLetter(11111111)).toBe("H");
    expect(dniLetter(99999999)).toBe("R");
    expect(dniLetter(5)).toBe("M");
  });

  test("all 23 entries of the table, against the official order written out here", () => {
    // Written independently of the code under test. A table with two letters
    // swapped at the end passes every spot check that happens to avoid them.
    const official = "TRWAGMYFPDXBNJZSQVHLCKE";
    expect(official).toHaveLength(23);
    for (let remainder = 0; remainder < 23; remainder++) {
      expect(dniLetter(remainder), `remainder ${remainder}`).toBe(official[remainder]);
      expect(dniLetter(remainder + 23 * 1000), `remainder ${remainder} + 23000`).toBe(official[remainder]);
    }
  });

  test("accepts a valid DNI in the ways people write it", () => {
    for (const dni of [
      "12345678Z",
      "12.345.678-Z",
      "12345678-Z",
      "12345678 Z",
      "12345678z",
      "00000000T",
      "10000007K", // remainder 21, the second to last entry of the table
      "10000008E", // remainder 22, the last one
    ]) {
      expect(found(detectDni, `Mi DNI es ${dni}.`), dni).toEqual([dni]);
    }
  });

  test("rejects a wrong check letter", () => {
    for (const dni of ["12345678S", "87654321B", "11111111L", "99999999W"]) {
      expect(found(detectDni, dni), dni).toEqual([]);
      expect(isValidDni(dni), dni).toBe(false);
    }
    expect(isValidDni("12345678Z")).toBe(true);
  });

  test("a lowercase letter after a space is a word, not a check letter", () => {
    // 12345678 -> Z, so "12345678 z" would validate if the space were allowed.
    expect(found(detectDni, "Ingreso 12345678 z veces")).toEqual([]);
  });

  test("is not found inside a longer number or word", () => {
    expect(found(detectDni, "912345678Z")).toEqual([]);
    expect(found(detectDni, "ref12345678Z")).toEqual([]);
    expect(found(detectDni, "12345678Z9")).toEqual([]);
  });
});

test.describe("NIE (Spain)", () => {
  test("prefix X, Y, Z stand for 0, 1, 2 before the mod 23", () => {
    expect(nieLetter("X", "1234567")).toBe("L");
    expect(nieLetter("Y", "1234567")).toBe("X");
    expect(nieLetter("Z", "1234567")).toBe("R");
    expect(nieLetter("X", "0000000")).toBe("T");
    expect(nieLetter("Y", "7654321")).toBe("G");
  });

  test("accepts valid NIEs with each prefix, with or without separators", () => {
    for (const nie of ["X1234567L", "Y1234567X", "Z1234567R", "X-1234567-L", "X 1234567 L", "x1234567l"]) {
      expect(found(detectNie, `NIE ${nie} caduca`), nie).toEqual([nie]);
    }
  });

  test("the prefix changes the letter: Y1234567L is not valid, X1234567L is", () => {
    expect(isValidNie("X1234567L")).toBe(true);
    expect(isValidNie("Y1234567L")).toBe(false);
    expect(found(detectNie, "Y1234567L")).toEqual([]);
  });

  test("rejects a wrong letter and any prefix but X, Y, Z", () => {
    expect(found(detectNie, "X1234567A")).toEqual([]);
    expect(found(detectNie, "A1234567L")).toEqual([]);
    expect(found(detectNie, "W1234567L")).toEqual([]);
  });

  test("a NIE is not also read as a DNI, nor a DNI as a NIE", () => {
    expect(found(detectDni, "X1234567L")).toEqual([]);
    expect(found(detectNie, "12345678Z")).toEqual([]);
  });
});

test.describe("NIR / numéro de sécurité sociale (France)", () => {
  test("key is 97 minus the first 13 digits mod 97", () => {
    expect(nirKey("2690549588157")).toBe(80); // published example
    expect(nirKey("1850578006084")).toBe(91);
    expect(nirKey("2890675123456")).toBe(37);
    expect(nirKey("2240598123456")).toBe(63);
  });

  test("accepts a valid NIR, spaced or compact", () => {
    for (const nir of [
      "2 69 05 49 588 157 80",
      "269054958815780",
      "1 85 05 78 006 084 91",
      "185057800608491",
      "2 89 06 75 123 456 37",
      "2 24 05 98 123 456 63",
    ]) {
      expect(found(detectNir, `NIR: ${nir}.`), nir).toEqual([nir]);
      expect(isValidNir(nir), nir).toBe(true);
    }
  });

  test("rejects a wrong key", () => {
    expect(found(detectNir, "1 85 05 78 006 084 92")).toEqual([]);
    expect(isValidNir("1 85 05 78 006 084 92")).toBe(false);
  });

  test("rejects an impossible structure even when a key would fit", () => {
    expect(isValidNir("1 85 13 78 006 084 00")).toBe(false); // month 13
    expect(isValidNir("1 85 05 96 006 084 00")).toBe(false); // département 96
    expect(isValidNir("1 85 05 00 006 084 00")).toBe(false); // département 00
    expect(isValidNir("5 85 05 78 006 084 00")).toBe(false); // first digit 5
  });

  test("Corsica (2A/2B) is accepted on structure, the key is not checked", () => {
    // The 2A/2B substitution rule is not verified against a primary source, so
    // it is deliberately not enforced. This pins that behaviour.
    expect(found(detectNir, "1 85 12 2A 004 123 71")).toEqual(["1 85 12 2A 004 123 71"]);
    expect(found(detectNir, "1 85 06 2B 001 042 00")).toEqual(["1 85 06 2B 001 042 00"]);
  });

  test("is not found inside a longer run of digits", () => {
    expect(found(detectNir, "9185057800608491")).toEqual([]);
  });

  test("Carte Vitale: with the keyword a wrong key, or no key at all, is still masked", () => {
    expect(found(detectCarteVitale, "Ma carte vitale : 1 85 05 78 006 084 91")).toEqual([
      "1 85 05 78 006 084 91",
    ]);
    expect(found(detectCarteVitale, "numéro de sécurité sociale 1 85 05 78 006 084 00")).toEqual([
      "1 85 05 78 006 084 00",
    ]);
    expect(found(detectCarteVitale, "NIR 1 85 05 78 006 084")).toEqual(["1 85 05 78 006 084"]);
  });

  test("Carte Vitale: without the keyword nothing is claimed, and structure is still checked", () => {
    expect(found(detectCarteVitale, "1 85 05 78 006 084 00")).toEqual([]);
    expect(found(detectCarteVitale, "carte vitale 1 85 13 78 006 084 00")).toEqual([]);
  });

  test("Carte Vitale: the number must be the first one after the keyword", () => {
    // 'sécu' then a count, then a NIR-shaped run further on: not claimed.
    expect(found(detectCarteVitale, "sécu 3 fois puis 1 85 05 78 006 084 00")).toEqual([]);
  });
});

test.describe("phone numbers", () => {
  test("Spain: nine digits starting 6-9, grouped any usual way, with or without +34", () => {
    for (const p of [
      "612345678",
      "612 345 678",
      "612-345-678",
      "612 34 56 78",
      "912 345 678",
      "+34 612 345 678",
      "+34612345678",
      "0034 612 345 678",
    ]) {
      expect(found(detectPhoneEs, `Llámame al ${p}.`), p).toEqual([p]);
    }
  });

  test("Spain: not a thousands-separated count, not the wrong length, not mid-number", () => {
    expect(found(detectPhoneEs, "plaquetas 650.000.000")).toEqual([]);
    expect(found(detectPhoneEs, "12345678")).toEqual([]);
    expect(found(detectPhoneEs, "512345678")).toEqual([]);
    expect(found(detectPhoneEs, "1612345678")).toEqual([]);
    expect(found(detectPhoneEs, "6123456789")).toEqual([]);
    expect(found(detectPhoneEs, "3.612345678")).toEqual([]);
  });

  test("France: ten digits starting 01-09 in pairs, or +33/0033 without the zero", () => {
    for (const p of [
      "06 12 34 56 78",
      "0612345678",
      "06.12.34.56.78",
      "06-12-34-56-78",
      "01 23 45 67 89",
      "+33 6 12 34 56 78",
      "+33612345678",
      "0033 6 12 34 56 78",
    ]) {
      expect(found(detectPhoneFr, `Appelez le ${p}.`), p).toEqual([p]);
    }
  });

  test("France: a date followed by two digits is not a phone number", () => {
    // 01.02.2024 10 has ten digits and a 0[1-9] start; only a consistent
    // separator makes a phone number.
    expect(found(detectPhoneFr, "visite du 01.02.2024 10 h")).toEqual([]);
    expect(found(detectPhoneFr, "1234567890")).toEqual([]);
    expect(found(detectPhoneFr, "00 12 34 56 78")).toEqual([]);
  });

  test("a French number is not read as a Spanish one, nor the reverse", () => {
    expect(found(detectPhoneEs, "06 12 34 56 78")).toEqual([]);
    expect(found(detectPhoneEs, "0612345678")).toEqual([]);
    expect(found(detectPhoneFr, "612 345 678")).toEqual([]);
  });

  test("international: needs the plus", () => {
    expect(found(detectPhoneInternational, "oficina +44 20 7946 0958 ext")).toEqual(["+44 20 7946 0958"]);
    expect(found(detectPhoneInternational, "+1 202 555 0143")).toEqual(["+1 202 555 0143"]);
    expect(found(detectPhoneInternational, "44 20 7946 0958")).toEqual([]);
    expect(found(detectPhoneInternational, "dosis +0.5 mg")).toEqual([]);
  });
});

test.describe("email", () => {
  test("finds addresses, not the full stop that ends the sentence", () => {
    expect(found(detectEmail, "Escribe a papa@example.com.")).toEqual(["papa@example.com"]);
    expect(found(detectEmail, "ana.garcia+bebe@mail.example.es, gracias")).toEqual([
      "ana.garcia+bebe@mail.example.es",
    ]);
    expect(found(detectEmail, "a@b.co y c@d.org")).toEqual(["a@b.co", "c@d.org"]);
  });

  test("ignores text that only contains an @", () => {
    expect(found(detectEmail, "nos vemos @ las 5")).toEqual([]);
    expect(found(detectEmail, "usuario@")).toEqual([]);
    expect(found(detectEmail, "@algo.com")).toEqual([]);
  });
});

test.describe("postal codes (only after a keyword)", () => {
  test("Spain: 01000-52999 after CP, C.P. or código postal", () => {
    expect(found(detectPostalCodeEs, "vivimos en CP 28001")).toEqual(["28001"]);
    expect(found(detectPostalCodeEs, "C.P. 08001, Barcelona")).toEqual(["08001"]);
    expect(found(detectPostalCodeEs, "Código postal: 46001")).toEqual(["46001"]);
    expect(found(detectPostalCodeEs, "cp28001")).toEqual(["28001"]);
  });

  test("Spain: out-of-range provinces are not postal codes", () => {
    expect(found(detectPostalCodeEs, "CP 53000")).toEqual([]);
    expect(found(detectPostalCodeEs, "CP 00100")).toEqual([]);
    expect(found(detectPostalCodeEs, "CP 99999")).toEqual([]);
  });

  test("France: 01000-95999 and 97000-98999 after CP or code postal", () => {
    expect(found(detectPostalCodeFr, "code postal 75011")).toEqual(["75011"]);
    expect(found(detectPostalCodeFr, "CP : 97400")).toEqual(["97400"]);
    expect(found(detectPostalCodeFr, "CP 53000")).toEqual(["53000"]);
    expect(found(detectPostalCodeFr, "CP 96000")).toEqual([]);
    expect(found(detectPostalCodeFr, "CP 99000")).toEqual([]);
  });

  test("a five-digit number without the keyword is a count, not a postal code", () => {
    for (const text of [
      "leucocitos 12500",
      "12500 leucocitos",
      "plaquetas 25000",
      "28001",
      "peso 28001 g",
    ]) {
      expect(found(detectPostalCodeEs, text), text).toEqual([]);
      expect(found(detectPostalCodeFr, text), text).toEqual([]);
    }
  });

  test("six digits after the keyword are not a postal code", () => {
    expect(found(detectPostalCodeEs, "CP 280010")).toEqual([]);
  });
});

test.describe("date of birth (only right after a birth keyword)", () => {
  test("masks the date and only the date, in Spanish, French and English", () => {
    const cases: Array<[string, string]> = [
      ["Nació el 12/03/2024 en Madrid", "12/03/2024"],
      ["Fecha de nacimiento: 12-03-2024", "12-03-2024"],
      ["nacida el 12 de marzo de 2024", "12 de marzo de 2024"],
      ["nacido el día 12 de Marzo del 2024", "12 de Marzo del 2024"],
      ["F. nac.: 12.03.2024", "12.03.2024"],
      ["née le 12/03/2024", "12/03/2024"],
      ["Né le 1er mars 2024", "1er mars 2024"],
      ["date de naissance : 12.03.2024", "12.03.2024"],
      ["née le 3 décembre 2023", "3 décembre 2023"],
      ["DOB: 2024-03-12", "2024-03-12"],
      ["born on March 12, 2024", "March 12, 2024"],
      ["date of birth 12/03/24", "12/03/24"],
    ];
    for (const [text, date] of cases) {
      expect(found(detectBirthDate, text), text).toEqual([date]);
    }
  });

  test("a date of a measurement, a vaccine or a visit is left alone", () => {
    for (const text of [
      "Peso 8.350 kg el 12/03/2025",
      "Vacuna hexavalente el 15/03/2025",
      "Cita el 20/04/2025 a las 10:30",
      "Fiebre desde el 3 de marzo de 2025",
      "analyse du 12/02/2025",
      "Hemoglobina 12.5 g/dL (15/03/2025)",
    ]) {
      expect(found(detectBirthDate, text), text).toEqual([]);
    }
  });

  test("only the date directly after the keyword, not a later one", () => {
    const text = "Nació el 12/03/2024 y la vacuna fue el 15/03/2024";
    expect(found(detectBirthDate, text)).toEqual(["12/03/2024"]);
  });

  test("a birth keyword with no date after it claims nothing", () => {
    for (const text of [
      "Peso al nacimiento 3.2 kg",
      "Apgar al nacimiento: 9/10",
      "nació a las 38 semanas",
      "nacido con 3.150 g",
      "née prématurée à 34 semaines",
    ]) {
      expect(found(detectBirthDate, text), text).toEqual([]);
    }
  });

  test("an impossible calendar date is not a date", () => {
    expect(found(detectBirthDate, "nació el 45/13/2024")).toEqual([]);
    expect(found(detectBirthDate, "nació el 12/13/2024")).toEqual([]);
  });

  test("month and year alone are not masked", () => {
    expect(found(detectBirthDate, "nació en marzo de 2024")).toEqual([]);
  });
});

test.describe("tarjeta sanitaria (Spain)", () => {
  // Structures from the Ministerio de Sanidad document "Modelos de tarjetas
  // sanitarias en el SNS" (Plan VEO v3.0).

  test("lettered CIP-AUT formats are found anywhere", () => {
    const cases: Array<[string, string]> = [
      ["Cataluña, 4 letras + 10 números", "CATA 1234 5678 90"],
      ["Madrid, 4 letras + 12 números", "MADR 1234 5678 9012"],
      ["compacto", "MADR123456789012"],
      ["Andalucía AN + 10", "AN1234567890"],
      ["Aragón AR + 9 + letra", "AR123456789K"],
      ["Castilla y León CYL + 10", "CYL1234567890"],
      ["Galicia 6 + 4 letras + 4", "123456 ABCD 1234"],
      ["Murcia CARM + 12", "CARM 1234 5678 9012"],
    ];
    for (const [label, card] of cases) {
      expect(found(detectHealthCardEs, `Mi tarjeta: ${card} gracias`), label).toEqual([card]);
    }
  });

  test("CIP-SNS, 2 letters and 6 digits, needs the keyword", () => {
    expect(found(detectHealthCardEs, "CIP-SNS: AB123456")).toEqual(["AB123456"]);
    expect(found(detectHealthCardEs, "tarjeta sanitaria AB123456")).toEqual(["AB123456"]);
    expect(found(detectHealthCardEs, "lote AB123456")).toEqual([]);
  });

  test("digit-only CIP-AUT lengths need the keyword", () => {
    expect(found(detectHealthCardEs, "tarjeta sanitaria: 12345678")).toEqual(["12345678"]); // Navarra, País Vasco
    expect(found(detectHealthCardEs, "TSI 1234567")).toEqual(["1234567"]); // Valencia, 7
    expect(found(detectHealthCardEs, "CIP 1234567890")).toEqual(["1234567890"]); // Madrid, 10
    expect(found(detectHealthCardEs, "SIP 12345678901")).toEqual(["12345678901"]); // Baleares, 11
    expect(found(detectHealthCardEs, "tarjeta sanitaria nº 123456789012")).toEqual(["123456789012"]); // Andalucía, 12
    expect(found(detectHealthCardEs, "mi CIP es 1234 5678 9012")).toEqual(["1234 5678 9012"]);
  });

  test("the same digits with no keyword are not claimed", () => {
    for (const text of ["12345678", "peso 12345678", "tarjeta 12345678", "ref 123456789012"]) {
      expect(found(detectHealthCardEs, text), text).toEqual([]);
    }
  });

  test("nine digits after the keyword are a phone number, not a card", () => {
    expect(found(detectHealthCardEs, "tarjeta sanitaria 612345678")).toEqual([]);
  });

  test("the number has to be the first one after the keyword", () => {
    expect(found(detectHealthCardEs, "tarjeta sanitaria, 2 hijos, 12345678")).toEqual([]);
  });
});
