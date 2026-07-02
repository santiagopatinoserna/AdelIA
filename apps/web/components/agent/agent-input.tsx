"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Mic, Send, Square } from "lucide-react";

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

export function AgentInput({ onSubmit, onStop, disabled, locale }: {
  onSubmit: (text: string) => void; onStop: () => void; disabled: boolean; locale: string;
}) {
  const t = useTranslations("agent");
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const [micSupported, setMicSupported] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const baseRef = useRef("");

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

  function submit() { const text = input.trim(); if (!text) return; onSubmit(text); setInput(""); }

  return (
    <div className="flex items-end gap-2 border-t border-line bg-surface p-3">
      <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1}
        placeholder={t("placeholder")} aria-label={t("placeholder")}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        className="ad-card max-h-32 min-h-[44px] flex-1 resize-none px-3 py-2" />
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
        <button type="button" onClick={submit} disabled={!input.trim()} aria-label={t("send")}
          className="ad-btn ad-btn-primary min-h-[44px] w-11 justify-center">
          <Send className="h-5 w-5" />
        </button>
      )}
    </div>
  );
}
