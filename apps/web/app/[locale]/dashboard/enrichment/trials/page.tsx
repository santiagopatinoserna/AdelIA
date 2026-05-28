"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { enrichment } from "@/lib/api-client";
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
      <h1 className="text-2xl font-semibold">🧪 {t("enrichment.tabs.trials")}</h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          placeholder={t("enrichment.trials.condition")}
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          type="text"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          placeholder={t("enrichment.trials.country")}
          className="w-32 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={search}
          disabled={loading || !condition.trim()}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:bg-slate-400"
        >
          {loading ? "..." : t("enrichment.trials.search")}
        </button>
      </div>

      {trials.length === 0 && !loading && condition && (
        <p className="mt-6 text-sm text-slate-500">{t("enrichment.trials.noResults")}</p>
      )}

      <ul className="mt-6 space-y-3">
        {trials.map((trial) => (
          <li key={trial.nct_id} className="rounded border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <a
                href={trial.url}
                target="_blank"
                rel="noopener"
                className="font-medium text-blue-700 hover:underline"
              >
                {trial.title}
              </a>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                {trial.status}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {trial.nct_id}
              {trial.phase && ` · ${trial.phase}`}
              {trial.sponsor && ` · ${trial.sponsor}`}
            </div>
            <p className="mt-2 text-sm text-slate-700">{trial.brief_summary}</p>
            {trial.locations.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1">
                {trial.locations.slice(0, 5).map((loc, i) => (
                  <li
                    key={i}
                    className="rounded-full bg-slate-100 px-2 py-0.5 text-xs"
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
