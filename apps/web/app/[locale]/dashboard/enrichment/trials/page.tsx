"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { TestTube } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { ClinicalTrial } from "@/lib/enrichment-types";

export default function TrialsPage() {
  const t = useTranslations();
  const [condition, setCondition] = useState("");
  const [country, setCountry] = useState("");
  const [trials, setTrials] = useState<ClinicalTrial[]>([]);
  const [loading, setLoading] = useState(false);

  async function search() {
    if (!condition.trim()) return;
    setLoading(true);
    try {
      const res = await enrichment.searchTrials(condition, country || undefined);
      setTrials(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <TestTube className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("enrichment.tabs.trials")}
      </h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          placeholder={t("enrichment.trials.condition")}
          aria-label={t("enrichment.trials.condition")}
          className="flex-1 rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
        />
        <input
          type="text"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          placeholder={t("enrichment.trials.country")}
          aria-label={t("enrichment.trials.country")}
          className="w-32 rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
        />
        <button
          type="button"
          onClick={search}
          disabled={loading || !condition.trim()}
          className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:opacity-50"
        >
          {loading ? "..." : t("enrichment.trials.search")}
        </button>
      </div>

      {trials.length === 0 && !loading && condition && (
        <p className="mt-6 text-sm text-ink-faint">{t("enrichment.trials.noResults")}</p>
      )}

      <ul className="mt-6 space-y-3">
        {trials.map((trial) => (
          <li key={trial.nct_id} className="ad-card p-3">
            <div className="flex items-center justify-between">
              <a
                href={trial.url}
                target="_blank"
                rel="noopener"
                className="font-medium text-pine-600 hover:text-pine-700 underline decoration-pine-200 underline-offset-2"
              >
                {trial.title}
              </a>
              <span className="rounded bg-pine-50 px-2 py-0.5 text-xs text-pine-700 ring-1 ring-pine-100">
                {trial.status}
              </span>
            </div>
            <div className="mt-1 text-xs text-ink-faint">
              {trial.nct_id}
              {trial.phase && ` · ${trial.phase}`}
              {trial.sponsor && ` · ${trial.sponsor}`}
            </div>
            <p className="mt-2 text-sm text-ink-soft">{trial.brief_summary}</p>
            {trial.locations.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1">
                {trial.locations.slice(0, 5).map((loc, i) => (
                  <li
                    key={i}
                    className="rounded-full bg-pine-50 px-2 py-0.5 text-xs text-pine-700 ring-1 ring-pine-100"
                  >
                    {loc.city}, {loc.country}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
