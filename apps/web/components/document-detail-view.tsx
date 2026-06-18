"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, RotateCcw } from "lucide-react";

import { Link } from "@/lib/navigation";
import { getDocument, type DocumentDTO } from "@/lib/api-client-browser";
import { StatusBadge } from "@/components/status-badge";

const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 120; // ~5 min — then stop the spinner and offer a reload

export function DocumentDetailView({
  initialDoc,
  locale,
}: {
  initialDoc: DocumentDTO;
  locale: string;
}) {
  const [doc, setDoc] = useState<DocumentDTO>(initialDoc);
  const [timedOut, setTimedOut] = useState(false);
  const pollsRef = useRef(0);
  const t = useTranslations("dashboard");

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

  const fileName = doc.file_name;
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <Link
        href="/dashboard"
        className="mb-5 inline-flex items-center gap-1.5 text-sm text-ink-soft transition-colors hover:text-pine-700"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={2} />
        {t("title")}
      </Link>
      <div className="flex items-start justify-between gap-3">
        <h1 className="min-w-0 truncate text-2xl text-pine-900">{fileName}</h1>
        <StatusBadge status={doc.status} />
      </div>
      <p className="mt-2 font-mono text-xs text-ink-faint">
        {new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(doc.created_at))}
        {doc.raw_text ? `  ·  ${t("docReady")}` : ""}
      </p>
      <section className="ad-card mt-8 p-6">
        {doc.raw_text ? (
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
    </main>
  );
}
