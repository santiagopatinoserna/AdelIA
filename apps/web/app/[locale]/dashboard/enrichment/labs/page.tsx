"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { enrichment } from "@/lib/api-client-browser";
import type { LabEvalResult } from "@/lib/enrichment-types";

interface LabInput {
  name: string;
  value: string;
}

const FLAG_STYLE: Record<string, string> = {
  low: "border-blue-400 bg-blue-50 text-blue-900",
  normal: "border-green-400 bg-green-50 text-green-900",
  high: "border-red-400 bg-red-50 text-red-900",
};

export default function LabRangesPage() {
  const t = useTranslations();
  const [labs, setLabs] = useState<LabInput[]>([{ name: "", value: "" }]);
  const [sex, setSex] = useState<"M" | "F" | "">("");
  const [results, setResults] = useState<LabEvalResult[]>([]);
  const [loading, setLoading] = useState(false);

  function update(i: number, field: keyof LabInput, value: string) {
    const next = [...labs];
    next[i] = { ...next[i], [field]: value };
    setLabs(next);
  }

  function addRow() {
    setLabs([...labs, { name: "", value: "" }]);
  }

  function removeRow(i: number) {
    setLabs(labs.filter((_, idx) => idx !== i));
  }

  async function evaluate() {
    setLoading(true);
    try {
      const valid = labs.filter((l) => l.name && l.value);
      const res = await enrichment.evaluateLabs({
        observations: valid,
        sex: sex || null,
      });
      setResults(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">🔬 {t("enrichment.tabs.labs")}</h1>

      <div className="mt-4 flex items-center gap-2 text-sm">
        <label>Sex:</label>
        <select
          value={sex}
          onChange={(e) => setSex(e.target.value as "M" | "F" | "")}
          className="rounded border border-slate-300 px-2 py-1"
        >
          <option value="">—</option>
          <option value="M">M</option>
          <option value="F">F</option>
        </select>
      </div>

      <div className="mt-6 space-y-2">
        {labs.map((lab, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={lab.name}
              onChange={(e) => update(i, "name", e.target.value)}
              placeholder="HbA1c, glucose, ldl, ..."
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              type="text"
              value={lab.value}
              onChange={(e) => update(i, "value", e.target.value)}
              placeholder="value"
              className="w-24 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              className="px-3 text-slate-500"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          className="text-sm text-blue-700 hover:underline"
        >
          + {t("enrichment.labs.addLab")}
        </button>
      </div>

      <button
        type="button"
        onClick={evaluate}
        disabled={loading || labs.every((l) => !l.name)}
        className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
      >
        {loading ? "..." : t("enrichment.labs.evaluate")}
      </button>

      <ul className="mt-6 space-y-2">
        {results.map((r, idx) => (
          <li
            key={idx}
            className={`rounded border-l-4 p-3 ${r.flag ? FLAG_STYLE[r.flag] : "border-slate-200 bg-white"}`}
          >
            <div className="font-medium">
              {r.canonical_name || r.name} = {r.value ?? "?"}{r.unit ? ` ${r.unit}` : ""}
              {r.zone_label && (
                <span className="ml-2 rounded bg-white/50 px-2 py-0.5 text-xs">
                  {r.zone_label}
                </span>
              )}
            </div>
            {r.range_low != null && r.range_high != null && (
              <div className="text-xs text-slate-600">
                {t("enrichment.labs.reference")}: {r.range_low} - {r.range_high} {r.unit ?? ""}
              </div>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
