"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { enrichment } from "@/lib/api-client-browser";
import type { VariantHit } from "@/lib/enrichment-types";

const CATEGORY_STYLE: Record<string, string> = {
  pharmacogenomics: "border-purple-500 bg-purple-50",
  carrier_status: "border-blue-500 bg-blue-50",
  disease_risk: "border-orange-400 bg-orange-50",
};

export default function GenomicsPage() {
  const t = useTranslations();
  const [file, setFile] = useState<File | null>(null);
  const [hits, setHits] = useState<VariantHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const res = await enrichment.uploadGenomics(file);
      setHits(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">🧬 {t("enrichment.tabs.genomics")}</h1>
      <p className="mt-1 text-sm text-slate-600">{t("enrichment.genomics.disclaimer")}</p>

      <div className="mt-6 rounded-lg border-2 border-dashed border-slate-300 bg-white p-6 text-center">
        <input
          type="file"
          accept=".txt,.tsv,.csv,text/plain,text/tab-separated-values"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        {file && <div className="mt-2 text-sm text-slate-600">{file.name}</div>}
        <button
          type="button"
          onClick={upload}
          disabled={!file || loading}
          className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
        >
          {loading ? "..." : t("enrichment.genomics.upload")}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <ul className="mt-6 space-y-3">
        {hits.map((h) => (
          <li
            key={h.rsid}
            className={`rounded border-l-4 p-3 ${CATEGORY_STYLE[h.category] ?? ""}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <strong>{h.gene}</strong> · {h.rsid} · {h.user_genotype}
              </div>
              <div className="flex gap-1">
                <span className="rounded bg-white/60 px-2 py-0.5 text-xs">
                  {t(`enrichment.genomics.zygosity.${h.zygosity}`)}
                </span>
                <span className="rounded bg-white/60 px-2 py-0.5 text-xs">
                  {t(`enrichment.genomics.categories.${h.category}`)}
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm font-medium">{h.phenotype}</p>
            <p className="mt-1 text-sm">→ {h.actionability}</p>
            <div className="mt-2 text-xs text-slate-500">
              {h.evidence_level}
              {h.url && (
                <>
                  {" · "}
                  <a href={h.url} target="_blank" rel="noopener" className="text-blue-700 hover:underline">
                    source
                  </a>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
