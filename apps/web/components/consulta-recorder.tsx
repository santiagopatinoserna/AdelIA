"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Loader2, Mic, Square, XCircle } from "lucide-react";

import { Link } from "@/lib/navigation";
import { useActiveProfile } from "@/lib/profile-context";

export const CONSENT_POLICY_VERSION = "2026-08-17";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

type Phase = "gate" | "recording" | "uploading" | "transcribing" | "done" | "declined" | "error";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
}

// Grabar consulta: a parent records the whole pediatric visit so AdelIA can
// transcribe it into the child's health record verbatim — no more relying on
// memory of what the doctor said. Gated behind an explicit informed-consent
// checkbox (the professional must be told, per the legal note); a kill switch
// discards audio client-side and never uploads it.
export function ConsultaRecorder() {
  const t = useTranslations("consulta.record");
  const locale = useLocale();
  const { profiles, activeId, setActiveId } = useActiveProfile();

  const [phase, setPhase] = useState<Phase>("gate");
  const [informed, setInformed] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [docId, setDocId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const wakeLockRef = useRef<{ release(): Promise<void> } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const discardRef = useRef(false);
  // Synchronous in-flight guard: getUserMedia can hang on a permission
  // prompt, and state (`starting`) only updates on the next render — a
  // second tap before that render would otherwise orphan the first
  // stream/AudioContext/timer with the mic left open.
  const startingRef = useRef(false);
  const [starting, setStarting] = useState(false);

  // Screen wake lock: iOS suspends MediaRecorder when the screen locks.
  async function acquireWakeLock() {
    try {
      const wl = await (navigator as unknown as {
        wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> };
      }).wakeLock?.request("screen");
      if (wl) wakeLockRef.current = wl;
    } catch {
      /* unsupported — the on-screen hint still tells the mom */
    }
  }

  function cleanup() {
    timerRef.current && clearInterval(timerRef.current);
    timerRef.current = null;
    pollRef.current && clearInterval(pollRef.current);
    pollRef.current = null;
    streamRef.current?.getTracks().forEach((tr) => tr.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    wakeLockRef.current?.release().catch(() => {});
    wakeLockRef.current = null;
  }

  useEffect(
    () => () => {
      // An unmount must discard only when it's what forces the stop —
      // i.e. the recorder is still actively "recording". A deliberate
      // Stop tap flips MediaRecorder to "inactive" synchronously (its
      // `onstop` still fires async) — if the user then navigates away
      // before `onstop` runs, discardRef must stay false so that
      // already-in-flight upload isn't silently dropped. Without this
      // guard for the active-recording case, a browser-fired `onstop`
      // (e.g. tracks ending) after the component is gone would see
      // discardRef still false and POST partial audio from nowhere.
      if (recorderRef.current?.state === "recording") {
        discardRef.current = true;
      }
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      cleanup();
    },
    [],
  );

  // The wake lock is auto-released by the browser whenever the tab loses
  // visibility (app switch, phone display timeout while still recording) —
  // reacquire it once the tab is visible again so a distracted parent
  // switching apps mid-consult doesn't silently stop capturing on iOS.
  useEffect(() => {
    if (phase !== "recording") return;
    function onVisibility() {
      if (document.visibilityState === "visible") void acquireWakeLock();
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [phase]);

  async function start() {
    if (startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError(t("micDenied"));
      startingRef.current = false;
      setStarting(false);
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    discardRef.current = false;

    // Everything below can throw mid-setup (unsupported MediaRecorder
    // options, AudioContext construction failing, etc.) — without this
    // guard a throw here would leave startingRef/starting stuck true
    // forever: the button would stay disabled with a spinner and the
    // user could never retry.
    try {
      const mime = pickMime();
      const rec = new MediaRecorder(stream, {
        ...(mime ? { mimeType: mime } : {}),
        audioBitsPerSecond: 32_000,
      });
      recorderRef.current = rec;
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        cleanup();
        if (discardRef.current) {
          chunksRef.current = [];
          return;
        }
        void upload();
      };
      rec.start(10_000); // 10s timeslice: partial data survives a crash

      await acquireWakeLock();
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);

      // Live input level so the mom sees it's actually capturing.
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!audioCtxRef.current) return;
        analyser.getByteFrequencyData(buf);
        setLevel(Math.min(100, Math.round((buf.reduce((a, b) => a + b, 0) / buf.length / 255) * 300)));
        requestAnimationFrame(tick);
      };
      tick();

      startingRef.current = false;
      setStarting(false);
      setPhase("recording");
    } catch {
      // Discard whatever got created (e.g. a MediaRecorder that already
      // started) and tear down tracks/timers/context so nothing keeps
      // running behind the gate screen.
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        discardRef.current = true;
        recorderRef.current.stop();
      }
      cleanup();
      setError(t("error"));
      startingRef.current = false;
      setStarting(false);
      setPhase("gate");
    }
  }

  function stop() {
    recorderRef.current?.stop();
    setPhase("uploading");
  }

  function decline() {
    discardRef.current = true;
    recorderRef.current?.stop();
    setPhase("declined");
    void fetch("/api/backend/consent-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "recording_declined",
        profile_id: activeId,
        policy_version: CONSENT_POLICY_VERSION,
        locale,
      }),
    }).catch(() => {});
  }

  async function upload() {
    const mime = recorderRef.current?.mimeType || "audio/webm";
    const bare = mime.split(";")[0];
    const ext = bare === "audio/mp4" ? "m4a" : bare.split("/")[1];
    const blob = new Blob(chunksRef.current, { type: mime });
    const fd = new FormData();
    fd.append("file", blob, `consulta-${new Date().toISOString().slice(0, 10)}.${ext}`);
    if (activeId) fd.append("profile_id", activeId);
    fd.append("source", "consulta");
    fd.append("consent_policy_version", CONSENT_POLICY_VERSION);
    fd.append("locale", locale);
    try {
      const res = await fetch("/api/backend/documents", { method: "POST", body: fd });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const doc = (await res.json()) as { id: string };
      setDocId(doc.id);
      setPhase("transcribing");
      poll(doc.id);
    } catch {
      setError(t("error"));
      setPhase("error");
    }
  }

  function poll(id: string) {
    if (pollRef.current) clearInterval(pollRef.current); // guard: never stack two pollers
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/backend/documents/${id}`);
        if (!res.ok) return;
        const doc = (await res.json()) as { status: string };
        if (doc.status === "ready") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setPhase("done");
        } else if (doc.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setError(t("error"));
          setPhase("error");
        }
      } catch {
        /* transient — keep polling */
      }
    }, 3000);
  }

  const legalNote =
    locale === "es" ? t("legalNoteEs") : locale === "fr" ? t("legalNoteFr") : t("legalNoteGeneric");
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  if (phase === "gate") {
    return (
      <div className="ad-card space-y-4 p-6">
        <h1 className="text-xl font-semibold text-pine-900">{t("title")}</h1>
        {profiles.length > 1 && (
          <label className="block space-y-1">
            <span className="text-sm font-medium">{t("profileLabel")}</span>
            <select
              className="w-full rounded-lg border border-line-strong bg-surface p-2"
              value={activeId ?? ""}
              onChange={(e) => setActiveId(e.target.value)}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.display_name}</option>
              ))}
            </select>
          </label>
        )}
        <div>
          <p className="text-sm font-medium">{t("scriptLabel")}</p>
          <p className="mt-1 text-lg">{t("scriptText")}</p>
        </div>
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={informed}
            onChange={(e) => setInformed(e.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span>{t("checkboxLabel")}</span>
        </label>
        <Link href="/profesionales" target="_blank" className="block text-sm underline">
          {t("showInfo")}
        </Link>
        <p className="text-xs opacity-70">{legalNote}</p>
        {error && (
          <p role="alert" className="flex items-center gap-2 text-sm text-clay-600">
            <AlertCircle className="h-4 w-4" /> {error}
          </p>
        )}
        <button
          type="button"
          className="ad-btn ad-btn-primary min-h-[48px] w-full"
          disabled={!informed || starting}
          onClick={start}
        >
          {starting ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Mic className="h-5 w-5" />
          )}
          {t("start")}
        </button>
        {!informed && <p className="text-center text-xs opacity-70">{t("startDisabledHint")}</p>}
      </div>
    );
  }

  if (phase === "recording") {
    return (
      <div className="ad-card space-y-4 p-6">
        <div
          role="status"
          className="flex items-center justify-between rounded-lg bg-clay-600 px-4 py-3 text-white"
        >
          <span className="flex items-center gap-2 font-semibold">
            <span className="h-3 w-3 animate-pulse rounded-full bg-white" />
            {t("recording")} {mm}:{ss}
          </span>
          <span className="h-2 w-24 overflow-hidden rounded bg-clay-700">
            <span className="block h-full bg-white transition-all" style={{ width: `${level}%` }} />
          </span>
        </div>
        {elapsed < 15 && <p className="text-sm">{t("askNow")}</p>}
        <p className="text-xs opacity-70">{t("keepScreenOn")}</p>
        <button type="button" className="ad-btn ad-btn-primary min-h-[48px] w-full" onClick={stop}>
          <Square className="h-5 w-5" /> {t("stop")}
        </button>
        <button type="button" className="ad-btn ad-btn-danger min-h-[48px] w-full" onClick={decline}>
          <XCircle className="h-5 w-5" /> {t("decline")}
        </button>
      </div>
    );
  }

  if (phase === "declined") {
    return (
      <div className="ad-card space-y-3 p-6 text-center">
        <p className="font-medium">{t("declineDone")}</p>
        <Link href="/dashboard/consulta" className="ad-btn ad-btn-ghost">
          {t("declineFallback")}
        </Link>
      </div>
    );
  }

  if (phase === "uploading" || phase === "transcribing") {
    return (
      <div className="ad-card space-y-3 p-6 text-center" role="status">
        <Loader2 className="mx-auto h-8 w-8 animate-spin text-pine-500" />
        <p>{phase === "uploading" ? t("uploading") : t("transcribing")}</p>
        <p className="text-xs opacity-70">{t("audioDeleted")}</p>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="ad-card space-y-3 p-6 text-center">
        <CheckCircle2 className="mx-auto h-8 w-8 text-pine-600" />
        <p className="font-medium">{t("done")}</p>
        <p className="text-sm opacity-80">{t("audioDeleted")}</p>
        {docId && (
          <Link href={`/dashboard/documents/${docId}`} className="ad-btn ad-btn-primary">
            {t("viewDocument")}
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className="ad-card space-y-3 p-6 text-center">
      <p role="alert" className="text-clay-600">{error}</p>
      <button type="button" className="ad-btn ad-btn-ghost" onClick={() => setPhase("gate")}>
        {t("retry")}
      </button>
    </div>
  );
}
