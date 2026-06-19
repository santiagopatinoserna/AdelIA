"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Pill, X, CheckCircle2 } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { DrugInteraction, Severity } from "@/lib/enrichment-types";

const SEVERITY_STYLE: Record<Severity, string> = {
  contraindicated: "border-clay-500 bg-clay-50 text-clay-700",
  major: "border-clay-500 bg-clay-50 text-clay-700",
  moderate: "border-honey-400 bg-honey-100/60 text-ink",
  minor: "border-pine-400 bg-pine-50 text-ink",
};

export default function DrugInteractionsPage() {
  const t = useTranslations();
  const [meds, setMeds] = useState<string[]>([]);
  const [newMed, setNewMed] = useState("");
  const [interactions, setInteractions] = useState<DrugInteraction[]>([]);
  const [checked, setChecked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addMed() {
    if (!newMed.trim()) return;
    setMeds([...meds, newMed.trim()]);
    setNewMed("");
  }

  function removeMed(i: number) {
    setMeds(meds.filter((_, idx) => idx !== i));
  }

  async function check() {
    setLoading(true);
    setError(null);
    try {
      const res = await enrichment.checkDrugInteractions(meds);
      setInteractions(res);
      setChecked(true);
    } catch {
      setError(t("enrichment.searchError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Pill className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("enrichment.tabs.drugs")}
      </h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={newMed}
          onChange={(e) => setNewMed(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addMed()}
          placeholder={t("enrichment.drugs.placeholder")}
          aria-label={t("enrichment.drugs.placeholder")}
          className="flex-1 rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
        />
        <button
          type="button"
          onClick={addMed}
          className="ad-btn ad-btn-primary px-3 py-2 text-sm"
        >
          +
        </button>
      </div>

      <ul className="mt-4 flex flex-wrap gap-2">
        {meds.map((m, i) => (
          <li
            key={`${m}-${i}`}
            className="flex items-center gap-1 rounded-full bg-pine-50 px-3 py-1 text-sm text-pine-700 ring-1 ring-pine-100"
          >
            {m}
            <button
              type="button"
              onClick={() => removeMed(i)}
              aria-label={t("common.remove")}
              className="-mr-1 rounded-full p-1 text-ink-faint transition-colors hover:text-clay-600"
            >
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-col items-start gap-2">
        <button
          type="button"
          onClick={check}
          disabled={meds.length < 2 || loading}
          className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-surface-2 disabled:text-ink-faint disabled:opacity-100"
        >
          {loading ? t("common.loading") : t("enrichment.drugs.check")}
        </button>
        {meds.length < 2 && !loading && (
          <span className="inline-flex items-center rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink-soft">
            {t("enrichment.drugs.needTwo")}
          </span>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {error}
        </div>
      )}

      {checked && interactions.length === 0 && (
        <div className="mt-6 flex items-start gap-2 rounded-xl border border-pine-100 bg-pine-50 p-4 text-sm text-pine-800">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-pine-500" strokeWidth={2.2} />
          <div>
            <p className="font-medium">
              {t("enrichment.drugs.noInteractionsTitle", { drugs: meds.join(", ") })}
            </p>
            <p className="mt-0.5 text-pine-700">{t("enrichment.drugs.noInteractionsHint")}</p>
          </div>
        </div>
      )}

      <ul className="mt-6 space-y-3">
        {interactions.map((i, idx) => (
          <li
            key={idx}
            className={`rounded-xl border-l-4 p-3 ${SEVERITY_STYLE[i.severity]}`}
          >
            <div className="flex items-center justify-between">
              <strong>
                {i.drug_a} ↔ {i.drug_b}
              </strong>
              <span className="ad-eyebrow rounded bg-surface/70 px-2 py-0.5">
                {t(`enrichment.drugs.severityMom.${i.severity}`)}
              </span>
            </div>
            <p className="mt-1 text-xs text-ink-soft">
              {t("enrichment.drugs.severityMeans")}: {t(`enrichment.drugs.severityPlain.${i.severity}`)}
            </p>
            <p className="mt-2 text-sm">{i.mechanism}</p>
            <p className="mt-1 text-sm font-medium">→ {i.recommendation}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
