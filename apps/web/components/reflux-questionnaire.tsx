"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Baby,
  HelpCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Circle,
  ChevronDown,
  Clock,
  Loader2,
  Trash2,
} from "lucide-react";

import { RefluxValoracion } from "./reflux-valoracion";

type Question = {
  id: string;
  text: string;
  type: "number" | "choice" | "multichoice" | "text" | "med_detail";
  why: string;
  source: string;
  unit?: string;
  options?: string[];
  fields?: string[];
  alarm?: boolean;
};
type Section = { id: string; title: string; questions: Question[] };
type Questionnaire = { _meta?: { title?: string }; sections: Section[] };

const STORAGE_KEY = "adelia:reflux-questionnaire:v1";

type Answer = string | string[] | Record<string, string> | undefined;

function isAnswered(v: Answer): boolean {
  if (v == null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.values(v).some((x) => (x ?? "").toString().trim() !== "");
  return v.toString().trim() !== "";
}

export function RefluxQuestionnaire() {
  const t = useTranslations("questionnaire");
  const tc = useTranslations("common");
  const [data, setData] = useState<Questionnaire | null>(null);
  const [error, setError] = useState(false);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [hydrated, setHydrated] = useState(false);
  const [showSummary, setShowSummary] = useState(false);

  // Hydrate saved answers before we start persisting (avoid clobbering them).
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setAnswers(JSON.parse(raw));
    } catch {
      /* corrupt store — start fresh */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(answers));
    } catch {
      /* private mode / quota — answers stay in memory */
    }
  }, [answers, hydrated]);

  useEffect(() => {
    let active = true;
    fetch("/api/backend/clinical/reflux-questionnaire")
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((d: Questionnaire) => active && setData(d))
      .catch(() => active && setError(true));
    return () => {
      active = false;
    };
  }, []);

  const allQuestions = useMemo(
    () => (data ? data.sections.flatMap((s) => s.questions) : []),
    [data],
  );
  const total = allQuestions.length;
  const done = allQuestions.filter((q) => isAnswered(answers[q.id])).length;
  const pct = total ? Math.round((done / total) * 100) : 0;

  // Per-section status for the resume-after-interruption summary:
  // any unanswered alarm question → ⚠, all answered → ✓, none → ○.
  const sectionStatus = useMemo(() => {
    if (!data) return [] as { id: string; title: string; status: "alarm" | "done" | "pending"; done: number; total: number }[];
    return data.sections.map((s) => {
      const d = s.questions.filter((q) => isAnswered(answers[q.id])).length;
      const hasAlarm = s.questions.some((q) => q.alarm && isAnswered(answers[q.id]));
      const status: "alarm" | "done" | "pending" = hasAlarm
        ? "alarm"
        : d === s.questions.length && d > 0
          ? "done"
          : "pending";
      return { id: s.id, title: s.title, status, done: d, total: s.questions.length };
    });
  }, [data, answers]);

  function jumpTo(id: string) {
    setShowSummary(false);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setAnswer(id: string, value: Answer) {
    setAnswers((prev) => ({ ...prev, [id]: value }));
  }
  function reset() {
    if (confirm(t("resetConfirm"))) setAnswers({});
  }

  const medLabel: Record<string, string> = {
    nombre: t("medName"),
    dosis: t("medDose"),
    desde_cuando: t("medSince"),
    respuesta: t("medResponse"),
  };

  if (error) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <div role="alert" className="rounded-xl border border-error-tint-line bg-error-tint p-4 text-sm text-error-text">
          {t("loadError")}
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary-text" strokeWidth={2} aria-label={tc("loading")} />
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      {/* Header */}
      <div className="flex items-start gap-3">
        <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
          <Baby className="h-6 w-6" strokeWidth={1.9} />
        </span>
        <div>
          <h1 className="text-2xl text-ink">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-soft">{t("subtitle")}</p>
        </div>
      </div>
      <p className="ad-eyebrow mt-4 flex items-center gap-1.5 normal-case tracking-normal">
        <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.2} />
        <span className="font-sans">{t("intro")}</span>
      </p>

      {/* Sticky progress — sits just below the dashboard top bar (h-14) */}
      <div className="sticky top-14 z-10 -mx-6 mt-6 border-y border-line bg-canvas/85 px-6 py-3 backdrop-blur-md">
        <div className="flex items-center justify-between gap-3 text-xs">
          <button
            type="button"
            onClick={() => setShowSummary((v) => !v)}
            aria-expanded={showSummary}
            className="inline-flex items-center gap-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
          >
            <Clock className="h-3.5 w-3.5 text-primary-text" strokeWidth={2.2} />
            <span className="font-medium">{t("progressContext")}</span>
            <span className="text-ink-faint">· {t("progress", { done, total })}</span>
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${showSummary ? "rotate-180" : ""}`}
              strokeWidth={2.2}
            />
          </button>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Collapsible per-section summary — tap a row to jump and resume. */}
        {showSummary && (
          <div className="mt-3 space-y-1 border-t border-line pt-3">
            {sectionStatus.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => jumpTo(s.id)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-ink-soft transition-colors hover:bg-surface-2"
              >
                {s.status === "alarm" ? (
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-error-text" strokeWidth={2.4} />
                ) : s.status === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-primary-text" strokeWidth={2.4} />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-ink-faint" strokeWidth={2} />
                )}
                <span className="flex-1 truncate">{s.title}</span>
                <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                  {s.done}/{s.total}
                </span>
              </button>
            ))}
            <button
              type="button"
              onClick={reset}
              className="mt-1 inline-flex items-center gap-1.5 rounded-lg border border-error-tint-line bg-error-tint px-2.5 py-1.5 text-[11px] font-medium text-error-text transition-colors hover:bg-error-tint-line"
            >
              <Trash2 className="h-3 w-3" strokeWidth={2.2} />
              {t("reset")}
            </button>
          </div>
        )}
      </div>

      {/* Sections */}
      <div className="mt-8 space-y-10">
        {data.sections.map((section) => {
          const isAlarm = section.id === "red_flags";
          return (
            <section
              key={section.id}
              id={`section-${section.id}`}
              className={`scroll-mt-28 ${isAlarm ? "rounded-2xl bg-error-tint/50 p-4 ring-1 ring-error-tint-line sm:p-5" : ""}`}
            >
              <h2
                className={`flex items-center gap-2 text-lg ${isAlarm ? "text-error-text" : "text-ink"}`}
              >
                {isAlarm && <AlertTriangle className="h-4 w-4" strokeWidth={2.2} />}
                {section.title}
              </h2>
              {isAlarm && (
                <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-error-tint/60 px-3 py-2 text-xs font-medium leading-relaxed text-error-text">
                  {t("redFlagsBanner")}
                </p>
              )}
              <div className="mt-4 space-y-3">
                {section.questions.map((q) => (
                  <QuestionCard
                    key={q.id}
                    q={q}
                    value={answers[q.id]}
                    onChange={(v) => setAnswer(q.id, v)}
                    t={t}
                    medLabel={medLabel}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {/* Evidence-based assessment from the answers (existing chat/RAG endpoint) */}
      <RefluxValoracion sections={data.sections} answers={answers} />

      {/* Footer: save indicator */}
      <p className="mt-10 flex items-center justify-center gap-1.5 text-xs text-ink-faint">
        <Check className="h-3.5 w-3.5 text-primary-text" strokeWidth={2.4} />
        {t("saved")}
      </p>
    </main>
  );
}

function QuestionCard({
  q,
  value,
  onChange,
  t,
  medLabel,
}: {
  q: Question;
  value: Answer;
  onChange: (v: Answer) => void;
  t: ReturnType<typeof useTranslations>;
  medLabel: Record<string, string>;
}) {
  const answered = isAnswered(value);
  return (
    <div
      className={`ad-card p-4 transition-colors ${q.alarm ? "border-error-tint-line" : ""} ${answered ? "ring-1 ring-primary-tint-line" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-ink">{q.text}</p>
        {q.alarm && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-error-tint px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-error-text ring-1 ring-error-tint-line">
            <AlertTriangle className="h-2.5 w-2.5" strokeWidth={2.4} />
            {t("alarm")}
          </span>
        )}
      </div>

      {/* Input by type */}
      <div className="mt-3">
        {q.type === "number" && (
          <div className="flex items-center gap-2">
            <input
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={(value as string) ?? ""}
              onChange={(e) => onChange(e.target.value)}
              aria-label={q.text}
              className="w-full max-w-[12rem] rounded-xl border border-line-control bg-surface px-3 py-2 text-base text-ink focus:border-primary-text sm:w-40"
            />
            {q.unit && <span className="text-sm text-ink-faint">{q.unit}</span>}
          </div>
        )}

        {q.type === "text" && (
          <textarea
            rows={2}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
            placeholder={t("answerPlaceholder")}
            aria-label={q.text}
            className="w-full rounded-xl border border-line-control bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-faint focus:border-primary-text"
          />
        )}

        {q.type === "choice" && (
          <div className="flex flex-wrap gap-2">
            {q.options?.map((opt) => (
              <label key={opt} className="cursor-pointer">
                <input
                  type="radio"
                  name={q.id}
                  checked={value === opt}
                  onChange={() => onChange(opt)}
                  aria-label={`${q.text}: ${opt}`}
                  className="peer sr-only"
                />
                <span className="inline-block rounded-full border border-line-control px-3 py-1.5 text-sm text-ink-soft transition-colors hover:border-primary-tint-line peer-checked:border-primary-text peer-checked:bg-primary-tint peer-checked:font-medium peer-checked:text-primary-text peer-focus-visible:ring-2 peer-focus-visible:ring-primary-tint-line">
                  {opt}
                </span>
              </label>
            ))}
          </div>
        )}

        {q.type === "multichoice" && (
          <div className="flex flex-wrap gap-2">
            {q.options?.map((opt) => {
              const arr = Array.isArray(value) ? value : [];
              const on = arr.includes(opt);
              return (
                <label key={opt} className="cursor-pointer">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange(on ? arr.filter((x) => x !== opt) : [...arr, opt])
                    }
                    aria-label={`${q.text}: ${opt}`}
                    className="peer sr-only"
                  />
                  <span className="inline-flex items-center gap-1 rounded-full border border-line-control px-3 py-1.5 text-sm text-ink-soft transition-colors hover:border-primary-tint-line peer-checked:border-primary-text peer-checked:bg-primary-tint peer-checked:font-medium peer-checked:text-primary-text peer-focus-visible:ring-2 peer-focus-visible:ring-primary-tint-line">
                    {on && <Check className="h-3 w-3" strokeWidth={3} />}
                    {opt}
                  </span>
                </label>
              );
            })}
          </div>
        )}

        {q.type === "med_detail" && (
          <div className="grid gap-2 sm:grid-cols-2">
            {q.fields?.map((f) => {
              const obj = (value as Record<string, string>) ?? {};
              return (
                <label key={f} className="block text-xs text-ink-soft">
                  {medLabel[f] ?? f}
                  <input
                    type="text"
                    value={obj[f] ?? ""}
                    onChange={(e) => onChange({ ...obj, [f]: e.target.value })}
                    aria-label={`${q.text} · ${medLabel[f] ?? f}`}
                    className="mt-1 w-full rounded-lg border border-line-control bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-primary-text"
                  />
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* Justification — the trazabilidad differentiator: every question grounded */}
      <div className="mt-3 rounded-lg bg-surface-2 px-3 py-2">
        <p className="flex gap-1.5 text-xs leading-relaxed text-ink-soft">
          <HelpCircle className="mt-px h-3.5 w-3.5 shrink-0 text-primary-text" strokeWidth={2} />
          <span>
            <span className="font-medium text-ink">{t("whyLabel")}: </span>
            {q.why}
          </span>
        </p>
        <p className="mt-1.5 pl-5 font-mono text-[11px] text-ink-faint">
          {t("sourceLabel")}: {q.source}
        </p>
      </div>
    </div>
  );
}
