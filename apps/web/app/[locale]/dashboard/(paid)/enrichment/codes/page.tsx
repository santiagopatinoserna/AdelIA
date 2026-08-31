"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ClipboardList } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { NormalizedCode } from "@/lib/enrichment-types";

export default function CodesLookupPage() {
  const t = useTranslations();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<NormalizedCode | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function lookup() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await enrichment.normalize(query);
      setResult(res);
    } catch {
      setError(t("enrichment.searchError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-ink">
        <ClipboardList className="h-5 w-5 text-primary-text" strokeWidth={2} />
        {t("enrichment.tabs.codes")}
      </h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && lookup()}
          placeholder={t("enrichment.codes.placeholder")}
          aria-label={t("enrichment.codes.placeholder")}
          className="flex-1 rounded-xl border border-line-control bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-primary-text"
        />
        <button
          type="button"
          onClick={lookup}
          disabled={loading || !query.trim()}
          className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-surface-2 disabled:text-ink-faint disabled:opacity-100"
        >
          {loading ? t("common.loading") : t("enrichment.codes.lookup")}
        </button>
      </div>

      {!query.trim() && !loading && (
        <p className="mt-2 inline-flex items-center rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink-soft">
          {t("enrichment.codes.needQuery")}
        </p>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
          {error}
        </div>
      )}

      {result && (
        <div className="ad-card mt-6 p-4">
          {result.canonical_name ? (
            <>
              <h3 className="font-medium text-ink">{result.canonical_name}</h3>
              <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-ink-soft">{t("enrichment.codes.icd10")}:</dt>
                <dd className="font-mono text-ink">{result.icd10}</dd>
                <dt className="text-ink-soft">{t("enrichment.codes.snomed")}:</dt>
                <dd className="font-mono text-ink">{result.snomed}</dd>
                <dt className="text-ink-soft">{t("enrichment.codes.category")}:</dt>
                <dd className="text-ink">{result.category}</dd>
                <dt className="text-ink-soft">{t("enrichment.codes.match")}:</dt>
                <dd className="text-ink">{result.match_score}%</dd>
              </dl>
            </>
          ) : (
            <p className="text-sm text-ink-faint">{t("enrichment.codes.noMatch")}</p>
          )}
        </div>
      )}
    </main>
  );
}
