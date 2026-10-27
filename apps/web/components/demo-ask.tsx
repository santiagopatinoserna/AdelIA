"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, Loader2, Mic, MicOff, ShieldAlert } from "lucide-react";
import { AnswerSources } from "@/components/answer-sources";
import { AnswerContent, type AnswerCorpusStats } from "@/components/answer-content";
import { useDictation } from "@/hooks/use-dictation";
import type { DemoAnswerKind, DemoClarify, DemoIntent, EvidenceCitation } from "@/lib/chat-types";

const SPEECH_LANG: Record<string, string> = { es: "es-ES", en: "en-GB", fr: "fr-FR" };

// The public demo has no session and receives one JSON response, not progress
// events. Never infer retrieval or generation stages from elapsed time.
// Mirrors the API's `kind` (apps/api/adelia/routers/demo.py): experience_only
// is "no guideline, but other mothers have something to say" and renders the
// one mothers section under its own title, never as a plan.
type DemoAnswer = {
  kind: DemoAnswerKind;
  intent?: DemoIntent | null;
  answer: string;
  evidence_citations: EvidenceCitation[];
  disclaimer: string;
  clarify?: DemoClarify;
};

type Clarification = { field: DemoClarify["field"]; value: string };

export function DemoAsk({ suggested, corpusStats }: {
  suggested: string[];
  corpusStats?: AnswerCorpusStats;
}) {
  const t = useTranslations("demo");
  const locale = useLocale();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DemoAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState("");
  const [slow, setSlow] = useState(false);
  const [typing, setTyping] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const pending = useRef<AbortController | null>(null);
  // Dictated text is appended, never sent: she reads it and fixes a wrong
  // word before pressing send, as with anything typed.
  const dictation = useDictation({
    lang: SPEECH_LANG[locale] ?? locale,
    onFinal: (text) => setQuestion((current) => {
      const base = current.trimEnd();
      return (base ? `${base} ${text}` : text).slice(0, 300);
    }),
  });

  useEffect(() => () => pending.current?.abort(), []);

  useEffect(() => {
    if (!busy) return;
    const timer = setTimeout(() => setSlow(true), 10000);
    return () => clearTimeout(timer);
  }, [busy]);

  // Only a keyboard resize while editing may adjust the viewport. A request
  // finishing must never take the reader away from the passage they are reading.
  useEffect(() => {
    if (!typing) return;
    function revealForm() {
      const el = form.current;
      if (!el) return;
      const vv = window.visualViewport;
      const bottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
      const overflow = el.getBoundingClientRect().bottom + 12 - bottom;
      if (overflow > 0) window.scrollBy({ top: overflow });
    }
    const target: EventTarget = window.visualViewport ?? window;
    target.addEventListener("resize", revealForm);
    return () => target.removeEventListener("resize", revealForm);
  }, [typing]);

  async function ask(text: string, clarification?: Clarification) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || trimmed.length > 300 || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    // A bounded request always leaves the visitor an actionable retry.
    const timeout = setTimeout(() => controller.abort(), 60000);
    setBusy(true);
    setSlow(false);
    setAsked(trimmed);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/demo/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "omit",
        signal: controller.signal,
        body: JSON.stringify({ question: trimmed, locale, ...(clarification ? { clarification } : {}) }),
      });
      if (!res.ok) {
        setError(t(res.status === 429 ? "errorBudget" :
          res.status === 503 ? "errorUnavailable" : "errorGeneric"));
        return;
      }
      setResult((await res.json()) as DemoAnswer);
    } catch {
      setError(t("errorGeneric"));
    } finally {
      clearTimeout(timeout);
      pending.current = null;
      setBusy(false);
    }
  }

  return (
    <div data-testid="demo-ask">
      <form
        hidden={Boolean(result) && !busy}
        ref={form}
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <label
          htmlFor="demo-question"
          className="sr-only"
        >
          {t("askTitle")}
        </label>
        <div className="relative">
          <textarea
            id="demo-question"
            rows={2}
            maxLength={300}
            value={question}
            onChange={(event) => { dictation.clearError(); setQuestion(event.target.value); }}
            onFocus={() => setTyping(true)}
            onBlur={() => setTyping(false)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }}
            enterKeyHint="send"
            placeholder={dictation.interim ? "" : t("askPlaceholder")}
            aria-label={t("askLabel")}
            aria-describedby="demo-question-help"
            className={`ad-field block w-full resize-y text-base leading-relaxed placeholder:text-ink-faint${
              dictation.supported ? " ad-field-mic" : ""}`}
          />
          {/* Words still being recognised, greyed after what she has typed. A
              mirror of the textarea, so the interim text starts where the
              caret would be; it is decoration until the final result lands. */}
          {dictation.interim && (
            <div
              aria-hidden
              className="ad-field-mirror pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words ad-field-mic text-base leading-relaxed"
            >
              <span className="invisible">{question.trimEnd()}{question.trimEnd() ? " " : ""}</span>
              <span data-testid="dictation-interim" className="text-ink-soft">{dictation.interim}</span>
            </div>
          )}
          {dictation.supported && (
            <button
              type="button"
              onClick={dictation.toggle}
              aria-label={t("dictate")}
              aria-pressed={dictation.listening}
              disabled={busy}
              className={`absolute right-1 top-1 inline-flex h-11 w-11 items-center justify-center rounded-full transition-colors ${
                dictation.listening
                  ? "bg-primary text-on-primary motion-safe:animate-pulse"
                  : "text-ink-soft hover:bg-surface-2 hover:text-ink"}`}
            >
              {dictation.listening ? <MicOff className="h-5 w-5" aria-hidden /> : <Mic className="h-5 w-5" aria-hidden />}
            </button>
          )}
        </div>
        {dictation.failed && (
          <p role="alert" className="mt-2 text-sm leading-relaxed text-error-text">{t("dictateError")}</p>
        )}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          {/* Enter-to-send is the convention of every chat; only an actual
              blocker (too short to send) earns a line of text. */}
          <p id="demo-question-help" aria-live="polite" className="text-xs leading-relaxed text-ink-soft">
            {question.trim().length > 0 && question.trim().length < 3 ? t("uxMinimum") : ""}
          </p>
          <button
            type="submit"
            disabled={busy || question.trim().length < 3}
            aria-busy={busy}
            className="ad-btn ad-btn-primary w-full text-base sm:w-auto sm:min-w-36"
          >
            {busy && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden />}
            {busy ? t("askBusy") : t("askCta")}
          </button>
        </div>
      </form>

      {/* Short, persistent live region, rather than announcing every citation. */}
      <div role="status" aria-atomic="true" className="text-sm leading-relaxed text-ink-soft">
        {busy && (
          <p data-testid="demo-loading" className="mt-4">
            {slow ? t("uxWaitingLong") : t("uxWaiting")}
          </p>
        )}
        {result && !busy && <p className="sr-only">{t("uxReady")}</p>}
      </div>

      {error && (
        <div className="mt-5 border-t border-line pt-4">
          <p role="alert" className="text-sm leading-relaxed text-error-text">{error}</p>
          <button
            type="button"
            onClick={() => void ask(asked)}
            className="mt-2 inline-flex min-h-11 items-center text-sm font-medium text-primary-text underline underline-offset-4"
          >
            {t("uxRetry")}
          </button>
        </div>
      )}

      {result && !busy && result.kind === "clarify" && result.clarify && (
        <section
          data-testid="demo-clarify"
          aria-labelledby="demo-clarify-title"
          className="mt-6 border-t border-line pt-5"
        >
          {/* One question, the values as buttons, and a way out that still
              answers: never a second question, never a dead end. */}
          <h2 id="demo-clarify-title" className="text-xl font-semibold text-ink">
            {result.clarify.question}
          </h2>
          <div className="mt-4 flex flex-col gap-2" role="group" aria-labelledby="demo-clarify-title">
            {result.clarify.options.map((option) => (
              <button
                key={option.value}
                data-testid="clarify-option"
                type="button"
                onClick={() => {
                  const field = result.clarify!.field;
                  void ask(asked, { field, value: option.value });
                }}
                className="ad-btn ad-btn-ghost min-h-11 w-full justify-start text-base"
              >
                {option.label}
              </button>
            ))}
          </div>
          <button
            data-testid="clarify-skip"
            type="button"
            onClick={() => {
              const { field, skip } = result.clarify!;
              void ask(asked, { field, value: skip.value });
            }}
            className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-primary-text underline underline-offset-4"
          >
            {result.clarify.skip.label}
          </button>
        </section>
      )}

      {result && !busy && result.kind !== "clarify" && (
        <section
          data-testid="demo-answer"
          aria-labelledby="demo-answer-title"
          className="mt-6 border-t border-line pt-5"
        >
          <h2 id="demo-answer-title" className={`text-xl font-semibold ${result.kind === "red_flag" ? "text-error-text" : "text-ink"}`}>
            {t(result.kind === "red_flag" ? "urgentAnswerTitle"
              : result.kind === "experience_only" ? "experienceOnlyTitle"
              : isShortAnswer(result) ? "shortAnswerTitle" : "answerTitle")}
          </h2>
          {result.kind === "red_flag" && (
            <p className="mt-4 flex items-start gap-2 rounded-lg bg-error-tint p-4 text-sm leading-relaxed text-error-text">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{t("redFlagNote")}</span>
            </p>
          )}
          <AnswerContent>
            {result.kind === "evidence_only" ? t("evidenceOnlyNote") : result.answer}
          </AnswerContent>
          {/* Fixed clinical line comes from the API, unchanged (audit 3.8). */}
          <p className="mt-5 border-t border-line pt-4 text-sm leading-relaxed text-ink-soft">
            {result.disclaimer}
          </p>
          <AnswerSources
            citations={result.evidence_citations}
            kind={result.kind}
            shortAnswer={isShortAnswer(result)}
            answer={result.answer}
            corpusStats={corpusStats}
          />
          <button
            data-testid="ask-another"
            type="button"
            onClick={() => {
              setResult(null);
              setQuestion("");
              requestAnimationFrame(() => form.current?.querySelector("textarea")?.focus());
            }}
            className="ad-btn ad-btn-ghost mt-4 w-full text-base"
          >
            {t("askAnother")}
          </button>
        </section>
      )}

      <div className="mt-5" hidden={Boolean(result)}>
        <ul className="mt-1 flex flex-col">
          {suggested.map((suggestion, index) => (
            <li key={suggestion} className="border-t border-line first:border-t-0">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setQuestion(suggestion);
                  void ask(suggestion);
                }}
                className="flex min-h-11 w-full items-center gap-3 rounded-md py-3 text-left text-sm leading-relaxed text-ink hover:bg-surface-2 disabled:cursor-wait disabled:text-ink-soft"
              >
                <span className="min-w-0 flex-1">{index === 0 ? <strong className="font-semibold">{suggestion}</strong> : suggestion}</span>
                <span className="sr-only">{t("uxSendSuggestion")}</span>
                <ArrowUpRight className="h-4 w-4 shrink-0 text-ink-soft" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// A fact question answered in one sentence is not a plan, and the page must
// not call it one. Only an `answer` qualifies: a referral or a refusal keeps
// its own wording whatever the router said.
function isShortAnswer(result: DemoAnswer): boolean {
  return result.kind === "answer" && result.intent === "question";
}
