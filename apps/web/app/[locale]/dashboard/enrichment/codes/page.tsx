"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { enrichment } from "@/lib/api-client-browser";
import type { NormalizedCode } from "@/lib/enrichment-types";

export default function CodesLookupPage() {
  const t = useTranslations();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<NormalizedCode | null>(null);
  const [loading, setLoading] = useState(false);

  async function lookup() {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await enrichment.normalize(query);
      setResult(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">📋 {t("enrichment.tabs.codes")}</h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && lookup()}
          placeholder={t("enrichment.codes.placeholder")}
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={lookup}
          disabled={loading || !query.trim()}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:bg-slate-400"
        >
          {loading ? "..." : t("enrichment.codes.lookup")}
        </button>
      </div>

      {result && (
        <div className="mt-6 rounded border border-slate-200 bg-white p-4">
          {result.canonical_name ? (
            <>
              <h3 className="font-medium">{result.canonical_name}</h3>
              <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-slate-600">{t("enrichment.codes.icd10")}:</dt>
                <dd className="font-mono">{result.icd10}</dd>
                <dt className="text-slate-600">{t("enrichment.codes.snomed")}:</dt>
                <dd className="font-mono">{result.snomed}</dd>
                <dt className="text-slate-600">{t("enrichment.codes.category")}:</dt>
                <dd>{result.category}</dd>
                <dt className="text-slate-600">{t("enrichment.codes.match")}:</dt>
                <dd>{result.match_score}%</dd>
              </dl>
            </>
          ) : (
            <p className="text-sm text-slate-500">{t("enrichment.codes.noMatch")}</p>
          )}
        </div>
      )}
    </main>
  );
}
