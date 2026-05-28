"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ingestion } from "@/lib/api-client";
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
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold">🏥 CCD / MyChart import</h1>
      <p className="mt-1 text-sm text-slate-600">
        Sube el XML descargado del portal de pacientes (Epic, Cerner, Allscripts, Athena…)
      </p>

      <div className="mt-6 rounded-lg border-2 border-dashed border-slate-300 bg-white p-8 text-center">
        <input
          type="file"
          accept=".xml,application/xml,text/xml"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="mb-3"
        />
        {file && <div className="text-sm text-slate-600">{file.name}</div>}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!file || submitting}
          className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
        >
          {submitting ? t("ingestion.processing") : t("ingestion.uploadCcd")}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 rounded border border-green-300 bg-green-50 p-4">
          <h3 className="font-semibold text-green-900">{t("ingestion.imported")}</h3>
          <ul className="mt-2 space-y-1 text-sm text-green-800">
            <li>
              {result.entity_count} {t("ingestion.entities")}
            </li>
            {result.sample_names.length > 0 && (
              <li className="mt-2 text-xs">
                Sample: {result.sample_names.join(", ")}
              </li>
            )}
          </ul>
        </div>
      )}
    </main>
  );
}
