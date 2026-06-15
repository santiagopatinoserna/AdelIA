"use client";

import { useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Sparkles, Loader2, RotateCcw, ShieldCheck, Copy, Check } from "lucide-react";

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
    setBusy(true);
    setError(null);
    setText("");
    setCitations([]);
    try {
      for await (const ev of streamChat(composePrompt(), null, locale)) {
        if (ev.type === "token") setText((prev) => prev + ev.content);
        else if (ev.type === "final") setCitations(ev.citations ?? []);
        else if (ev.type === "error") setError(ev.content);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-12 border-t border-line pt-8">
      <h2 className="flex items-center gap-2 text-lg text-pine-900">
        <Sparkles className="h-4.5 w-4.5 text-honey-500" strokeWidth={2} />
        {t("valoracionTitle")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t("valoracionLead")}</p>

      {!text && !busy && (
        <button
          type="button"
          onClick={generate}
          disabled={answeredCount === 0}
          className="ad-btn ad-btn-primary mt-4 px-5 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles className="h-4 w-4" strokeWidth={2.2} />
          {t("generateBtn")}
        </button>
      )}
      {answeredCount === 0 && !busy && !text && (
        <p className="mt-2 text-xs text-ink-faint">{t("needMoreAnswers")}</p>
      )}

      {(busy || text) && (
        <div className="ad-card mt-4 p-5">
          {busy && !text && (
            <p className="flex items-center gap-2 text-sm text-ink-soft">
              <Loader2 className="h-4 w-4 animate-spin text-pine-400" strokeWidth={2} />
              {t("generating")}
            </p>
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
                <ShieldCheck className="h-3.5 w-3.5 text-pine-400" strokeWidth={2} />
                {t("valoracionDisclaimer")}
              </p>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={copyOutput}
                  className="ad-btn ad-btn-ghost px-3 py-1.5 text-xs"
                >
                  {copied ? (
                    <Check className="h-3.5 w-3.5 text-pine-500" strokeWidth={2.4} />
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
        <div className="mt-4 rounded-xl border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {t("valoracionError")}
        </div>
      )}
    </section>
  );
}
