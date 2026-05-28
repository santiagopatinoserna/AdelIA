"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { enrichment } from "@/lib/api-client";
import type { DrugInteraction, Severity } from "@/lib/enrichment-types";

const SEVERITY_STYLE: Record<Severity, string> = {
  contraindicated: "border-red-500 bg-red-50 text-red-900",
  major: "border-orange-500 bg-orange-50 text-orange-900",
  moderate: "border-yellow-400 bg-yellow-50 text-yellow-900",
  minor: "border-blue-300 bg-blue-50 text-blue-900",
};

export default function DrugInteractionsPage() {
  const t = useTranslations();
  const [meds, setMeds] = useState<string[]>([]);
  const [newMed, setNewMed] = useState("");
  const [interactions, setInteractions] = useState<DrugInteraction[]>([]);
  const [checked, setChecked] = useState(false);
  const [loading, setLoading] = useState(false);

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
    try {
      const res = await enrichment.checkDrugInteractions(meds);
      setInteractions(res);
      setChecked(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">💊 {t("enrichment.tabs.drugs")}</h1>

      <div className="mt-6 flex gap-2">
        <input
          type="text"
          value={newMed}
          onChange={(e) => setNewMed(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addMed()}
          placeholder={t("enrichment.drugs.placeholder")}
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={addMed}
          className="rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800"
        >
          +
        </button>
      </div>

      <ul className="mt-4 flex flex-wrap gap-2">
        {meds.map((m, i) => (
          <li
            key={`${m}-${i}`}
            className="flex items-center gap-1 rounded-full bg-slate-100 px-3 py-1 text-sm"
          >
            {m}
            <button type="button" onClick={() => removeMed(i)} className="text-slate-500">
              ×
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={check}
        disabled={meds.length < 2 || loading}
        className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
      >
        {loading ? "..." : t("enrichment.drugs.check")}
      </button>

      {checked && interactions.length === 0 && (
        <div className="mt-6 rounded border border-green-300 bg-green-50 p-4 text-sm text-green-800">
          ✅ {t("enrichment.drugs.noInteractions")}
        </div>
      )}

      <ul className="mt-6 space-y-3">
        {interactions.map((i, idx) => (
          <li
            key={idx}
            className={`rounded border-l-4 p-3 ${SEVERITY_STYLE[i.severity]}`}
          >
            <div className="flex items-center justify-between">
              <strong>
                {i.drug_a} ↔ {i.drug_b}
              </strong>
              <span className="rounded bg-white/50 px-2 py-0.5 text-xs uppercase">
                {t(`enrichment.drugs.severity.${i.severity}`)}
              </span>
            </div>
            <p className="mt-1 text-sm">{i.mechanism}</p>
            <p className="mt-1 text-sm font-medium">→ {i.recommendation}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
