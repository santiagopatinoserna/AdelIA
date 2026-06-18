"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Building2, CheckCircle2 } from "lucide-react";

import { ingestion } from "@/lib/api-client-browser";
import type { IngestionImportResult } from "@/lib/enrichment-types";

export default function CcdImportPage() {
  const t = useTranslations();
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<IngestionImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const res = await ingestion.importCcd(file);
      setResult(res);
    } catch (e) {
      setError(t("common.actionError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Building2 className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("ingestion.ccd.title")}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">
        {t("ingestion.ccd.instructions")}
      </p>

      <div className="ad-card mt-6 rounded-2xl border-2 border-dashed border-line-strong bg-surface-2/60 p-8 text-center">
        <input
          type="file"
          accept=".xml,application/xml,text/xml"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label={t("ingestion.uploadCcd")}
          className="mb-3 block w-full text-sm text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-pine-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-pine-700 hover:file:bg-pine-100"
        />
        {file && <div className="text-sm text-ink-soft">{file.name}</div>}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!file || submitting}
          className="ad-btn ad-btn-primary mt-4 px-4 py-2 text-sm disabled:opacity-50"
        >
          {submitting ? t("ingestion.processing") : t("ingestion.uploadCcd")}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 rounded-xl border border-pine-100 bg-pine-50 p-4">
          <h3 className="flex items-center gap-2 font-semibold text-pine-800">
            <CheckCircle2 className="h-4 w-4 text-pine-500" strokeWidth={2.2} />
            {t("ingestion.imported")}
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-ink">
            <li>
              {t("ingestion.entityCount", { count: result.entity_count })}
            </li>
            {result.sample_names.length > 0 && (
              <li className="mt-2 text-xs text-ink-soft">
                {t("ingestion.sampleLabel")} {result.sample_names.join(", ")}
              </li>
            )}
          </ul>
        </div>
      )}
    </main>
  );
}
