// rehydrate: the inverse of redact, applied ONLY in the browser, when an answer
// is displayed. The server answers about `[NOMBRE_1]`; the parent reads her
// child's name. The mapping never leaves the device, which is the whole point.

import { PLACEHOLDER_SOURCE } from "./redact";
import type { RedactionMap } from "./types";

/**
 * Put the original text back. A placeholder the map does not know is left as
 * it is: better a visible `[NOMBRE_7]` than a wrong name, and the model may
 * well write a placeholder this device never minted.
 *
 * The replacement is a function, not a string, on purpose: a string would have
 * `$&` and `$1` in a value interpreted as replacement patterns.
 */
export function rehydrate(text: string, map: RedactionMap): string {
  return text.replace(new RegExp(PLACEHOLDER_SOURCE, "g"), (placeholder) =>
    Object.hasOwn(map, placeholder) ? map[placeholder] : placeholder,
  );
}

// The longest placeholder worth waiting for. `[TARJETA_SANITARIA_123456]` is
// 26; anything longer than this cannot be one and is released as ordinary text.
const MAX_PLACEHOLDER_LENGTH = 40;
const PLACEHOLDER_PREFIX = /^\[[A-Z_0-9]*$/;

export type StreamRehydrator = {
  /** Feed the next streamed chunk; returns the text that is safe to show now. */
  push(chunk: string): string;
  /** End of stream: whatever was held back, rehydrated as far as it can be. */
  flush(): string;
};

/**
 * Rehydration for a token stream. An answer arrives in small pieces and a
 * placeholder can be cut anywhere: `[NOM` then `BRE_1] tiene fiebre`. Naively
 * rehydrating each piece would show `[NOM` to the parent and never find a
 * placeholder. So a trailing `[...` that could still become one is held back
 * until the next chunk settles it.
 */
export function createStreamRehydrator(map: RedactionMap): StreamRehydrator {
  let held = "";
  return {
    push(chunk) {
      const buffer = held + chunk;
      const open = buffer.lastIndexOf("[");
      const tail = open >= 0 ? buffer.slice(open) : "";
      const mayComplete =
        tail !== "" && tail.length <= MAX_PLACEHOLDER_LENGTH && PLACEHOLDER_PREFIX.test(tail);
      held = mayComplete ? tail : "";
      return rehydrate(mayComplete ? buffer.slice(0, open) : buffer, map);
    },
    flush() {
      const rest = held;
      held = "";
      return rehydrate(rest, map);
    },
  };
}
