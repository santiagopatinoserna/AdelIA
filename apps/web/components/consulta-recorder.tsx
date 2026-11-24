"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Mic,
  Square,
  UploadCloud,
  XCircle,
} from "lucide-react";

import { track } from "@/lib/analytics";
import {
  draftAppend,
  draftClear,
  draftLoad,
  draftStart,
  type DraftMeta,
} from "@/lib/consulta-draft";
import { Link } from "@/lib/navigation";
import { useActiveProfile } from "@/lib/profile-context";
import { useRecordingGuard } from "@/lib/recording-guard";
import { useFocusTrap } from "@/lib/use-focus-trap";

export const CONSENT_POLICY_VERSION = "2026-08-17";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

type Phase =
  | "gate"
  | "recording"
  | "uploading"
  | "transcribing"
  | "done"
  | "declined"
  | "error"
  | "upload-error";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
}

// A destructive tap in two: the first arms it (the label asks for the
// second), the second within 4 s acts. Left alone it disarms itself.
function useTwoTap(): [boolean, (armed: boolean) => void] {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const id = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(id);
  }, [armed]);
  return [armed, setArmed];
}

// MediaRecorder timeslice of the consult (see rec.start below). At 32 kbps a
// second is about 4 KB, one small write to the device draft.
const CHUNK_MS = 1_000;

// How long "Grabar" waits for the device check below before it gives up on
// it. Some WebKit builds never answer indexedDB.open on a cold start; a
// backup that cannot be read must not keep the mic shut.
const DRAFT_CHECK_FALLBACK_MS = 3000;

// Grabar consulta: a parent records the whole pediatric visit so AdelIA can
// transcribe it into the child's health record verbatim — no more relying on
// memory of what the doctor said. Gated behind an explicit informed-consent
// checkbox (the professional must be told, per the legal note); a kill switch
// discards audio client-side and never uploads it.
export function ConsultaRecorder() {
  const t = useTranslations("consulta.record");
  const tDash = useTranslations("dashboard");
  const locale = useLocale();
  const { profiles, activeId, setActiveId } = useActiveProfile();

  const [phase, setPhase] = useState<Phase>("gate");
  const [informed, setInformed] = useState(false);
  // The consent box is server-rendered and a native checkbox ticks before
  // React hydrates. That tick never reached `informed`: the box showed
  // ticked while "Grabar" stayed disabled under it (QA 2026-11-12, 10/10 on
  // a full load, which is how the "Grabar consulta" shortcut opens). Reading
  // the box once on mount keeps her tick; the explicit act is still hers.
  const informedRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (informedRef.current?.checked) setInformed(true);
  }, []);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [docId, setDocId] = useState<string | null>(null);
  const [doneSummary, setDoneSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // Retained across an upload failure so "Reintentar" can re-POST the exact
  // same bytes instead of forcing a re-record of an unrepeatable consult.
  const uploadBlobRef = useRef<Blob | null>(null);
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
  // The visit kept on the device while it is recorded (lib/consulta-draft),
  // so a reload or a killed tab no longer loses it. Every draft write goes
  // through one chain: a chunk can never land after the clear that follows
  // the upload. `dropDraftRef` is set by the kill switch: the professional
  // objected, so not one chunk may stay on the device.
  const draftChain = useRef<Promise<void>>(Promise.resolve());
  const dropDraftRef = useRef(false);
  const startedRef = useRef(false);
  // Whose visit the upload is, the consent wording she accepted and the day
  // it was recorded: the ones of this recording when Grabar was tapped, or
  // the ones an interrupted recording was made with.
  const uploadProfileRef = useRef<string | null>(null);
  const uploadPolicyRef = useRef(CONSENT_POLICY_VERSION);
  const uploadStartedAtRef = useRef(Date.now());
  // Whether the upload is a recording a reload, a closed tab or the browser
  // cut short. The server then summarises it without its last, maybe
  // half-said sentence and says it was cut: one cut inside "treinta y ocho"
  // was saved as "sube de 30" with no mark (third QA wave 2026-11-13). Kept
  // for "Reintentar" too.
  const uploadInterruptedRef = useRef(false);
  // Whether the stop was hers ("Terminar y guardar"). The browser can stop the
  // recorder itself (a call takes the mic, the track ends, an iOS interruption),
  // and that recording ends wherever it was cut, like a reload: without the flag
  // its summary could state a half-said last sentence as fact (third QA wave
  // 2026-11-13, review of the summary package).
  const stoppedByUserRef = useRef(false);
  const [interrupted, setInterrupted] = useState<{ blob: Blob; meta: DraftMeta } | null>(null);
  // "Grabar" stays disabled until the device has been checked for an
  // interrupted visit. A tap before the check queued draftStart, whose
  // clear() erased that visit before it was ever offered, and the case is
  // exactly the one the draft exists for: the tab was killed mid-visit and
  // she reopens the recorder to go on. The check takes milliseconds.
  const [draftChecked, setDraftChecked] = useState(false);
  function draft(op: () => Promise<void>) {
    draftChain.current = draftChain.current.then(op, op);
  }
  useEffect(() => {
    let alive = true;
    const fallback = setTimeout(() => setDraftChecked(true), DRAFT_CHECK_FALLBACK_MS);
    draft(async () => {
      try {
        const found = await draftLoad();
        // Only her own child's recording, and only if she has not started a
        // new one in the meantime (possible only after the fallback).
        if (!alive || !found || startedRef.current) return;
        if (!profiles.some((p) => p.id === found.meta.profileId)) return;
        setInterrupted(found);
      } finally {
        clearTimeout(fallback);
        if (alive) setDraftChecked(true);
      }
    });
    return () => {
      alive = false;
      clearTimeout(fallback);
    };
    // Read once, on mount: `profiles` comes from the server with the page.
  }, []);
  // Kill switch in two taps, and the same for dropping an interrupted visit:
  // both erase a recording that cannot be made again.
  const [declineArmed, setDeclineArmed] = useTwoTap();
  const [discardArmed, setDiscardArmed] = useTwoTap();

  // Navigation lock (lib/recording-guard): while recording, uploading, or
  // after a FAILED upload (the audio is then in uploadBlobRef, and in the
  // device draft only as a backup), any tab, link, language switch or Back
  // press lands here as `pending` and is answered with the dialog below
  // instead of dropping the audio.
  const { setActive: setGuardActive, pending: leaveRequest, clearPending } = useRecordingGuard();
  const guarded = phase === "recording" || phase === "uploading" || phase === "upload-error";
  useEffect(() => {
    setGuardActive(guarded);
    return () => setGuardActive(false);
  }, [guarded, setGuardActive]);
  const leaveDialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(leaveDialogRef, leaveRequest !== null && guarded);
  useEffect(() => {
    if (leaveRequest === null || !guarded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearPending();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [leaveRequest, guarded, clearPending]);

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
  //
  // And the moment the page may die (hidden, reload, closed tab), the audio
  // since the last chunk is asked for, so it reaches the device draft too.
  // With only complete 10 s chunks kept, a reload at 15 s lost the doctor's
  // answer and one at 6 s lost the whole visit (verification QA 2026-11-13).
  useEffect(() => {
    if (phase !== "recording") return;
    function flush() {
      const rec = recorderRef.current;
      if (rec?.state !== "recording") return;
      try {
        rec.requestData(); // the chunk lands in ondataavailable, then the draft
      } catch {
        /* stopped between the check and the call: its onstop has the audio */
      }
    }
    function onVisibility() {
      if (document.visibilityState === "visible") void acquireWakeLock();
      else flush();
    }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", flush);
    window.addEventListener("beforeunload", flush);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", flush);
      window.removeEventListener("beforeunload", flush);
    };
  }, [phase]);

  async function start() {
    if (startingRef.current) return;
    startingRef.current = true;
    startedRef.current = true;
    setInterrupted(null);
    setStarting(true);
    setError(null);
    // No recording API at all: an in-app browser (WhatsApp, Instagram) or a
    // page not served over https. Telling her to close other apps would send
    // her looking for a problem she does not have.
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError(t("micUnsupported"));
      startingRef.current = false;
      setStarting(false);
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      // Only a refusal is a permission problem. A mic held by a call or by
      // another app (NotReadableError), no mic (NotFoundError) or an aborted
      // start used to say "no tiene permiso", which sent her to a setting
      // that was already right (QA 2026-11-12). PermissionDeniedError is the
      // old name some engines still throw for the same refusal.
      const name = (e as { name?: string } | null)?.name;
      const refused =
        name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError";
      setError(refused ? t("micDenied") : t("micBusy"));
      startingRef.current = false;
      setStarting(false);
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    discardRef.current = false;
    dropDraftRef.current = false;
    uploadProfileRef.current = activeId;
    uploadPolicyRef.current = CONSENT_POLICY_VERSION;
    uploadStartedAtRef.current = Date.now();
    uploadInterruptedRef.current = false;
    stoppedByUserRef.current = false;
    setDeclineArmed(false);

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
      draft(() =>
        draftStart({
          mime: rec.mimeType || mime,
          profileId: activeId,
          startedAt: uploadStartedAtRef.current,
          policyVersion: CONSENT_POLICY_VERSION,
        }),
      );
      let seq = 0;
      rec.ondataavailable = (e) => {
        if (e.data.size === 0) return;
        chunksRef.current.push(e.data);
        if (dropDraftRef.current) return;
        const n = seq++;
        const data = e.data;
        draft(() => draftAppend(n, data));
      };
      rec.onstop = () => {
        cleanup();
        // After the last chunk: the kill switch's clear also covers the
        // chunk the stop itself delivered.
        if (dropDraftRef.current) draft(draftClear);
        if (discardRef.current) {
          chunksRef.current = [];
          return;
        }
        // Not her tap: the browser ended it, so the visit may have been cut mid-sentence.
        uploadInterruptedRef.current = uploadInterruptedRef.current || !stoppedByUserRef.current;
        void upload();
      };
      // A chunk every second, each also written to the device draft: a
      // crash or a killed tab that gives no warning loses about a second, not
      // the last 10 s. The chunks still join into one valid file (the first
      // carries the header), on the device and in the upload alike.
      rec.start(CHUNK_MS);

      await acquireWakeLock();
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);

      // Live input level so the mom sees it's actually capturing.
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      void ctx.resume(); // iOS Safari can start a fresh AudioContext suspended
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
      // Funnel step (no-op without consent): that a recording began, nothing of it.
      track("recording_started");
    } catch {
      // Discard whatever got created (e.g. a MediaRecorder that already
      // started) and tear down tracks/timers/context so nothing keeps
      // running behind the gate screen.
      dropDraftRef.current = true;
      draft(draftClear);
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        discardRef.current = true;
        recorderRef.current.stop();
      }
      recorderRef.current = null;
      cleanup();
      setError(t("error"));
      startingRef.current = false;
      setStarting(false);
      setPhase("gate");
    }
  }

  function stop() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") track("recording_finished");
    // Only a recorder still recording is hers to stop: if the browser already
    // stopped it and its onstop has not run yet, her tap must not mark the cut
    // as her own (review of the third fix round).
    if (recorderRef.current?.state === "recording") stoppedByUserRef.current = true;
    recorderRef.current?.stop();
    setPhase("uploading");
  }

  function decline() {
    discardRef.current = true;
    // The professional objected: nothing of it stays on the device either.
    dropDraftRef.current = true;
    draft(draftClear);
    recorderRef.current?.stop();
    setPhase("declined");
    // The declined event is the RGPD accountability trail for "the doctor
    // said no" — worth more than one shot. Non-blocking retries with
    // backoff; the kill switch itself never waits on the network.
    const send = () =>
      fetch("/api/backend/consent-events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: "recording_declined",
          profile_id: activeId,
          policy_version: CONSENT_POLICY_VERSION,
          locale,
        }),
      });
    void send().catch(() =>
      new Promise((r) => setTimeout(r, 2000)).then(() =>
        send().catch(() => new Promise((r) => setTimeout(r, 8000)).then(() => send().catch(() => {}))),
      ),
    );
  }

  async function upload(retryBlob?: Blob) {
    // First attempt builds the Blob from the just-recorded chunks; a retry
    // after an upload failure reuses the exact same Blob via uploadBlobRef
    // instead of re-recording (the consult itself is unrepeatable).
    const blob = retryBlob ?? new Blob(chunksRef.current, { type: recorderRef.current?.mimeType || "audio/webm" });
    uploadBlobRef.current = blob;
    const bare = (blob.type || "audio/webm").split(";")[0];
    const ext = bare === "audio/mp4" ? "m4a" : bare.split("/")[1] || "webm";
    const fd = new FormData();
    const day = new Date(uploadStartedAtRef.current).toISOString().slice(0, 10);
    fd.append("file", blob, `consulta-${day}.${ext}`);
    if (uploadProfileRef.current) fd.append("profile_id", uploadProfileRef.current);
    fd.append("source", "consulta");
    fd.append("consent_policy_version", uploadPolicyRef.current);
    fd.append("locale", locale);
    if (uploadInterruptedRef.current) fd.append("interrupted", "true");
    setPhase("uploading");
    try {
      const res = await fetch("/api/backend/documents", { method: "POST", body: fd });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const doc = (await res.json()) as { id: string };
      uploadBlobRef.current = null;
      // The server has it now: the device copy goes.
      draft(draftClear);
      setDocId(doc.id);
      setPhase("transcribing");
      poll(doc.id);
    } catch {
      // Distinct from transcription/start failures: the blob is retained
      // (uploadBlobRef) so "Reintentar" here re-POSTs it directly.
      setError(t("uploadError"));
      setPhase("upload-error");
    }
  }

  function retryUpload() {
    if (uploadBlobRef.current) void upload(uploadBlobRef.current);
  }

  // Deliberate way out after a failed upload (chosen in the leave dialog,
  // so it is always a second tap): drop the audio and lift the lock. The
  // recorder returns to the gate and the next tap navigates freely.
  function discardUnsaved() {
    clearPending();
    uploadBlobRef.current = null;
    chunksRef.current = [];
    draft(draftClear);
    setError(null);
    setPhase("gate");
  }

  // The recording a reload or a killed tab interrupted: upload what the
  // device kept, for the child it was recorded for, or drop it.
  //
  // That child also becomes the active one. After a reload the active child
  // is the default one, and the done screen's "Preguntar sobre esta consulta"
  // and "Preparar resumen" read the active child: for a sibling's visit they
  // asked the other child's record what the pediatrician said. The id was
  // checked against `profiles` when the draft was read.
  function uploadInterrupted() {
    if (!interrupted) return;
    const { meta, blob } = interrupted;
    if (meta.profileId) setActiveId(meta.profileId);
    uploadProfileRef.current = meta.profileId;
    uploadPolicyRef.current = meta.policyVersion ?? CONSENT_POLICY_VERSION;
    uploadStartedAtRef.current = meta.startedAt;
    uploadInterruptedRef.current = true;
    setInterrupted(null);
    void upload(blob);
  }

  function discardInterrupted() {
    setDiscardArmed(false);
    setInterrupted(null);
    draft(draftClear);
  }

  function poll(id: string) {
    if (pollRef.current) clearInterval(pollRef.current); // guard: never stack two pollers
    // Cap: a stuck pipeline must not spin "Transcribiendo…" forever. The
    // upload DID land, so the honest copy on timeout is t("error") — the
    // audio really is kept server-side for a retry window.
    let polls = 0;
    const MAX_POLLS = 100; // ~5 min at 3s
    pollRef.current = setInterval(async () => {
      if (++polls > MAX_POLLS) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setError(t("error"));
        setPhase("error");
        return;
      }
      try {
        const res = await fetch(`/api/backend/documents/${id}`);
        if (!res.ok) return;
        const doc = (await res.json()) as { status: string; summary?: string | null };
        if (doc.status === "ready") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setDoneSummary(doc.summary ?? null);
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

  // "¿Terminar la grabación?": the answer to any attempt to leave while the
  // mic is open. "Seguir grabando" is the default (focused first) — the tap
  // was most likely accidental. "Terminar y guardar" is exactly the Stop
  // button: the audio recorded so far is uploaded, nothing is discarded.
  // While uploading there is nothing to decide: a short notice, then the
  // lock lifts by itself the moment the upload lands. After a FAILED upload
  // the audio is only in memory: "Reintentar" re-posts the same bytes,
  // "Quedarme aquí" keeps the lock, "Descartar" is the conscious way out.
  const leaveTitle =
    phase === "recording"
      ? t("leaveTitle")
      : phase === "upload-error"
        ? t("leaveUnsavedTitle")
        : t("uploadingNoticeTitle");
  const leaveBody =
    phase === "recording"
      ? t("leaveBody")
      : phase === "upload-error"
        ? t("leaveUnsavedBody")
        : t("uploadingNoticeBody");
  const leaveDialog =
    leaveRequest !== null && guarded ? (
      <div
        className="fixed inset-0 z-50 flex items-end justify-center bg-scrim p-4 backdrop-blur-sm sm:items-center"
        onClick={clearPending}
      >
        <div
          ref={leaveDialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="leave-recording-title"
          aria-describedby="leave-recording-body"
          onClick={(e) => e.stopPropagation()}
          className="ad-card ad-elevated w-full max-w-md space-y-4 p-6 shadow-glow"
        >
          <h2 id="leave-recording-title" className="text-lg text-ink">
            {leaveTitle}
          </h2>
          <p id="leave-recording-body" className="text-sm leading-relaxed text-ink-soft">
            {leaveBody}
          </p>
          {phase === "recording" ? (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="ad-btn ad-btn-primary min-h-[48px] w-full"
                onClick={clearPending}
              >
                <Mic className="h-5 w-5" /> {t("leaveStay")}
              </button>
              <button
                type="button"
                className="ad-btn ad-btn-ghost min-h-[48px] w-full"
                onClick={() => {
                  clearPending();
                  stop();
                }}
              >
                <Square className="h-5 w-5" /> {t("stop")}
              </button>
            </div>
          ) : phase === "upload-error" ? (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="ad-btn ad-btn-primary min-h-[48px] w-full"
                onClick={() => {
                  clearPending();
                  retryUpload();
                }}
              >
                {t("retry")}
              </button>
              <button
                type="button"
                className="ad-btn ad-btn-ghost min-h-[48px] w-full"
                onClick={clearPending}
              >
                {t("leaveUnsavedStay")}
              </button>
              <button
                type="button"
                className="mx-auto inline-flex min-h-[44px] items-center gap-1.5 px-2 text-sm text-error-text underline underline-offset-4"
                onClick={discardUnsaved}
              >
                <XCircle className="h-4 w-4" /> {t("leaveUnsavedDiscard")}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="ad-btn ad-btn-primary min-h-[48px] w-full"
              onClick={clearPending}
            >
              {t("uploadingNoticeOk")}
            </button>
          )}
        </div>
      </div>
    ) : null;

  // One decision before anything else: a new recording would replace the
  // interrupted one, and that visit cannot be recorded again.
  if (phase === "gate" && interrupted) {
    const when = new Date(interrupted.meta.startedAt).toLocaleString(locale, {
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit",
    });
    // Named, so a mother of two knows whose visit she is about to upload.
    const name = profiles.find((p) => p.id === interrupted.meta.profileId)?.display_name ?? "";
    return (
      <div className="ad-card space-y-4 p-6">
        <h1 className="text-title text-ink">{t("title")}</h1>
        <p className="text-ink">{t("interruptedBody", { name, when })}</p>
        <button
          type="button"
          className="ad-btn ad-btn-primary ad-btn-lg w-full"
          onClick={uploadInterrupted}
        >
          <UploadCloud className="h-5 w-5" /> {t("interruptedUpload")}
        </button>
        {/* Two taps, like the kill switch: it sits right under the primary
            button and erases a visit that cannot be recorded again. */}
        <p className="text-center">
          <button
            type="button"
            aria-live="polite"
            className={
              discardArmed
                ? "ad-btn ad-btn-danger min-h-[48px] px-5 text-sm"
                : "inline-flex min-h-[44px] items-center gap-1.5 px-2 text-sm text-error-text underline underline-offset-4"
            }
            onClick={() => (discardArmed ? discardInterrupted() : setDiscardArmed(true))}
          >
            <XCircle className="h-4 w-4" />{" "}
            {discardArmed ? t("interruptedDiscardConfirm") : t("interruptedDiscard")}
          </button>
        </p>
      </div>
    );
  }

  if (phase === "gate") {
    return (
      <div className="ad-card space-y-4 p-6">
        <h1 className="text-title text-ink">{t("title")}</h1>
        {profiles.length > 1 && (
          <label className="block space-y-1">
            <span className="text-sm font-medium">{t("profileLabel")}</span>
            <select
              className="w-full rounded-lg border border-line-control bg-surface p-2"
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
          <p className="text-sm font-medium text-ink-soft">{t("scriptLabel")}</p>
          <p className="mt-1 text-lead text-ink">{t("scriptText")}</p>
        </div>
        {/* The whole row is the target: one thumb, phone in the other hand
            while the doctor waits. */}
        <label className="flex min-h-[52px] cursor-pointer items-start gap-3 rounded-xl border border-line-control px-4 py-3">
          {/* autoComplete off: Firefox restores a ticked box on reload, and
              the mount read above would turn that restored tick into consent
              for a new recording with no act of hers this time. */}
          <input
            ref={informedRef}
            type="checkbox"
            autoComplete="off"
            checked={informed}
            onChange={(e) => setInformed(e.target.checked)}
            className="mt-0.5 h-6 w-6 shrink-0 accent-primary"
          />
          <span className="text-ink">{t("checkboxLabel")}</span>
        </label>
        <Link
          href="/profesionales"
          target="_blank"
          className="inline-flex min-h-11 items-center text-sm text-ink underline underline-offset-2"
        >
          {t("showInfo")}
        </Link>
        <p className="text-sm text-ink-soft">{legalNote}</p>
        {error && (
          <p role="alert" className="flex items-center gap-2 text-sm text-error-text">
            <AlertCircle className="h-4 w-4" /> {error}
          </p>
        )}
        <button
          type="button"
          className="ad-btn ad-btn-primary ad-btn-lg w-full"
          disabled={!informed || starting || !draftChecked}
          onClick={start}
        >
          {starting ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Mic className="h-5 w-5" />
          )}
          {t("start")}
        </button>
        {!informed && <p className="text-center text-sm text-ink-soft">{t("startDisabledHint")}</p>}
      </div>
    );
  }

  if (phase === "recording") {
    return (
      <>
      <div className="ad-card space-y-4 p-6">
        <div
          role="status"
          className="flex items-center justify-between rounded-lg bg-error px-4 py-3 text-on-error"
        >
          <span className="flex items-center gap-2 font-semibold">
            <span className="h-3 w-3 animate-pulse rounded-full bg-on-error" />
            {t("recording")} {mm}:{ss}
          </span>
          {/* The groove needs its own value: `bg-error` here is the banner's
              own colour, so the empty part of the meter was invisible and the
              parent could not see its extent. */}
          <span className="h-2 w-24 overflow-hidden rounded bg-on-error/30">
            <span className="block h-full bg-on-error transition-all" style={{ width: `${level}%` }} />
          </span>
        </div>
        {elapsed < 15 && <p className="text-sm">{t("askNow")}</p>}
        <p className="text-sm text-ink-soft">{t("keepScreenOn")}</p>
        <button type="button" className="ad-btn ad-btn-primary ad-btn-lg w-full" onClick={stop}>
          <Square className="h-5 w-5" /> {t("stop")}
        </button>
      </div>
      {/* Kill switch ("the professional objects"), deliberately NOT a button
          under Stop: a text link outside the card (card padding + 24px away)
          that takes two taps. The first arms it (the label asks for the
          second), the second within 4 s discards the audio and logs
          recording_declined; otherwise it disarms itself. One slipped finger
          while stopping used to erase the consult and record an objection
          that never happened. */}
      <p className="mt-6 text-center">
        <button
          type="button"
          aria-live="polite"
          className={
            declineArmed
              ? "ad-btn ad-btn-danger min-h-[48px] px-5 text-sm"
              : "inline-flex min-h-[44px] items-center gap-1.5 px-2 text-sm text-error-text underline underline-offset-4"
          }
          onClick={() => (declineArmed ? decline() : setDeclineArmed(true))}
        >
          <XCircle className="h-4 w-4" /> {declineArmed ? t("declineConfirm") : t("decline")}
        </button>
      </p>
      {leaveDialog}
      </>
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
      <>
      <div className="ad-card space-y-3 p-6 text-center" role="status">
        <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary-text" />
        <p>{phase === "uploading" ? t("uploading") : t("transcribing")}</p>
        <p className="text-xs opacity-70">{t("audioDeleted")}</p>
      </div>
      {leaveDialog}
      </>
    );
  }

  if (phase === "done") {
    return (
      <div className="ad-card space-y-3 p-6 text-center">
        <CheckCircle2 className="mx-auto h-8 w-8 text-primary-text" />
        <p className="font-medium">{t("done")}</p>
        <p className="text-sm opacity-80">{t("audioDeleted")}</p>
        {/* The essence, right here: the takeaway a mom wants the second the
            visit is saved, without a trip to the document page. */}
        {doneSummary && (
          <div className="rounded-2xl border border-primary-tint-line bg-primary-tint p-4 text-left">
            <h2 className="ad-eyebrow text-primary-text">{tDash("summaryTitle")}</h2>
            <ul className="mt-2 space-y-1.5">
              {doneSummary
                .split("\n")
                .map((line) => line.replace(/^-\s*/, "").trim())
                .filter(Boolean)
                .map((line, i) => (
                  <li key={i} className="flex gap-2 text-sm leading-relaxed text-ink">
                    <span
                      aria-hidden
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-text"
                    />
                    {line}
                  </li>
                ))}
            </ul>
          </div>
        )}
        <div className="flex flex-wrap justify-center gap-2">
          {docId && (
            <Link href={`/dashboard/documents/${docId}`} className="ad-btn ad-btn-primary">
              {t("viewDocument")}
            </Link>
          )}
          {/* Close the loop recording → next visit: the briefing machinery
              already picked up this consult's entities (stale-marking). */}
          <Link href="/dashboard/briefings/new" className="ad-btn ad-btn-ghost">
            {t("prepareBriefing")}
          </Link>
        </div>
      </div>
    );
  }

  if (phase === "upload-error") {
    return (
      <>
      <div className="ad-card space-y-3 p-6 text-center">
        <p role="alert" className="text-error-text">{error}</p>
        <button type="button" className="ad-btn ad-btn-ghost min-h-[44px]" onClick={retryUpload}>
          {t("retry")}
        </button>
      </div>
      {leaveDialog}
      </>
    );
  }

  return (
    <div className="ad-card space-y-3 p-6 text-center">
      <p role="alert" className="text-error-text">{error}</p>
      <button type="button" className="ad-btn ad-btn-ghost" onClick={() => setPhase("gate")}>
        {t("retry")}
      </button>
    </div>
  );
}
