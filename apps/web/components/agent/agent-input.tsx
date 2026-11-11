"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Mic, Send, Square } from "lucide-react";
import { ClinicalDisclaimer } from "@/components/clinical-disclaimer";
import { useEarlyAsk } from "@/lib/early-ask";

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
  const w = window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}
const LANG: Record<string, string> = { es: "es-ES", en: "en-US", fr: "fr-FR" };

export function AgentInput({ onSubmit, onStop, disabled, locale, placeholder }: {
  onSubmit: (text: string) => void; onStop: () => void; disabled: boolean; locale: string;
  placeholder?: string;
}) {
  const t = useTranslations("agent");
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const [micSupported, setMicSupported] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const baseRef = useRef("");
  const fieldRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { setMicSupported(getSpeechCtor() !== null); return () => recRef.current?.stop(); }, []);

  function toggleMic() {
    if (listening) { recRef.current?.stop(); return; }
    const Ctor = getSpeechCtor(); if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = LANG[locale] ?? "es-ES"; rec.interimResults = true; rec.continuous = true;
    baseRef.current = input.trim() ? input + " " : "";
    rec.onresult = (e) => {
      let txt = ""; for (let i = 0; i < e.results.length; i++) txt += e.results[i][0].transcript;
      setInput(baseRef.current + txt);
    };
    rec.onend = () => setListening(false); rec.onerror = () => setListening(false);
    recRef.current = rec; setListening(true); rec.start();
  }

  function submit(value = input) {
    const text = value.trim(); if (!text) return; onSubmit(text); setInput("");
  }
  // What she wrote or sent before hydration (lib/early-ask.ts).
  useEarlyAsk("panel", fieldRef, setInput, submit);

  return (
    <div className="border-t border-line bg-surface p-3">
    {/* gap-1.5 and px-2.5, not 2 and 3: at 360 px «Demande-en plus à ce sujet»
        was cut by a few pixels (usability run, 2026-11-11). */}
    <div data-early-scope className="flex items-end gap-1.5">
      <textarea ref={fieldRef} data-early-ask="panel" suppressHydrationWarning
        value={input} onChange={(e) => setInput(e.target.value)} rows={1}
        placeholder={placeholder ?? t("placeholder")} aria-label={t("inputLabel")}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        className="ad-field max-h-32 min-h-[44px] flex-1 resize-none px-2.5 py-2" />
      {micSupported && (
        <button type="button" onClick={toggleMic} aria-pressed={listening} aria-label={t("listen")}
          className={`ad-btn min-h-[44px] w-11 justify-center ${listening ? "ad-btn-accent" : "ad-btn-ghost"}`}>
          <Mic className="h-5 w-5" />
        </button>
      )}
      {disabled ? (
        <button type="button" onClick={onStop} aria-label={t("stop")} className="ad-btn ad-btn-ghost min-h-[44px] w-11 justify-center">
          <Square className="h-5 w-5" />
        </button>
      ) : (
        <button type="button" onClick={() => submit()} disabled={!input.trim()} aria-label={t("send")}
          data-early-send suppressHydrationWarning
          className="ad-btn ad-btn-primary min-h-[44px] w-11 justify-center">
          <Send className="h-5 w-5" />
        </button>
      )}
    </div>
    {/* Same fixed disclaimer as the chat (audit 3.8): /dashboard is the screen
        a parent lands on, and it carried none before. */}
    <ClinicalDisclaimer className="mt-2" />
    </div>
  );
}
