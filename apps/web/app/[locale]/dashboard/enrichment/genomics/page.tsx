"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Dna } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { VariantHit } from "@/lib/enrichment-types";

const CATEGORY_STYLE: Record<string, string> = {
  pharmacogenomics: "border-pine-400 bg-pine-50",
  carrier_status: "border-honey-400 bg-honey-100/60",
  disease_risk: "border-clay-500 bg-clay-50",
};

export default function GenomicsPage() {
  const t = useTranslations();
  const [file, setFile] = useState<File | null>(null);
  const [hits, setHits] = useState<VariantHit[]>([]);
  const [analyzedAt, setAnalyzedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    enrichment
      .savedGenomics()
      .then((saved) => {
        if (saved.variants.length) {
          setHits(saved.variants);
          setAnalyzedAt(saved.analyzed_at);
        }
      })
      .catch(() => {
        // no saved analysis (or transient error) — page still works via upload
      });
  }, []);

  async function upload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const res = await enrichment.uploadGenomics(file);
      setHits(res);
      setAnalyzedAt(new Date().toISOString());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Dna className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("enrichment.tabs.genomics")}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">{t("enrichment.genomics.disclaimer")}</p>
      {analyzedAt && (
        <p className="mt-1 text-xs text-ink-faint">
          {t("enrichment.genomics.savedFrom")}{" "}
          {new Date(analyzedAt).toLocaleDateString()}
        </p>
      )}

      <div className="ad-card mt-6 rounded-2xl border-2 border-dashed border-line-strong bg-surface-2/60 p-6 text-center">
        <input
          type="file"
          accept=".txt,.tsv,.csv,text/plain,text/tab-separated-values"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label={t("enrichment.genomics.upload")}
          className="block w-full text-sm text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-pine-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-pine-700 hover:file:bg-pine-100"
        />
        {file && <div className="mt-2 text-sm text-ink-soft">{file.name}</div>}
        <button
          type="button"
          onClick={upload}
          disabled={!file || loading}
          className="ad-btn ad-btn-primary mt-4 px-4 py-2 text-sm disabled:opacity-50"
        >
          {loading ? "..." : t("enrichment.genomics.upload")}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {error}
        </div>
      )}

      <ul className="mt-6 space-y-3">
        {hits.map((h) => (
          <li
            key={h.rsid}
            className={`rounded-xl border-l-4 p-3 ${CATEGORY_STYLE[h.category] ?? ""}`}
          >
            <div className="flex items-center justify-between">
              <div className="text-ink">
                <strong>{h.gene}</strong> · {h.rsid} · {h.user_genotype}
              </div>
              <div className="flex gap-1">
                <span className="rounded bg-surface/70 px-2 py-0.5 text-xs text-ink-soft">
                  {t(`enrichment.genomics.zygosity.${h.zygosity}`)}
                </span>
                <span className="rounded bg-surface/70 px-2 py-0.5 text-xs text-ink-soft">
                  {t(`enrichment.genomics.categories.${h.category}`)}
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm font-medium text-ink">{h.phenotype}</p>
            <p className="mt-1 text-sm text-ink">→ {h.actionability}</p>
            <div className="mt-2 text-xs text-ink-faint">
              {h.evidence_level}
              {h.url && (
                <>
                  {" · "}
                  <a href={h.url} target="_blank" rel="noopener" className="text-pine-600 hover:text-pine-700 underline decoration-pine-200 underline-offset-2">
                    {t("enrichment.genomics.source")}
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
