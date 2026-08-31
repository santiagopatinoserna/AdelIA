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
  const [error, setError] = useState<string | null>(null);

  async function search() {
    if (!condition.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await enrichment.searchTrials(condition, country || undefined);
      setTrials(res);
    } catch {
      setError(t("enrichment.searchError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-ink">
        <TestTube className="h-5 w-5 text-primary-text" strokeWidth={2} />
        {t("enrichment.tabs.trials")}
      </h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          placeholder={t("enrichment.trials.condition")}
          aria-label={t("enrichment.trials.condition")}
          className="flex-1 rounded-xl border border-line-control bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-primary-text"
        />
        <input
          type="text"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          placeholder={t("enrichment.trials.country")}
          aria-label={t("enrichment.trials.country")}
          className="w-32 rounded-xl border border-line-control bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-primary-text"
        />
        <button
          type="button"
          onClick={search}
          disabled={loading || !condition.trim()}
          className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-surface-2 disabled:text-ink-faint disabled:opacity-100"
        >
          {loading ? t("common.loading") : t("enrichment.trials.search")}
        </button>
      </div>

      {!condition.trim() && !loading && (
        <p className="mt-2 inline-flex items-center rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink-soft">
          {t("enrichment.trials.needCondition")}
        </p>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
          {error}
        </div>
      )}

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
                className="font-medium text-primary-text hover:text-primary-text-hover underline decoration-primary-tint-line underline-offset-2"
              >
                {trial.title}
              </a>
              <span className="rounded bg-primary-tint px-2 py-0.5 text-xs text-primary-text ring-1 ring-primary-tint-line">
                {trial.status}
              </span>
            </div>
            <div className="mt-1 text-xs text-ink-faint">
              {trial.nct_id}
              {trial.phase && ` · ${trial.phase}`}
              {trial.sponsor && ` · ${trial.sponsor}`}
            </div>
            {trial.phase && (
              <p className="mt-1 text-xs text-ink-soft">{t("enrichment.trials.phaseLegend")}</p>
            )}
            {(trial.eligibility_age_min ||
              trial.eligibility_age_max ||
              trial.eligibility_sex) && (
              <div className="mt-2 inline-flex flex-wrap items-center gap-2 rounded-lg bg-primary-tint px-2.5 py-1.5 text-xs text-ink ring-1 ring-primary-tint-line">
                <span className="font-medium">{t("enrichment.trials.whoCanJoin")}:</span>
                {(trial.eligibility_age_min || trial.eligibility_age_max) && (
                  <span>
                    {t("enrichment.trials.ageLabel")}{" "}
                    {trial.eligibility_age_min ?? "·"}
                    {" – "}
                    {trial.eligibility_age_max ?? "·"}
                  </span>
                )}
                {trial.eligibility_sex && (
                  <span>
                    {t("enrichment.trials.sexLabel")} {trial.eligibility_sex}
                  </span>
                )}
              </div>
            )}
            <p className="mt-2 text-sm text-ink-soft">{trial.brief_summary}</p>
            {trial.locations.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1">
                {trial.locations.slice(0, 5).map((loc, i) => (
                  <li
                    key={i}
                    className="rounded-full bg-primary-tint px-2 py-0.5 text-xs text-primary-text ring-1 ring-primary-tint-line"
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
