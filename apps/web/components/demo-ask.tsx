"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AlertCircle, Loader2, Send, ShieldAlert, Sparkles } from "lucide-react";

import { EvidenceCard } from "@/components/evidence-card";
import type { EvidenceCitation } from "@/lib/chat-types";

/**
 * The asking half of the public demo (audit 4.6).
 *
 * It talks to /api/demo/ask, which forwards to the API WITHOUT a session:
 * there is no account here, and there is nothing to persist. The answer comes
 * back in one JSON response rather than over SSE because a page with no
 * transcript has nothing to stream into.
 *
 * `kind` is what the SERVER decided, and the three non-answers are as much
 * the product as the answer is: a red flag is refused by code before any
 * model call, "no_evidence" is the refusal the corpus forces when nothing
 * supports an answer, and "evidence_only" is retrieval succeeding while
 * generation fails. Each gets its own frame so a visitor can tell them apart.
 */
type DemoAnswer = {
  kind: "answer" | "red_flag" | "no_evidence" | "evidence_only";
  answer: string;
  evidence_citations: EvidenceCitation[];
  disclaimer: string;
};

export function DemoAsk({ suggested }: { suggested: string[] }) {
  const t = useTranslations("demo");
  const locale = useLocale();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DemoAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const form = useRef<HTMLFormElement>(null);
  const [typing, setTyping] = useState(false);

  // Keyboard up on a phone: keep the whole form, field AND "Preguntar", above
  // it. The browser scrolls the focused field into view and nothing else, so
  // the button used to end up behind the keyboard. `visualViewport` is what
  // shrinks when the keyboard opens (the layout viewport does not, on iOS and
  // on Chrome's default), so the edge to clear is read from it.
  useEffect(() => {
    if (!typing) return;
    function revealForm() {
      const el = form.current;
      if (!el) return;
      const vv = window.visualViewport;
      const visibleBottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
      const overflow = el.getBoundingClientRect().bottom + 12 - visibleBottom;
      if (overflow > 0) window.scrollBy({ top: overflow });
    }
    revealForm();
    const target: EventTarget = window.visualViewport ?? window;
    target.addEventListener("resize", revealForm);
    return () => target.removeEventListener("resize", revealForm);
  }, [typing]);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/demo/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // No cookies: the demo needs no identity and must not carry one.
        credentials: "omit",
        body: JSON.stringify({ question: trimmed, locale }),
      });
      if (res.status === 429) {
        setError(t("errorBudget"));
        return;
      }
      if (res.status === 503) {
        setError(t("errorUnavailable"));
        return;
      }
      if (!res.ok) {
        setError(t("errorGeneric"));
        return;
      }
      setResult((await res.json()) as DemoAnswer);
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="demo-ask">
      <form
        ref={form}
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor="demo-question" className="ad-eyebrow block">
          {t("askTitle")}
        </label>
        <textarea
          id="demo-question"
          rows={3}
          maxLength={300}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onFocus={() => setTyping(true)}
          onBlur={() => setTyping(false)}
          // Enter sends and Shift+Enter breaks the line, as in every chat the
          // visitor already uses. It used to only add a newline: an automated
          // check typed a question, pressed Enter and the page stayed put, and
          // on a phone the button can be behind the keyboard. Routed through
          // requestSubmit so there is one send path (onSubmit above, with its
          // minimum length and busy guards). `isComposing`: Enter that
          // confirms an IME candidate (and some Android keyboards' word
          // suggestions) must not send half a sentence.
          onKeyDown={(e) => {
            if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }}
          enterKeyHint="send"
          placeholder={t("askPlaceholder")}
          aria-label={t("askLabel")}
          className="ad-field mt-2 w-full resize-y"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="ad-btn ad-btn-primary mt-3 w-full py-3 text-base"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
          ) : (
            <Send className="h-4 w-4" strokeWidth={2.2} />
          )}
          {busy ? t("askBusy") : t("askCta")}
        </button>
      </form>

      <div className="mt-5">
        <p className="ad-eyebrow">{t("suggestedTitle")}</p>
        <ul className="mt-2 flex flex-col gap-2">
          {suggested.map((s) => (
            <li key={s}>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setQuestion(s);
                  void ask(s);
                }}
                className="ad-btn ad-btn-ghost w-full justify-start px-3.5 py-2.5 text-left text-sm"
              >
                <Sparkles className="h-3.5 w-3.5 shrink-0 text-accent-text" strokeWidth={2.2} />
                <span className="min-w-0 flex-1">{s}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-5 flex items-start gap-2 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2.2} />
          <span>{error}</span>
        </p>
      )}

      {result && (
        <section
          data-testid="demo-answer"
          aria-live="polite"
          className="ad-card ad-rise mt-6 p-5"
        >
          <p className="ad-eyebrow">{t("answerTitle")}</p>
          {result.kind === "red_flag" && (
            <p className="mt-2 flex items-start gap-2 rounded-xl border border-accent-tint-line bg-accent-tint/60 p-3 text-xs text-ink">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-accent-text" strokeWidth={2.2} />
              <span>{t("redFlagNote")}</span>
            </p>
          )}
          {result.kind === "evidence_only" ? (
            <p className="mt-2 text-sm leading-relaxed text-ink-soft">
              {t("evidenceOnlyNote")}
            </p>
          ) : (
            <p className="mt-2 whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
              {result.answer}
            </p>
          )}

          {result.evidence_citations.length > 0 && (
            <div className="mt-5">
              <p className="ad-eyebrow">{t("sourcesTitle")}</p>
              <div className="mt-2 flex flex-col gap-2">
                {result.evidence_citations.map((c) => (
                  <EvidenceCard key={`${c.tag}-${c.chunk_id}`} citation={c} />
                ))}
              </div>
            </div>
          )}

          {/* The same fixed clinical line the product paints under every
              answer (audit 3.8), in the visitor's language, sent by the API
              so the demo cannot drift from the wording the app uses. */}
          <p className="mt-5 flex items-start gap-1.5 border-t border-line pt-3 text-xs leading-snug text-ink-soft">
            <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0 text-accent-text" strokeWidth={2} aria-hidden />
            <span>{result.disclaimer}</span>
          </p>
        </section>
      )}
    </div>
  );
}
