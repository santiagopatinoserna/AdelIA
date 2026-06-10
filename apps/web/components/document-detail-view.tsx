"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { getDocument, type DocumentDTO } from "@/lib/api-client-browser";
import { StatusBadge } from "@/components/status-badge";

const POLL_INTERVAL_MS = 2500;

export function DocumentDetailView({
  initialDoc,
  locale,
}: {
  initialDoc: DocumentDTO;
  locale: string;
}) {
  const [doc, setDoc] = useState<DocumentDTO>(initialDoc);
  const t = useTranslations("dashboard");

  const processing = doc.status === "processing";

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(async () => {
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
      <div className="flex items-center justify-between">
        <h1 className="truncate text-2xl font-semibold">{fileName}</h1>
        <StatusBadge status={doc.status} />
      </div>
      <p className="mt-2 text-sm text-slate-500">
        {new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(doc.created_at))}
      </p>
      <p className="mt-1 text-xs text-slate-400">
        {t("entitiesAndChunks", { count: doc.entity_count, chunks: doc.chunk_count })}
      </p>
      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6">
        {doc.raw_text ? (
          <pre className="whitespace-pre-wrap font-sans text-sm text-slate-800">{doc.raw_text}</pre>
        ) : (
          <p className="animate-pulse text-slate-400">{t("ocrProcessing")}</p>
        )}
      </section>
    </main>
  );
}
