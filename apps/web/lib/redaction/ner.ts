// The model-backed layer: person names, found by a small multilingual
// named-entity model running on the device through Transformers.js and WebGPU.
//
// It is OPTIONAL by construction. The pattern detectors work with no model and
// no network; this layer only adds names, and every way it can fail (no WebGPU,
// no f16 shader support, the download fails, inference throws, the model is
// slow to load) ends the same way: `detectEntities` resolves to `[]` and the
// caller carries on with the patterns alone. It never rejects.
//
// Nothing here is loaded until the first call: `@huggingface/transformers` is a
// dynamic import behind the WebGPU check, so a browser without WebGPU never
// downloads a byte of it, and neither does a page where redaction is off.
//
// BEFORE THIS IS TURNED ON (it is off, see chat.ts), three things are open and
// none of them is decided by this file:
//   - Content-Security-Policy. next.config.ts allows scripts and connections to
//     'self' and the API only. Running the model needs `'wasm-unsafe-eval'` in
//     script-src and a connect-src entry for the host that serves the weights
//     (huggingface.co by default), or the weights self-hosted under /models.
//   - Size. The fp16 weights are in the hundreds of megabytes, downloaded once
//     per browser and then served from the Cache API.
//   - Quality. Nobody has measured this model on Spanish and French baby-health
//     text. Its failure mode is a brand of medicine read as a person; redact()
//     vets for that, but only measurement can say how often it slips through.

import type { Span } from "./types";

/** Multilingual (es, fr, en among others) BERT, token classification, ONNX. */
export const NER_MODEL_ID = "Xenova/bert-base-multilingual-cased-ner-hrl";
/** fp16 needs the `shader-f16` WebGPU feature; without it we do not run. */
export const NER_DTYPE = "fp16";
/** Mean confidence under which a person is not believed. */
export const NER_MIN_SCORE = 0.9;
/**
 * How long the FIRST message waits for the model to load before going out with
 * the patterns alone. A parent asking about a fever must not wait for a
 * download. The load keeps going and the next message uses the model. This is
 * a placeholder number: the product decision it stands for (privacy of the very
 * first message against latency of the very first message) is not mine.
 */
export const NER_LOAD_BUDGET_MS = 4000;
/** The model reads at most 512 tokens; longer text is cut into chunks of this size. */
export const NER_CHUNK_CHARS = 1000;

export type NerStatus = "idle" | "loading" | "ready" | "unavailable";

/** One entity as Transformers.js returns it with `aggregation_strategy: "simple"`. */
export type RawEntity = { entity_group: string; score: number; word: string };
export type NerPipeline = (text: string) => Promise<RawEntity[]>;
export type PipelineLoader = () => Promise<NerPipeline>;

export interface EntityDetector {
  /** Person spans in `text`. Never rejects; `[]` when the model is not usable. */
  detectEntities(text: string): Promise<Span[]>;
  status(): NerStatus;
}

export type DetectorOptions = {
  minScore?: number;
  chunkChars?: number;
  loadBudgetMs?: number;
};

export function createEntityDetector(
  load: PipelineLoader,
  options: DetectorOptions = {},
): EntityDetector {
  const minScore = options.minScore ?? NER_MIN_SCORE;
  const chunkChars = options.chunkChars ?? NER_CHUNK_CHARS;
  const budget = options.loadBudgetMs ?? NER_LOAD_BUDGET_MS;

  let status: NerStatus = "idle";
  let loading: Promise<NerPipeline | null> | null = null;
  let model: NerPipeline | null = null;

  function start(): Promise<NerPipeline | null> {
    if (!loading) {
      status = "loading";
      // The failure is remembered for the life of the page: retrying a failed
      // download of hundreds of megabytes on every message would be worse than
      // doing without the model.
      loading = load().then(
        (pipeline) => {
          model = pipeline;
          status = "ready";
          return pipeline;
        },
        () => {
          status = "unavailable";
          return null;
        },
      );
    }
    return loading;
  }

  async function ready(): Promise<NerPipeline | null> {
    if (model) return model;
    if (status === "unavailable") return null;
    const pending = start();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const late = new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), budget);
    });
    try {
      return await Promise.race([pending, late]);
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    status: () => status,
    async detectEntities(text) {
      if (!text.trim()) return [];
      try {
        const pipeline = await ready();
        if (!pipeline) return [];
        const spans: Span[] = [];
        for (const chunk of chunkText(text, chunkChars)) {
          const entities = await pipeline(chunk.text);
          spans.push(...alignEntities(chunk.text, entities, minScore, chunk.offset));
        }
        return spans;
      } catch {
        return [];
      }
    },
  };
}

// --- chunking and alignment: pure, and tested without a model ---------------

export type Chunk = { text: string; offset: number };

/**
 * Cut `text` into pieces of at most `max` characters, preferring to cut after a
 * line break, then after a full stop, then at a space, so a name is rarely cut
 * in half. The pieces are contiguous: concatenated they give `text` back, and
 * `offset` is where each one starts.
 */
export function chunkText(text: string, max: number): Chunk[] {
  const chunks: Chunk[] = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + max, text.length);
    if (end < text.length) {
      const window = text.slice(start, end);
      // First kind of break that falls in the second half of the window wins,
      // in order of preference. (Taking the latest break of ANY kind would cut
      // mid-sentence whenever a space comes after the last full stop.)
      for (const brk of ["\n", ". ", " "]) {
        const cut = window.lastIndexOf(brk);
        if (cut > max * 0.5) {
          end = start + cut + brk.length;
          break;
        }
      }
    }
    chunks.push({ text: text.slice(start, end), offset: start });
    start = end;
  }
  return chunks;
}

/**
 * Turn the model's entities back into character ranges of `chunk`.
 *
 * Transformers.js returns the recognised words but not where they were, so each
 * one is searched for in order, starting after the previous hit. The model's
 * decoder may put spaces around punctuation ("O ' Brien"), hence the second,
 * whitespace-tolerant attempt. A word that cannot be found is dropped: that is
 * a name that goes out unmasked, which the patterns-only fallback does too, and
 * the alternative (masking a guessed range) could mask the wrong text.
 */
export function alignEntities(
  chunk: string,
  entities: readonly RawEntity[],
  minScore: number,
  offset = 0,
): Span[] {
  const out: Span[] = [];
  let cursor = 0;
  for (const e of entities) {
    if (e.entity_group !== "PER" || e.score < minScore || !e.word.trim()) continue;
    const found = locate(chunk, e.word.trim(), cursor);
    if (!found) continue;
    cursor = found.end;
    out.push({ start: offset + found.start, end: offset + found.end, kind: "NOMBRE", score: e.score });
  }
  return out;
}

function locate(chunk: string, word: string, from: number): { start: number; end: number } | null {
  const exact = chunk.indexOf(word, from);
  if (exact >= 0) return { start: exact, end: exact + word.length };
  const loose = new RegExp(
    word
      .split(/\s+/)
      .map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("\\s*"),
    "u",
  );
  const m = loose.exec(chunk.slice(from));
  return m ? { start: from + m.index, end: from + m.index + m[0].length } : null;
}

// --- the real loader --------------------------------------------------------

type GpuAdapter = { features: { has(name: string): boolean } };
type GpuNavigator = { gpu?: { requestAdapter(): Promise<GpuAdapter | null> } };

/** True only if the browser has WebGPU, an adapter, and the f16 shader feature. */
export async function webGpuUsable(): Promise<boolean> {
  if (typeof navigator === "undefined") return false;
  const gpu = (navigator as unknown as GpuNavigator).gpu;
  if (!gpu) return false;
  try {
    const adapter = await gpu.requestAdapter();
    return !!adapter && adapter.features.has("shader-f16");
  } catch {
    return false;
  }
}

const loadTransformersPipeline: PipelineLoader = async () => {
  if (!(await webGpuUsable())) throw new Error("WebGPU with shader-f16 is not available");
  const { pipeline } = await import("@huggingface/transformers");
  const classify = (await pipeline("token-classification", NER_MODEL_ID, {
    device: "webgpu",
    dtype: NER_DTYPE,
  })) as unknown as (text: string, o: { aggregation_strategy: "simple" }) => Promise<RawEntity[]>;
  return (text) => classify(text, { aggregation_strategy: "simple" });
};

const defaultDetector = createEntityDetector(loadTransformersPipeline);

/** The shared detector: loads on first use, caches the model, degrades to `[]`. */
export function detectEntities(text: string): Promise<Span[]> {
  return defaultDetector.detectEntities(text);
}

/** `idle` until first use, then `loading`, `ready` or `unavailable`. */
export function nerStatus(): NerStatus {
  return defaultDetector.status();
}
