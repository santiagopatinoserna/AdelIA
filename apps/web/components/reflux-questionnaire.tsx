"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Baby,
  HelpCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
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
        <div role="alert" className="rounded-xl border border-clay-100 bg-clay-50 p-4 text-sm text-clay-700">
          {t("loadError")}
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-pine-400" strokeWidth={2} aria-label={tc("loading")} />
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      {/* Header */}
      <div className="flex items-start gap-3">
        <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
          <Baby className="h-6 w-6" strokeWidth={1.9} />
        </span>
        <div>
          <h1 className="text-2xl text-pine-900">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-soft">{t("subtitle")}</p>
        </div>
      </div>
      <p className="ad-eyebrow mt-4 flex items-center gap-1.5 normal-case tracking-normal">
        <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.2} />
        <span className="font-sans">{t("intro")}</span>
      </p>

      {/* Sticky progress — sits just below the dashboard top bar (h-14) */}
      <div className="sticky top-14 z-10 -mx-6 mt-6 border-y border-line bg-canvas/85 px-6 py-3 backdrop-blur-md">
        <div className="flex items-center justify-between text-xs">
          <span className="font-mono text-ink-soft">{t("progress", { done, total })}</span>
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center gap-1 text-ink-faint transition-colors hover:text-clay-600"
          >
            <Trash2 className="h-3 w-3" strokeWidth={2} />
            {t("reset")}
          </button>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-gradient-to-r from-pine-500 to-pine-600 transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Sections */}
      <div className="mt-8 space-y-10">
        {data.sections.map((section) => {
          const isAlarm = section.id === "red_flags";
          return (
            <section key={section.id}>
              <h2
                className={`flex items-center gap-2 text-lg ${isAlarm ? "text-clay-700" : "text-pine-900"}`}
              >
                {isAlarm && <AlertTriangle className="h-4 w-4" strokeWidth={2.2} />}
                {section.title}
              </h2>
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
        <Check className="h-3.5 w-3.5 text-pine-500" strokeWidth={2.4} />
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
      className={`ad-card p-4 transition-colors ${q.alarm ? "border-clay-100" : ""} ${answered ? "ring-1 ring-pine-100" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-ink">{q.text}</p>
        {q.alarm && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-clay-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-clay-600 ring-1 ring-clay-100">
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
              value={(value as string) ?? ""}
              onChange={(e) => onChange(e.target.value)}
              aria-label={q.text}
              className="w-32 rounded-xl border border-line-strong bg-surface px-3 py-2 text-base text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
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
            className="w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
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
                <span className="inline-block rounded-full border border-line-strong px-3 py-1.5 text-sm text-ink-soft transition-colors hover:border-pine-200 peer-checked:border-pine-400 peer-checked:bg-pine-50 peer-checked:font-medium peer-checked:text-pine-700 peer-focus-visible:ring-2 peer-focus-visible:ring-pine-100">
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
                  <span className="inline-flex items-center gap-1 rounded-full border border-line-strong px-3 py-1.5 text-sm text-ink-soft transition-colors hover:border-pine-200 peer-checked:border-pine-400 peer-checked:bg-pine-50 peer-checked:font-medium peer-checked:text-pine-700 peer-focus-visible:ring-2 peer-focus-visible:ring-pine-100">
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
                    aria-label={`${q.text} — ${medLabel[f] ?? f}`}
                    className="mt-1 w-full rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
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
          <HelpCircle className="mt-px h-3.5 w-3.5 shrink-0 text-pine-400" strokeWidth={2} />
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
