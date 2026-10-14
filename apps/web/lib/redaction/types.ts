// Shared types for the local redaction primitive. No imports, no DOM, no
// framework: everything under lib/redaction/ except ner.ts runs in plain Node,
// which is what lets its tests run without a browser.

/**
 * What a hit is. The names double as the placeholder labels, in Spanish like
 * the rest of the product: a hit of kind DNI becomes `[DNI_1]`.
 *
 * FRENCH NIR / CARTE VITALE share one kind on purpose: the number printed on a
 * Carte Vitale IS the NIR, there is no separate French "health card number".
 */
export type EntityKind =
  | "NOMBRE"
  | "DNI"
  | "NIE"
  | "NIR"
  | "TELEFONO"
  | "EMAIL"
  | "CODIGO_POSTAL"
  | "FECHA_NACIMIENTO"
  | "TARJETA_SANITARIA";

/** A half-open range `[start, end)` of UTF-16 code units in the original text. */
export type Span = {
  start: number;
  end: number;
  kind: EntityKind;
  /** Only set on spans that come from the model; the detectors are exact. */
  score?: number;
};

/** A detector is a pure function from text to the spans it recognises. */
export type Detector = (text: string) => Span[];

/** placeholder (`[DNI_1]`) -> the text it replaced. Never leaves the device. */
export type RedactionMap = Record<string, string>;

export type RedactionResult = {
  /** The text that may be sent to the server. */
  text: string;
  /** The way back. Local only: sending this anywhere defeats the whole point. */
  map: RedactionMap;
};
