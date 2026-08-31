"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, RotateCcw, Trash2 } from "lucide-react";

import { Link, useRouter } from "@/lib/navigation";
import {
  deleteDocument,
  getDocument,
  setSpeakerNames,
  type DocumentDTO,
} from "@/lib/api-client-browser";
import { StatusBadge } from "@/components/status-badge";

const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 120; // ~5 min — then stop the spinner and offer a reload

// Consultation transcripts arrive as "[Hablante N] …" blocks (the backend's
// diarization format, a fixed literal regardless of UI locale). Parse them so
// the mom reads a conversation, not a wall of bracketed text.
type Turn = { speaker: number; text: string };

function parseDiarized(text: string): Turn[] | null {
  if (!text.trimStart().startsWith("[Hablante ")) return null;
  const turns: Turn[] = [];
  const re = /\[Hablante (\d+)\]\s*([\s\S]*?)(?=\s*\[Hablante \d+\]|$)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const body = m[2].trim();
    if (body) turns.push({ speaker: Number(m[1]), text: body });
  }
  return turns.length > 0 ? turns : null;
}

const SPEAKER_STYLES = [
  "bg-primary-tint text-primary-text ring-primary-tint-line",
  "bg-accent-tint text-accent-text ring-accent-tint-line",
];

export function DocumentDetailView({
  initialDoc,
  locale,
}: {
  initialDoc: DocumentDTO;
  locale: string;
}) {
  const [doc, setDoc] = useState<DocumentDTO>(initialDoc);
  const [timedOut, setTimedOut] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(false);
  const pollsRef = useRef(0);
  const router = useRouter();
  const t = useTranslations("dashboard");
  const tRecord = useTranslations("consulta.record");

  // Keyed by TURN index, not speaker number: clicking one chip must open
  // ONE panel, not a panel on every turn of that speaker.
  const [renamingTurn, setRenamingTurn] = useState<number | null>(null);
  const [customName, setCustomName] = useState("");

  async function nameSpeaker(speaker: number, name: string) {
    const trimmed = name.trim().slice(0, 40);
    if (!trimmed) return;
    setRenamingTurn(null);
    setCustomName("");
    const next = { ...(doc.speaker_names ?? {}), [String(speaker)]: trimmed };
    // Optimistic: the label flips at once; the PATCH persists it. On failure
    // we simply fall back to the server truth at the next poll/reload.
    setDoc((d) => ({ ...d, speaker_names: next }));
    try {
      const fresh = await setSpeakerNames(doc.id, next);
      setDoc(fresh);
    } catch {
      /* optimistic label stays for this view; server wins on reload */
    }
  }

  async function onDelete() {
    setDeleting(true);
    setDeleteError(false);
    try {
      await deleteDocument(doc.id);
      router.push("/dashboard/overview");
    } catch {
      setDeleteError(true);
      setDeleting(false);
      setConfirmingDelete(false);
    }
  }

  const processing = doc.status === "processing";

  useEffect(() => {
    if (!processing) return;
    pollsRef.current = 0;
    setTimedOut(false);
    const timer = setInterval(async () => {
      // Don't poll forever — a stuck OCR job should surface a recoverable state.
      if (pollsRef.current >= MAX_POLLS) {
        setTimedOut(true);
        clearInterval(timer);
        return;
      }
      pollsRef.current += 1;
      try {
        const fresh = await getDocument(doc.id);
        setDoc(fresh);
      } catch {
        // transient fetch error — keep last known state, retry next tick
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processing, doc.id]);

  const isConsulta = doc.source === "consulta";
  // "consulta-2026-08-20.webm" is a filename, not a title a mom should read.
  const longDate = (iso: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(iso));
  // Telegram diary entries are titled by the day they describe, not by
  // the "diario-2026-08-27.ogg" filename the bot generated.
  const title = isConsulta
    ? t("consultaDocTitle", { date: longDate(doc.created_at) })
    : doc.diary_date
      ? t("diaryDocTitle", { date: longDate(`${doc.diary_date}T12:00:00`) })
      : doc.file_name;
  const turns = isConsulta && doc.raw_text ? parseDiarized(doc.raw_text) : null;
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <Link
        href="/dashboard"
        className="mb-5 inline-flex items-center gap-1.5 text-sm text-ink-soft transition-colors hover:text-primary-text-hover"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={2} />
        {t("title")}
      </Link>
      <div className="flex items-start justify-between gap-3">
        <h1 className="min-w-0 truncate text-2xl text-ink">{title}</h1>
        <StatusBadge status={doc.status} />
      </div>
      {isConsulta && (
        <p className="mt-2 text-xs text-ink-faint">{tRecord("audioDeleted")}</p>
      )}
      <p className="mt-2 font-mono text-xs text-ink-faint">
        {new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(doc.created_at))}
        {doc.raw_text ? `  ·  ${t("docReady")}` : ""}
      </p>
      {/* Post-recording essence: the takeaway before the full conversation.
          Bullets come as "- " lines from the backend, rendered as a list. */}
      {isConsulta && doc.summary && (
        <section className="mt-8 rounded-2xl border border-primary-tint-line bg-primary-tint p-5">
          <h2 className="ad-eyebrow text-primary-text">{t("summaryTitle")}</h2>
          <ul className="mt-2 space-y-1.5">
            {doc.summary
              .split("\n")
              .map((line) => line.replace(/^-\s*/, "").trim())
              .filter(Boolean)
              .map((line, i) => (
                <li key={i} className="flex gap-2 text-sm leading-relaxed text-ink">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-text" />
                  {line}
                </li>
              ))}
          </ul>
        </section>
      )}

      <section className="ad-card mt-8 p-6">
        {turns ? (
          <div className="flex flex-col gap-4">
            {turns.map((turn, i) => {
              const label =
                doc.speaker_names?.[String(turn.speaker)] ??
                t("speakerLabel", { n: turn.speaker });
              return (
                <div key={i}>
                  <button
                    type="button"
                    onClick={() => setRenamingTurn(renamingTurn === i ? null : i)}
                    title={t("speakerRenameHint")}
                    className={`ad-eyebrow inline-block rounded-full px-2 py-0.5 ring-1 transition-shadow hover:ring-2 ${
                      SPEAKER_STYLES[(turn.speaker - 1) % SPEAKER_STYLES.length]
                    }`}
                  >
                    {label}
                  </button>
                  {renamingTurn === i && (
                    <span className="ml-2 inline-flex flex-wrap items-center gap-1.5 align-middle">
                      <button
                        type="button"
                        onClick={() => void nameSpeaker(turn.speaker, t("speakerSuggestDoctor"))}
                        className="ad-btn ad-btn-ghost px-2 py-1 text-xs"
                      >
                        {t("speakerSuggestDoctor")}
                      </button>
                      <button
                        type="button"
                        onClick={() => void nameSpeaker(turn.speaker, t("speakerSuggestMe"))}
                        className="ad-btn ad-btn-ghost px-2 py-1 text-xs"
                      >
                        {t("speakerSuggestMe")}
                      </button>
                      <input
                        type="text"
                        value={customName}
                        onChange={(e) => setCustomName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void nameSpeaker(turn.speaker, customName);
                        }}
                        placeholder={t("speakerCustomPlaceholder")}
                        maxLength={40}
                        className="h-7 w-28 rounded-lg border border-line bg-canvas px-2 text-xs"
                      />
                    </span>
                  )}
                  <p className="mt-1.5 text-sm leading-relaxed text-ink">{turn.text}</p>
                </div>
              );
            })}
          </div>
        ) : doc.raw_text ? (
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">{doc.raw_text}</pre>
        ) : timedOut ? (
          <div className="text-center">
            <p className="text-sm text-ink-soft">{t("ocrTimeout")}</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="ad-btn ad-btn-ghost mt-3 px-4 py-2 text-sm"
            >
              <RotateCcw className="h-3.5 w-3.5" strokeWidth={2} />
              {t("ocrReload")}
            </button>
          </div>
        ) : (
          <p className="animate-pulse text-ink-faint">{t("ocrProcessing")}</p>
        )}
      </section>

      {isConsulta && doc.status === "ready" && (
        <div className="mt-6">
          <Link href="/dashboard/briefings/new" className="ad-btn ad-btn-accent px-3.5 py-2 text-sm">
            {tRecord("prepareBriefing")}
          </Link>
        </div>
      )}

      {/* Per-document erasure (GDPR art. 17). Two-tap confirm: destructive
          and irreversible, but a modal would be heavier than the action
          deserves on a phone. */}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        {confirmingDelete ? (
          <>
            <span className="text-sm text-ink-soft">{t("deleteDocConfirm")}</span>
            <button
              type="button"
              onClick={() => void onDelete()}
              disabled={deleting}
              className="ad-btn ad-btn-danger px-3.5 py-2 text-sm"
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              {deleting ? t("deleteDocDeleting") : t("deleteDocYes")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(false)}
              disabled={deleting}
              className="ad-btn ad-btn-ghost px-3.5 py-2 text-sm"
            >
              {t("deleteDocCancel")}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingDelete(true)}
            className="ad-btn ad-btn-ghost px-3.5 py-2 text-sm text-error-text"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
            {t("deleteDoc")}
          </button>
        )}
        {deleteError && (
          <p role="alert" className="text-sm text-error-text">
            {t("deleteDocError")}
          </p>
        )}
      </div>
    </main>
  );
}
