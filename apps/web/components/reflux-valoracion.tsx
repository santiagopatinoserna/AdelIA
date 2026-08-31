"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Sparkles, Loader2, RotateCcw, ShieldCheck, Copy, Check, AlertTriangle, Info } from "lucide-react";

import { streamChat, type Citation } from "@/lib/chat-client-browser";
import { Markdown } from "./markdown";
import { CitationCard } from "./citation-card";

type Question = {
  id: string;
  text: string;
  type: string;
  unit?: string;
};
type Section = { id: string; title: string; questions: Question[] };
type Answer = string | string[] | Record<string, string> | undefined;

function isAnswered(v: Answer): boolean {
  if (v == null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.values(v).some((x) => (x ?? "").toString().trim() !== "");
  return v.toString().trim() !== "";
}

function formatAnswer(q: Question, v: Answer): string {
  if (q.type === "number") return `${v}${q.unit ? ` ${q.unit}` : ""}`;
  if (Array.isArray(v)) return v.join(", ");
  if (v && typeof v === "object") {
    return Object.entries(v)
      .filter(([, x]) => (x ?? "").toString().trim() !== "")
      .map(([k, x]) => `${k}: ${x}`)
      .join(", ");
  }
  return String(v ?? "");
}

const STORAGE_KEY = "adelia:valoracion:v1";

// Stable fingerprint of the answered questions — lets us detect when the
// answers have changed since a saved valoración, so we never present a stale
// medical assessment as current.
function fingerprint(a: Record<string, Answer>): string {
  return JSON.stringify(
    Object.keys(a)
      .filter((k) => isAnswered(a[k]))
      .sort()
      .map((k) => [k, a[k]]),
  );
}

// Realizes the "valoración fundamentada": composes the filled answers into a
// prompt and streams a cited assessment through the EXISTING chat/RAG endpoint
// (1,936-article corpus + the child's data). No backend change — frontend
// orchestration of capability that already exists.
export function RefluxValoracion({
  sections,
  answers,
}: {
  sections: Section[];
  answers: Record<string, Answer>;
}) {
  const t = useTranslations("questionnaire");
  const locale = useLocale();
  const [text, setText] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Fingerprint of the answers the current valoración was generated from.
  const [generatedFp, setGeneratedFp] = useState("");
  // Scroll the streamed result into view once the first token lands (it can
  // render below the fold after the mom taps "Generar").
  const outputRef = useRef<HTMLDivElement | null>(null);
  const scrolledRef = useRef(false);

  // Restore a saved valoración so it survives a reload.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d.text) {
          setText(d.text);
          setCitations(Array.isArray(d.citations) ? d.citations : []);
          setGeneratedFp(d.fp ?? "");
        }
      }
    } catch {
      /* corrupt store — ignore */
    }
  }, []);

  // True when the answers have changed since the shown valoración was made.
  const isStale = !!text && !busy && fingerprint(answers) !== generatedFp;

  async function copyOutput() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — no-op */
    }
  }

  const answeredCount = sections
    .flatMap((s) => s.questions)
    .filter((q) => isAnswered(answers[q.id])).length;

  function composePrompt(): string {
    const lines: string[] = [];
    for (const sec of sections) {
      const answered = sec.questions.filter((q) => isAnswered(answers[q.id]));
      if (!answered.length) continue;
      lines.push(`### ${sec.title}`);
      for (const q of answered) lines.push(`- ${q.text} → ${formatAnswer(q, answers[q.id])}`);
    }
    return (
      `Este es el control estructurado del reflujo de mi bebé (anamnesis):\n\n${lines.join("\n")}\n\n` +
      `Basándote en la evidencia clínica pediátrica del reflujo, dame una VALORACIÓN FUNDAMENTADA y CITADA: ` +
      `1) ¿el manejo actual es adecuado según las guías?, 2) señales de alarma a vigilar, ` +
      `3) preguntas concretas para llevar al pediatra. Sé específico, prudente, y cita la evidencia.`
    );
  }

  async function generate() {
    const fp = fingerprint(answers);
    setBusy(true);
    setError(null);
    setText("");
    setCitations([]);
    scrolledRef.current = false;
    let acc = "";
    let cits: Citation[] = [];
    try {
      for await (const ev of streamChat(composePrompt(), null, locale)) {
        if (ev.type === "token") {
          acc += ev.content;
          setText(acc);
          if (!scrolledRef.current) {
            scrolledRef.current = true;
            requestAnimationFrame(() =>
              outputRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
            );
          }
        } else if (ev.type === "final") {
          cits = ev.citations ?? [];
          setCitations(cits);
        } else if (ev.type === "error") {
          setError(ev.content);
        }
      }
      if (acc) {
        setGeneratedFp(fp);
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify({ fp, text: acc, citations: cits }));
        } catch {
          /* private mode / quota — keep in memory */
        }
      }
    } catch (e) {
      setError(t("actionError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-12 border-t border-line pt-8">
      <h2 className="flex items-center gap-2 text-lg text-ink">
        <Sparkles className="h-4.5 w-4.5 text-accent-text" strokeWidth={2} />
        {t("valoracionTitle")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t("valoracionLead")}</p>

      {!text && !busy && (
        <div className="mt-4">
          <button
            type="button"
            onClick={generate}
            disabled={answeredCount === 0}
            className="ad-btn ad-btn-primary px-5 py-2.5 text-sm disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-surface-2 disabled:text-ink-faint disabled:shadow-none"
          >
            <Sparkles className="h-4 w-4" strokeWidth={2.2} />
            {t("generateBtn")}
          </button>
          {answeredCount === 0 && (
            <p className="mt-2 flex items-center gap-1.5 rounded-lg bg-surface-2 px-3 py-2 text-xs font-medium text-ink-soft">
              <Info className="h-3.5 w-3.5 shrink-0 text-accent-text" strokeWidth={2.2} />
              {t("needMoreAnswers")}
            </p>
          )}
        </div>
      )}

      {(busy || text) && (
        <div ref={outputRef} className="ad-card mt-4 scroll-mt-28 p-5">
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-accent-tint-line bg-accent-tint/50 p-2.5 text-xs leading-relaxed text-ink">
            <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-accent-text" strokeWidth={2.2} />
            {t("valoracionDisclaimerTop")}
          </div>
          {isStale && (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-error-tint-line bg-error-tint p-2.5 text-xs text-error-text">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-error-text" strokeWidth={2.2} />
              <span className="flex-1">{t("valoracionStale")}</span>
              <button
                type="button"
                onClick={generate}
                className="ad-btn ad-btn-ghost px-2.5 py-1 text-xs"
              >
                <RotateCcw className="h-3 w-3" strokeWidth={2.2} />
                {t("regenerateValoracion")}
              </button>
            </div>
          )}
          {busy && !text && (
            <div className="flex items-center gap-3 py-2">
              <Loader2 className="h-6 w-6 shrink-0 animate-spin text-primary-text" strokeWidth={2} />
              <div>
                <p className="text-base font-medium text-ink">{t("generating")}</p>
                <p className="mt-0.5 text-sm text-ink-soft">{t("generatingHint")}</p>
              </div>
            </div>
          )}
          {text && (
            <div className="text-[15px] text-ink">
              <Markdown>{text}</Markdown>
            </div>
          )}
          {citations.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="ad-eyebrow">{t("sourcesLabel")}</div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {citations.map((c, i) => (
                  <CitationCard key={c.chunk_id} citation={c} index={i + 1} locale={locale} />
                ))}
              </div>
            </div>
          )}
          {!busy && text && (
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3">
              <p className="flex items-center gap-1.5 text-xs text-ink-faint">
                <ShieldCheck className="h-3.5 w-3.5 text-primary-text" strokeWidth={2} />
                {t("valoracionDisclaimer")}
              </p>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={copyOutput}
                  className="ad-btn ad-btn-ghost px-3 py-1.5 text-xs"
                >
                  {copied ? (
                    <Check className="h-3.5 w-3.5 text-primary-text" strokeWidth={2.4} />
                  ) : (
                    <Copy className="h-3.5 w-3.5" strokeWidth={2} />
                  )}
                  {copied ? t("copied") : t("copy")}
                </button>
                <button
                  type="button"
                  onClick={generate}
                  className="ad-btn ad-btn-ghost px-3 py-1.5 text-xs"
                >
                  <RotateCcw className="h-3.5 w-3.5" strokeWidth={2} />
                  {t("regenerateValoracion")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
          {t("valoracionError")}
        </div>
      )}
    </section>
  );
}
