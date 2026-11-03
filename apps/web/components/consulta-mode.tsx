"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  ChevronRight,
  Mic,
  MicOff,
  Sparkles,
  Loader2,
  RotateCcw,
  ShieldCheck,
  Copy,
  Check,
} from "lucide-react";

import { streamChat, type Citation } from "@/lib/chat-client-browser";
import { Link } from "@/lib/navigation";
import { AnswerContent } from "./answer-content";
import { CitationCard } from "./citation-card";

// Minimal shape of the Web Speech API (no DOM lib types ship for it).
type SpeechResultList = ArrayLike<ArrayLike<{ transcript: string }>>;
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { results: SpeechResultList }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};
type SpeechCtor = new () => SpeechRecognitionLike;

function getSpeechCtor(): SpeechCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const LANG: Record<string, string> = { es: "es-ES", en: "en-US", fr: "fr-FR" };
// Human-friendly label of the language the mic will transcribe in.
const MIC_LABEL: Record<string, string> = {
  es: "Español",
  en: "English",
  fr: "Français",
};

// Modo Consulta: the parent types/dictates what the doctor says, and AdelIA
// returns argued questions + safety flags cross-referenced with the child's
// data + evidence (cited) — via the existing chat/RAG endpoint. Ends the
// "sí doctor" asymmetry. Frontend orchestration, no backend change.
export function ConsultaMode() {
  const t = useTranslations("consulta");
  const locale = useLocale();
  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [micSupported, setMicSupported] = useState(false);
  const [copied, setCopied] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const fieldId = useId();

  // Survive a reload: a parent uses this mid-appointment, where the phone can
  // lock/reload — don't lose the argued questions. A consulta is point-in-time
  // (not tied to live data), so there's no staleness to guard against.
  useEffect(() => {
    try {
      const raw = localStorage.getItem("adelia:consulta:v1");
      if (raw) {
        const d = JSON.parse(raw);
        if (d.input) setInput(d.input);
        if (d.answer) setAnswer(d.answer);
        if (Array.isArray(d.citations)) setCitations(d.citations);
      }
    } catch {
      /* corrupt store — ignore */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    // Persist only when settled (not every streamed token).
    if (!hydrated || busy) return;
    try {
      localStorage.setItem(
        "adelia:consulta:v1",
        JSON.stringify({ input, answer, citations }),
      );
    } catch {
      /* private mode / quota — keep in memory */
    }
  }, [input, answer, citations, busy, hydrated]);

  async function copyOutput() {
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — no-op */
    }
  }
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const baseRef = useRef("");
  // Scroll the streamed answer into view when the first token lands — it can
  // render below the fold after the parent taps "Generar".
  const outputRef = useRef<HTMLDivElement | null>(null);
  const scrolledRef = useRef(false);

  useEffect(() => {
    setMicSupported(getSpeechCtor() !== null);
    return () => recRef.current?.stop();
  }, []);

  function toggleMic() {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const Ctor = getSpeechCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = LANG[locale] ?? "es-ES";
    rec.interimResults = true;
    rec.continuous = true;
    baseRef.current = input.trim() ? `${input.trim()} ` : "";
    rec.onresult = (e) => {
      let txt = "";
      for (let i = 0; i < e.results.length; i++) txt += e.results[i][0].transcript;
      setInput(baseRef.current + txt);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    rec.start();
    recRef.current = rec;
    setListening(true);
  }

  function composePrompt(): string {
    return (
      `Estoy en la consulta con el pediatra de mi bebé (con reflujo). El médico acaba de decir: ` +
      `"${input.trim()}".\n\n` +
      `Basándote en la historia clínica de mi bebé y en la evidencia clínica pediátrica, dame AHORA: ` +
      `1) PREGUNTAS con argumento que debería hacerle al médico para entender y cuestionar con fundamento ` +
      `(no quiero solo asentir), 2) SEÑALES de seguridad o banderas que debería verificar. ` +
      `Sé concreto, prudente y cita la evidencia. Dame argumentos, no un "sí doctor".`
    );
  }

  async function generate() {
    if (!input.trim() || busy) return;
    if (listening) recRef.current?.stop();
    setBusy(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    scrolledRef.current = false;
    try {
      for await (const ev of streamChat(composePrompt(), null, locale)) {
        if (ev.type === "token") {
          setAnswer((prev) => prev + ev.content);
          if (!scrolledRef.current) {
            scrolledRef.current = true;
            requestAnimationFrame(() =>
              outputRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
            );
          }
        } else if (ev.type === "final") setCitations(ev.citations ?? []);
        else if (ev.type === "error") setError(ev.content);
      }
    } catch {
      setError(t("error"));
    } finally {
      setBusy(false);
    }
  }

  const micLabel = listening
    ? t("listeningTap")
    : t("listenIn", { lang: MIC_LABEL[locale] ?? MIC_LABEL.es });

  // One job first: what the doctor just said, with the mic inside the field
  // at the thumb, as on the home. Recording the whole visit is the other way
  // in and used to sit above the field as a card with its own amber button,
  // so two tools competed for the first look (redesign audit, screen 15).
  // It now closes the page as a quiet row.
  return (
    <main className="mx-auto max-w-2xl px-5 py-8 sm:px-6 sm:py-10">
      <h1 className="text-title text-ink">{t("title")}</h1>
      <p className="mt-2 text-ink-soft">{t("subtitle")}</p>

      <div className="mt-6">
        <label htmlFor={fieldId} className="block text-lg font-semibold text-ink">
          {t("emptyPrompt")}
        </label>
        <div className="relative mt-3">
          <textarea
            id={fieldId}
            rows={4}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("placeholder")}
            disabled={busy}
            className={`block min-h-[120px] w-full resize-none rounded-2xl border border-line-control bg-surface px-4 py-3 text-base leading-relaxed text-ink placeholder:text-ink-faint focus:border-primary-text disabled:opacity-60 ${
              micSupported ? "pr-16" : ""
            }`}
          />
          {micSupported && (
            <button
              type="button"
              onClick={toggleMic}
              aria-pressed={listening}
              aria-label={micLabel}
              title={micLabel}
              className={`absolute bottom-1.5 right-1.5 inline-flex h-11 w-11 items-center justify-center rounded-full transition-colors ${
                listening
                  ? "bg-primary text-on-primary motion-safe:animate-pulse"
                  : "bg-primary-tint text-on-primary-tint hover:bg-surface-2"
              }`}
            >
              {listening ? <MicOff className="h-5 w-5" aria-hidden /> : <Mic className="h-5 w-5" aria-hidden />}
            </button>
          )}
        </div>
        {listening && (
          <p role="status" className="mt-2 text-sm text-ink-soft">
            {t("listeningTap")}
          </p>
        )}
        <button
          type="button"
          onClick={generate}
          disabled={!input.trim() || busy}
          className="ad-btn ad-btn-primary ad-btn-lg mt-4 w-full disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-5 w-5 animate-spin" strokeWidth={2.2} aria-hidden />
          ) : (
            <Sparkles className="h-5 w-5" strokeWidth={2.2} aria-hidden />
          )}
          {t("generate")}
        </button>
      </div>

      {/* Output */}
      {(busy || answer) && (
        <div ref={outputRef} className="ad-rise mt-8 scroll-mt-20 border-t border-line pt-6">
          {busy && !answer && (
            <div className="flex items-center gap-3 py-2">
              <Loader2 className="h-6 w-6 shrink-0 animate-spin text-primary-text" strokeWidth={2} />
              <div>
                <p className="text-base font-medium text-ink">{t("generating")}</p>
                <p className="mt-0.5 text-sm text-ink-soft">{t("generatingHint")}</p>
              </div>
            </div>
          )}
          {answer && <AnswerContent level={2}>{answer}</AnswerContent>}
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
          {!busy && answer && (
            <div className="mt-4 border-t border-line pt-3">
              <p className="flex items-start gap-1.5 text-sm text-ink-soft">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary-text" strokeWidth={2} aria-hidden />
                {t("disclaimer")}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={copyOutput}
                  className="ad-btn ad-btn-ghost min-h-11 px-3.5 text-sm"
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-primary-text" strokeWidth={2.4} aria-hidden />
                  ) : (
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden />
                  )}
                  {copied ? t("copied") : t("copy")}
                </button>
                <button
                  type="button"
                  onClick={generate}
                  className="ad-btn ad-btn-ghost min-h-11 px-3.5 text-sm"
                >
                  <RotateCcw className="h-4 w-4" strokeWidth={2} aria-hidden />
                  {t("regenerate")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
          {t("error")}
        </div>
      )}

      <Link
        href="/dashboard/consulta/grabar"
        className="mt-8 flex min-h-[52px] items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:bg-surface-2"
      >
        <Mic className="h-5 w-5 shrink-0 text-accent-text" strokeWidth={2} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-ink">{t("record.entryTitle")}</span>
          <span className="block text-sm text-ink-soft">{t("record.entryBody")}</span>
        </span>
        <ChevronRight className="h-5 w-5 shrink-0 text-ink-faint" aria-hidden />
      </Link>
    </main>
  );
}
