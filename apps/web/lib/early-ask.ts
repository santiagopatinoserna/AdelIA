import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";

// A question written before the page hydrates must never be lost (CI review
// of #72). On a slow phone the server's field is on screen and takes text
// seconds before React owns it. An Enter then only added a new line, the
// send button was still the server's disabled one, and the first render after
// hydration put the empty server value back: she thought she had asked and
// nothing happened, with no sign of it.
//
// Two halves. EARLY_ASK_SCRIPT (lib/early-ask-script.ts, a plain string the
// server layout can import) is inline in <head> (app/[locale]/layout.tsx),
// so it runs before any field exists and needs no bundle. Until a field's
// component has mounted it:
//   - keeps what she types (the DOM value, mirrored in window.__adeliaEarly
//     in case the field is ever re-created rather than hydrated);
//   - enables the field's send button by the same rule React will apply;
//   - turns Enter (or a tap on send) into "sent": the text stays, the field
//     turns read-only with aria-busy (a quiet "loading" look in globals.css),
//     and the event goes no further, so a form cannot reload the page and
//     React cannot also replay the event once it hydrates.
// useEarlyAsk, in the field's component, then takes the text into React state
// before anything can re-render the field, and sends a queued question once.
// The script only reads and writes attributes on the field and the button
// (both carry suppressHydrationWarning); it adds no node, so hydration still
// matches the server's markup. No provider state changes on mount (7adb21c):
// the hook updates the field's own component only.

type EarlyEntry = { text: string; sent: boolean };
type EarlyField = HTMLTextAreaElement & { __adeliaLive?: boolean };

declare global {
  interface Window { __adeliaEarly?: Record<string, EarlyEntry> }
}

/**
 * Picks up what the inline script kept for the field `name` (its
 * `data-early-ask`): the text goes to `keep` before the field's first
 * re-render, and a question she already sent goes to `send`, once.
 */
export function useEarlyAsk(
  name: string,
  field: RefObject<HTMLTextAreaElement | null>,
  keep: (text: string) => void,
  send: (text: string) => void,
) {
  const queued = useRef<string | null>(null);
  // Layout, not passive: React rewrites the field's value on its next render,
  // which a passive effect elsewhere (the mic check) can trigger first.
  useLayoutEffect(() => {
    const el = field.current as EarlyField | null;
    if (!el) return;
    el.__adeliaLive = true;
    const store = typeof window === "undefined" ? undefined : window.__adeliaEarly;
    const early = store?.[name];
    if (store) delete store[name];
    const text = el.value || early?.text || "";
    if (el.hasAttribute("aria-busy")) {
      el.removeAttribute("aria-busy");
      el.readOnly = false;
    }
    if (!text.trim()) return;
    keep(text);
    if (early?.sent) queued.current = text;
    // Mount only: what the script kept belongs to the first render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const text = queued.current;
    queued.current = null;
    if (text) send(text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
