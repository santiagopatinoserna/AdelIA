import { expect, test } from "@playwright/test";

import {
  alignEntities,
  chunkText,
  createEntityDetector,
  detectEntities,
  nerStatus,
  webGpuUsable,
  type NerPipeline,
  type RawEntity,
} from "@/lib/redaction/ner";
import { redact } from "@/lib/redaction/redact";

// No model, no GPU, no network. The loader is injected, so every state the real
// one can reach (ready, failed, slow, throwing) is reproduced with a fake.

const per = (word: string, score = 0.99): RawEntity => ({ entity_group: "PER", score, word });
const slow = <T,>(value: T, ms: number) => new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));

test.describe("alignment of model output to text", () => {
  test("finds each person, in order, as character ranges", () => {
    const text = "Mi hija Valentina vive con Marta Gómez";
    const spans = alignEntities(text, [per("Valentina"), per("Marta Gómez")], 0.9);
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(["Valentina", "Marta Gómez"]);
    expect(spans.every((s) => s.kind === "NOMBRE")).toBe(true);
  });

  test("the same name twice is found twice, not the first one twice", () => {
    const text = "Lucía duerme. Lucía come.";
    const spans = alignEntities(text, [per("Lucía"), per("Lucía")], 0.9);
    expect(spans.map((s) => s.start)).toEqual([0, 14]);
  });

  test("offsets are shifted by the chunk's position in the whole text", () => {
    const spans = alignEntities("hola Marta", [per("Marta")], 0.9, 100);
    expect(spans).toEqual([{ start: 105, end: 110, kind: "NOMBRE", score: 0.99 }]);
  });

  test("only persons, only above the threshold", () => {
    const text = "Marta vive en Madrid con Dalsy";
    const entities: RawEntity[] = [
      per("Marta", 0.97),
      { entity_group: "LOC", score: 0.99, word: "Madrid" },
      { entity_group: "ORG", score: 0.99, word: "Dalsy" },
      per("Dalsy", 0.6),
    ];
    const spans = alignEntities(text, entities, 0.9);
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(["Marta"]);
  });

  test("a decoder that spaces out punctuation still lines up with the text", () => {
    const text = "Habló con O'Brien ayer";
    const spans = alignEntities(text, [per("O ' Brien")], 0.9);
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(["O'Brien"]);
  });

  test("a word that is not in the text is dropped, never guessed", () => {
    expect(alignEntities("hola Marta", [per("Zacarías")], 0.9)).toEqual([]);
  });
});

test.describe("chunking", () => {
  test("pieces are contiguous and rebuild the text exactly", () => {
    const text = "Primera frase larga. ".repeat(40) + "\n" + "Otra más sin punto ".repeat(30);
    for (const max of [50, 120, 1000]) {
      const chunks = chunkText(text, max);
      expect(chunks.map((c) => c.text).join("")).toBe(text);
      let at = 0;
      for (const c of chunks) {
        expect(c.offset).toBe(at);
        expect(c.text.length).toBeLessThanOrEqual(max);
        at += c.text.length;
      }
    }
  });

  test("prefers to cut at a line break, then a full stop, then a space", () => {
    const first = chunkText("aaaa bbbb\ncccc dddd eeee", 15)[0].text;
    expect(first).toBe("aaaa bbbb\n");
    expect(chunkText("aaaa bbbb. cccc dddd eeee", 15)[0].text).toBe("aaaa bbbb. ");
    expect(chunkText("aaaa bbbb cccc dddd", 12)[0].text).toBe("aaaa bbbb ");
  });

  test("text with no break at all is still cut, and short text is one piece", () => {
    expect(chunkText("x".repeat(25), 10).map((c) => c.text.length)).toEqual([10, 10, 5]);
    expect(chunkText("hola", 1000)).toEqual([{ text: "hola", offset: 0 }]);
    expect(chunkText("", 1000)).toEqual([]);
  });
});

test.describe("the detector", () => {
  test("loads nothing until the first call, and nothing for empty text", async () => {
    let loads = 0;
    const detector = createEntityDetector(async () => {
      loads++;
      return async () => [];
    });
    expect(detector.status()).toBe("idle");
    expect(await detector.detectEntities("   ")).toEqual([]);
    expect(loads).toBe(0);
    await detector.detectEntities("hola");
    expect(loads).toBe(1);
  });

  test("loads once, caches the model, and returns spans", async () => {
    let loads = 0;
    let calls = 0;
    const model: NerPipeline = async (chunk) => {
      calls++;
      return chunk.includes("Valentina") ? [per("Valentina")] : [];
    };
    const detector = createEntityDetector(async () => {
      loads++;
      return model;
    });
    const a = await detector.detectEntities("Mi hija Valentina");
    const b = await detector.detectEntities("otra vez Valentina");
    expect(loads).toBe(1);
    expect(calls).toBe(2);
    expect(detector.status()).toBe("ready");
    expect(a).toEqual([{ start: 8, end: 17, kind: "NOMBRE", score: 0.99 }]);
    expect(b).toHaveLength(1);
  });

  test("a long text is read in chunks and the offsets come out right", async () => {
    const model: NerPipeline = async (chunk) => (chunk.includes("Valentina") ? [per("Valentina")] : []);
    const detector = createEntityDetector(async () => model, { chunkChars: 60 });
    const text = "Relleno sin nombres. ".repeat(10) + "Mi hija Valentina tiene tos. " + "Más relleno. ".repeat(5);
    const spans = await detector.detectEntities(text);
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(["Valentina"]);
  });

  test("when the model cannot load, it answers [] and does not try again", async () => {
    let loads = 0;
    const detector = createEntityDetector(async () => {
      loads++;
      throw new Error("no WebGPU");
    });
    expect(await detector.detectEntities("Mi hija Valentina")).toEqual([]);
    expect(await detector.detectEntities("Mi hija Valentina")).toEqual([]);
    expect(detector.status()).toBe("unavailable");
    expect(loads).toBe(1);
  });

  test("when inference throws, it answers [] and stays usable", async () => {
    let n = 0;
    const model: NerPipeline = async () => {
      if (n++ === 0) throw new Error("device lost");
      return [per("Valentina")];
    };
    const detector = createEntityDetector(async () => model);
    expect(await detector.detectEntities("Mi hija Valentina")).toEqual([]);
    expect(await detector.detectEntities("Mi hija Valentina")).toHaveLength(1);
  });

  test("a slow first load does not hold the question: [] now, the model next time", async () => {
    const model: NerPipeline = async () => [per("Valentina")];
    const detector = createEntityDetector(() => slow(model, 120), { loadBudgetMs: 10 });
    const started = Date.now();
    expect(await detector.detectEntities("Mi hija Valentina")).toEqual([]);
    expect(Date.now() - started).toBeLessThan(100);
    expect(detector.status()).toBe("loading");
    await slow(null, 200);
    expect(detector.status()).toBe("ready");
    expect(await detector.detectEntities("Mi hija Valentina")).toHaveLength(1);
  });

  test("never rejects, whatever the loader does", async () => {
    const detector = createEntityDetector(() => {
      throw new Error("synchronous failure");
    });
    await expect(detector.detectEntities("Mi hija Valentina")).resolves.toEqual([]);
  });
});

test.describe("graceful degradation to the patterns", () => {
  test("with no model the patterns still do their whole job", async () => {
    const detector = createEntityDetector(async () => {
      throw new Error("offline");
    });
    const text = "Mi DNI es 12345678Z, llamad al 612 345 678. Tiene 38.2 °C.";
    const modelSpans = await detector.detectEntities(text);
    expect(redact(text, { modelSpans }).text).toBe("Mi DNI es [DNI_1], llamad al [TELEFONO_1]. Tiene 38.2 °C.");
  });

  test("this environment has no WebGPU: the real detector says so and answers []", async () => {
    expect(await webGpuUsable()).toBe(false);
    expect(await detectEntities("Mi hija Valentina")).toEqual([]);
    expect(nerStatus()).toBe("unavailable");
  });
});
