"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { signIn } from "next-auth/react";
import { ArrowUpRight, Loader2, Mic, MicOff, Phone, ShieldAlert, Stethoscope } from "lucide-react";
import { AnswerSources } from "@/components/answer-sources";
import { AnswerContent, type AnswerCorpusStats } from "@/components/answer-content";
import { useDictation } from "@/hooks/use-dictation";
import type { DemoAnswerKind, DemoClarify, DemoIntent, EvidenceCitation } from "@/lib/chat-types";
import { keepLandingQuestion } from "@/lib/landing-question";

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

// "La demo es la app real" (2026-11-06). Her first question, a suggestion or
// "Grabar la consulta" opens the real panel with Lucía: a guest session is
// created without asking for anything (lib/auth.ts, provider "guest") and the
// question is answered there by the agent, once. Only when the guest cannot
// be created (the API's anti-bot brake, an outage) does this page answer
// itself through the keyless /api/demo/ask, so the question is never lost.
// `hasSession`: she already has a space (or an account) in this browser.
async function openGuestSpace(locale: string, hasSession: boolean): Promise<boolean> {
  if (hasSession) return true;
  try {
    const res = await signIn("guest", { redirect: false, locale });
    return Boolean(res?.ok && !res.error);
  } catch {
    return false;
  }
}

export function DemoAsk({ suggested, corpusStats, hasSession = false, consentNote }: {
  suggested: string[];
  corpusStats?: AnswerCorpusStats;
  hasSession?: boolean;
  /** What asking keeps and where to delete it, drawn by the page under the button. */
  consentNote?: ReactNode;
}) {
  const t = useTranslations("demo");
  const tg = useTranslations("guestSpace");
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
    // A bounded wait always leaves the visitor an actionable retry. It covers
    // opening her space AND the fallback answer: one wait, one bound.
    const timeout = setTimeout(() => controller.abort(), 60000);
    let leaving = false;
    setBusy(true);
    setSlow(false);
    setAsked(trimmed);
    setError(null);
    setResult(null);
    try {
      // A clarify press belongs to an answer this page already drew (the
      // keyless fallback): it stays here.
      if (!clarification && (await openGuestSpace(locale, hasSession)) && !controller.signal.aborted) {
        leaving = true;
        const key = keepLandingQuestion(trimmed);
        window.location.assign(`/${locale}/dashboard?ask=${encodeURIComponent(key)}`);
        return;
      }
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
      // Leaving for the panel: stay busy until the page goes, so a second
      // tap cannot send the question twice.
      if (!leaving) {
        pending.current = null;
        setBusy(false);
      }
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
            className={`ad-field block w-full resize-none text-base leading-relaxed placeholder:text-ink-faint${
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
              // Bottom right of the field: next to "Preguntar" and inside the
              // thumb's reach, where the top corner was not. Tinted so it
              // reads as a way in for someone who cannot type right now.
              className={`absolute bottom-1.5 right-1.5 inline-flex h-11 w-11 items-center justify-center rounded-full transition-colors ${
                dictation.listening
                  ? "bg-primary text-on-primary motion-safe:animate-pulse"
                  : "bg-primary-tint text-on-primary-tint hover:bg-surface-2"}`}
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
            className="ad-btn ad-btn-primary ad-btn-lg w-full sm:w-auto sm:min-w-36"
          >
            {busy && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden />}
            {busy ? t("askBusy") : t("askCta")}
          </button>
        </div>
        {consentNote && (
          <p data-testid="landing-consent" className="mt-2 text-sm leading-relaxed text-ink-soft">
            {consentNote}
          </p>
        )}
        {/* The appointment recorder of the real app, in her guest space. */}
        <button
          type="button"
          data-testid="landing-record"
          disabled={busy}
          onClick={async () => {
            if (pending.current) return;
            setBusy(true);
            if (await openGuestSpace(locale, hasSession)) {
              window.location.assign(`/${locale}/dashboard/consulta/grabar`);
              return;
            }
            setBusy(false);
            setError(t("errorUnavailable"));
          }}
          className="mt-3 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary-text underline underline-offset-4 disabled:opacity-60"
        >
          <Stethoscope className="h-4 w-4" aria-hidden />
          {tg("landingRecord")}
        </button>
      </form>

      {/* Short, persistent live region, rather than announcing every citation. */}
      <div role="status" aria-atomic="true" className="text-sm leading-relaxed text-ink-soft">
        {busy && (
          <p data-testid="demo-loading" className="mt-4 flex items-center gap-2.5 text-base text-ink">
            <span className="ad-pulse-dot shrink-0" aria-hidden />
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
          <h2 id="demo-clarify-title" className="text-title text-ink">
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
                className="ad-btn ad-btn-ghost ad-btn-lg w-full justify-start"
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
          {result.kind === "red_flag" ? (
            // The emergency leads, and its action is one tap: the number is
            // read from the code's own fixed reply, never from a model, and
            // the button only exists when that reply names one. The reply
            // itself follows in full, untouched.
            <div data-testid="urgent-block" className="rounded-2xl border border-error-tint-line bg-error-tint p-4">
              <h2 id="demo-answer-title" className="text-title text-error-text">
                {t("urgentAnswerTitle")}
              </h2>
              <p className="mt-2 flex items-start gap-2 text-base leading-relaxed text-error-text">
                <ShieldAlert className="mt-1 h-4 w-4 shrink-0" aria-hidden />
                <span>{t("redFlagNote")}</span>
              </p>
              {emergencyNumber(result.answer) && (
                <a
                  data-testid="call-emergency"
                  href={`tel:${emergencyNumber(result.answer)}`}
                  className="ad-btn ad-btn-danger ad-btn-lg mt-4 w-full"
                >
                  <Phone className="h-5 w-5" aria-hidden />
                  {t("callEmergency", { number: emergencyNumber(result.answer)! })}
                </a>
              )}
            </div>
          ) : (
            <h2 id="demo-answer-title" className="text-title text-ink">
              {t(titleKey(result))}
            </h2>
          )}
          <AnswerContent>
            {result.kind === "evidence_only" ? t("evidenceOnlyNote") : result.answer}
          </AnswerContent>
          {/* Fixed clinical line comes from the API, unchanged (audit 3.8). */}
          <p data-testid="answer-disclaimer" className="mt-6 border-t border-line pt-4 text-sm leading-relaxed text-ink-soft">
            {result.disclaimer}
          </p>
          <AnswerSources
            citations={result.evidence_citations}
            kind={result.kind}
            shortAnswer={isShortAnswer(result)}
            answer={result.answer}
            corpusStats={corpusStats}
          />
          {/* Under her thumb for the whole length of a long plan, settling at
              the end of the answer (sticky, not fixed). Not on an emergency:
              there the only action that matters is the call. */}
          <div className={result.kind === "red_flag" ? "mt-5" : "ad-sticky-action mt-5"}>
            <button
              data-testid="ask-another"
              type="button"
              onClick={() => {
                setResult(null);
                setQuestion("");
                requestAnimationFrame(() => form.current?.querySelector("textarea")?.focus());
              }}
              className="ad-btn ad-btn-ghost ad-btn-lg w-full"
            >
              {t("askAnother")}
            </button>
          </div>
        </section>
      )}

      {/* Gone while she waits, not just disabled: three greyed questions under
          "Pensando…" were the only thing on the screen to read. */}
      <div className="mt-5" hidden={Boolean(result) || busy}>
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

// The title says what kind of answer this is, never more: a refusal is not
// "Tu plan" (handoff 5.1, "Ton plan" over no_evidence in production), and
// sources found without a composed answer are titled as sources.
function titleKey(result: DemoAnswer) {
  if (result.kind === "experience_only") return "experienceOnlyTitle";
  if (result.kind === "no_evidence") return "noEvidenceTitle";
  if (result.kind === "evidence_only") return "evidenceOnlyTitle";
  return isShortAnswer(result) ? "shortAnswerTitle" : "answerTitle";
}

// The number in the fixed red-flag frame of the API (answer_contract,
// "Llama al {number}" / "Call {number}" / "Appelez le {number}"), or null.
// Only that frame counts: a number elsewhere in the text is not a phone.
const EMERGENCY_FRAME = /(?:Llama al|Call|Appelez le) (\d{2,3})\b/;
function emergencyNumber(answer: string): string | null {
  return EMERGENCY_FRAME.exec(answer)?.[1] ?? null;
}

// A fact question answered in one sentence is not a plan, and the page must
// not call it one. Only an `answer` qualifies: a referral or a refusal keeps
// its own wording whatever the router said.
function isShortAnswer(result: DemoAnswer): boolean {
  return result.kind === "answer" && result.intent === "question";
}
