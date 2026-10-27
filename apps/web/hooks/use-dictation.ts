"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Dictation for the public demo field through the browser's own Web Speech
// API. The demo has no account and the page promises that nothing is stored,
// so audio must never reach our server: the browser transcribes on its side
// (or on its vendor's side, under the browser's permission prompt) and the
// page only ever sees text. The account recorder (consulta-recorder.tsx)
// uploads to Voxtral; this hook deliberately does not.
//
// Feature-detected after mount, so the server renders the same markup for
// every browser and Firefox (no API) simply has no button.

type RecognitionResultList = ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;

type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: { resultIndex: number; results: RecognitionResultList }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
};

type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useDictation({ lang, onFinal }: {
  lang: string;
  onFinal: (text: string) => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [failed, setFailed] = useState(false);
  const active = useRef<Recognition | null>(null);
  const deliver = useRef(onFinal);

  useEffect(() => {
    deliver.current = onFinal;
  }, [onFinal]);

  useEffect(() => {
    setSupported(recognitionCtor() !== null);
    return () => active.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || active.current) return;
    const recognition = new Ctor();
    recognition.lang = lang;
    recognition.interimResults = true;
    // One utterance per tap: she speaks a question, not a monologue, and the
    // browser closes the microphone by itself when she pauses.
    recognition.continuous = false;
    recognition.onresult = (event) => {
      let text = "";
      let done = false;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        text += result[0].transcript;
        if (result.isFinal) done = true;
      }
      if (done) {
        setInterim("");
        if (text.trim()) deliver.current(text.trim());
      } else {
        setInterim(text);
      }
    };
    // "aborted" is her own stop; everything else (not-allowed, no-speech,
    // network, audio-capture) gets the same one line: the keyboard still works.
    recognition.onerror = (event) => {
      if (event.error !== "aborted") setFailed(true);
    };
    recognition.onend = () => {
      active.current = null;
      setListening(false);
      setInterim("");
    };
    active.current = recognition;
    setFailed(false);
    setInterim("");
    setListening(true);
    try {
      recognition.start();
    } catch {
      active.current = null;
      setListening(false);
      setFailed(true);
    }
  }, [lang]);

  const stop = useCallback(() => active.current?.stop(), []);
  const toggle = useCallback(() => (active.current ? stop() : start()), [start, stop]);
  const clearError = useCallback(() => setFailed(false), []);

  return { supported, listening, interim, failed, toggle, clearError };
}
