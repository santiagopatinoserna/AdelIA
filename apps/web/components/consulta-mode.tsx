"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  Stethoscope,
  Mic,
  Sparkles,
  Loader2,
  RotateCcw,
  ShieldCheck,
  Copy,
  Check,
} from "lucide-react";

import { streamChat, type Citation } from "@/lib/chat-client-browser";
import { Markdown } from "./markdown";
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

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <div className="flex items-start gap-3">
        <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
          <Stethoscope className="h-6 w-6" strokeWidth={1.9} />
        </span>
        <div>
          <h1 className="text-2xl text-pine-900">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-soft">{t("subtitle")}</p>
        </div>
      </div>

      {/* Input */}
      <div className="ad-card mt-6 p-4">
        <label className="ad-eyebrow normal-case tracking-normal">{t("emptyPrompt")}</label>
        <textarea
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("placeholder")}
          aria-label={t("placeholder")}
          disabled={busy}
          className="mt-2 w-full resize-y rounded-xl border border-line-strong bg-surface px-3 py-2.5 text-base leading-relaxed text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-300 disabled:opacity-60"
        />
        {!input.trim() && !answer && (
          <p className="mt-2 rounded-lg bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-soft">
            {t("example")}
          </p>
        )}
        <div className="mt-3 flex items-center justify-between gap-2">
          {micSupported ? (
            <button
              type="button"
              onClick={toggleMic}
              aria-pressed={listening}
              aria-label={listening ? t("listeningTap") : t("listenIn", { lang: MIC_LABEL[locale] ?? MIC_LABEL.es })}
              className={`ad-btn min-h-[44px] px-3 py-2 text-sm ${
                listening
                  ? "bg-honey-100 text-honey-700 ring-1 ring-honey-200 hover:bg-honey-200"
                  : "ad-btn-ghost"
              }`}
            >
              <Mic className={`h-4 w-4 ${listening ? "animate-pulse" : ""}`} strokeWidth={2} />
              <span>
                {listening
                  ? t("listeningTap")
                  : t("listenIn", { lang: MIC_LABEL[locale] ?? MIC_LABEL.es })}
              </span>
            </button>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={generate}
            disabled={!input.trim() || busy}
            className="ad-btn ad-btn-primary px-5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
            ) : (
              <Sparkles className="h-4 w-4" strokeWidth={2.2} />
            )}
            {t("generate")}
          </button>
        </div>
      </div>

      {/* Output */}
      {(busy || answer) && (
        <div ref={outputRef} className="ad-card ad-rise mt-4 scroll-mt-28 p-5">
          {busy && !answer && (
            <div className="flex items-center gap-3 py-2">
              <Loader2 className="h-6 w-6 shrink-0 animate-spin text-pine-500" strokeWidth={2} />
              <div>
                <p className="text-base font-medium text-pine-900">{t("generating")}</p>
                <p className="mt-0.5 text-sm text-ink-soft">{t("generatingHint")}</p>
              </div>
            </div>
          )}
          {answer && (
            <div className="text-[15px] text-ink">
              <Markdown>{answer}</Markdown>
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
          {!busy && answer && (
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3">
              <p className="flex items-center gap-1.5 text-xs text-ink-faint">
                <ShieldCheck className="h-3.5 w-3.5 text-pine-400" strokeWidth={2} />
                {t("disclaimer")}
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
                  {t("regenerate")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {t("error")}
        </div>
      )}
    </main>
  );
}
