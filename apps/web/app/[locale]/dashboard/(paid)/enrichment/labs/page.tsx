"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FlaskConical, X } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { LabEvalResult } from "@/lib/enrichment-types";

interface LabInput {
  name: string;
  value: string;
}

const FLAG_STYLE: Record<string, string> = {
  low: "border-accent-line bg-accent-tint/60 text-ink",
  normal: "border-primary-text bg-primary-tint text-ink",
  high: "border-error bg-error-tint text-error-text",
};

export default function LabRangesPage() {
  const t = useTranslations();
  const [labs, setLabs] = useState<LabInput[]>([{ name: "", value: "" }]);
  const [sex, setSex] = useState<"M" | "F" | "">("");
  const [results, setResults] = useState<LabEvalResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evaluated, setEvaluated] = useState(false);

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
    setError(null);
    try {
      const valid = labs.filter((l) => l.name && l.value);
      const res = await enrichment.evaluateLabs({
        observations: valid,
        sex: sex || null,
      });
      setResults(res);
      setEvaluated(true);
    } catch {
      setError(t("enrichment.searchError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-ink">
        <FlaskConical className="h-5 w-5 text-primary-text" strokeWidth={2} />
        {t("enrichment.tabs.labs")}
      </h1>

      <div className="mt-4 flex items-center gap-2 text-sm text-ink">
        <label htmlFor="lab-sex">{t("enrichment.labs.sexLabel")}</label>
        <select
          id="lab-sex"
          value={sex}
          onChange={(e) => setSex(e.target.value as "M" | "F" | "")}
          aria-label={t("enrichment.labs.sexLabel")}
          className="rounded-lg border border-line-control bg-surface px-2 py-1 text-ink focus:border-primary-text"
        >
          <option value="">{t("enrichment.labs.sexChoose")}</option>
          <option value="M">{t("enrichment.labs.sexBoy")}</option>
          <option value="F">{t("enrichment.labs.sexGirl")}</option>
        </select>
      </div>
      <p className="mt-1.5 text-xs text-ink-soft">{t("enrichment.labs.sexHint")}</p>

      <div className="mt-6 space-y-2">
        {labs.map((lab, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={lab.name}
              onChange={(e) => update(i, "name", e.target.value)}
              placeholder={t("enrichment.labs.namePlaceholder")}
              aria-label={t("enrichment.labs.namePlaceholder")}
              className="flex-1 rounded-xl border border-line-control bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-primary-text"
            />
            <input
              type="text"
              value={lab.value}
              onChange={(e) => update(i, "value", e.target.value)}
              placeholder={t("enrichment.labs.valuePlaceholder")}
              aria-label={t("enrichment.labs.valuePlaceholder")}
              className="w-24 rounded-xl border border-line-control bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-primary-text"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              aria-label={t("common.remove")}
              className="rounded-lg px-2 py-1.5 text-ink-faint transition-colors hover:text-error-text"
            >
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          className="text-sm font-medium text-primary-text hover:text-primary-text-hover hover:underline"
        >
          + {t("enrichment.labs.addLab")}
        </button>
      </div>

      <div className="mt-4 flex flex-col items-start gap-2">
        <button
          type="button"
          onClick={evaluate}
          disabled={loading || labs.every((l) => !l.name) || !sex}
          className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-surface-2 disabled:text-ink-faint disabled:opacity-100"
        >
          {loading ? t("common.loading") : t("enrichment.labs.evaluate")}
        </button>
        {labs.every((l) => !l.name) && !loading ? (
          <span className="inline-flex items-center rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink-soft">
            {t("enrichment.labs.needOne")}
          </span>
        ) : !sex && !loading ? (
          <span className="inline-flex items-center rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink-soft">
            {t("enrichment.labs.sexRequired")}
          </span>
        ) : null}
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
          {error}
        </div>
      )}

      <ul className="mt-6 space-y-2">
        {results.map((r, idx) => (
          <li
            key={idx}
            className={`rounded-xl border-l-4 p-3 ${r.flag ? FLAG_STYLE[r.flag] : "border-line-strong bg-surface-2"}`}
          >
            <div className="flex items-center gap-2">
              {/* A result with no flag is a value the API REFUSED to judge
                  (no age, or no paediatric band for that age). Painting it
                  with the green "normal" badge, as this page used to, is the
                  false reassurance audit 3.5 exists to remove. */}
              <span
                className={`ad-eyebrow rounded px-2 py-0.5 ${
                  !r.flag
                    ? "bg-surface-2 text-ink-soft"
                    : r.flag === "high"
                      ? "bg-error-tint text-error-text"
                      : r.flag === "low"
                        ? "bg-accent-tint text-ink"
                        : "bg-primary-tint text-ink"
                }`}
              >
                {r.flag ? t(`enrichment.labs.${r.flag}`) : t("enrichment.labs.notEvaluated")}
              </span>
              <span className="font-medium text-ink">
                {r.canonical_name || r.name} = {r.value ?? "?"}{r.unit ? ` ${r.unit}` : ""}
              </span>
            </div>
            {r.reason && (
              <div className="mt-1 text-xs text-ink-soft">
                {r.reason === "unknown_age"
                  ? t("enrichment.labs.reasonUnknownAge")
                  : t("enrichment.labs.reasonNoPediatricBand")}
              </div>
            )}
            {r.zone_label && (
              <div className="mt-1 text-xs text-ink-soft">{r.zone_label}</div>
            )}
            {(r.range_low != null || r.range_high != null) && (
              <div className="mt-0.5 text-xs text-ink-faint">
                {t("enrichment.labs.reference")}:{" "}
                {r.range_low != null && r.range_high != null
                  ? `${r.range_low} - ${r.range_high}`
                  : (r.range_low ?? r.range_high)}{" "}
                {r.unit ?? ""}
                {r.age_band ? ` · ${t("enrichment.labs.ageBand")} ${r.age_band}` : ""}
              </div>
            )}
          </li>
        ))}
      </ul>

      {evaluated && !loading && !error && results.length === 0 && (
        <p className="mt-4 text-sm text-ink-faint">{t("enrichment.labs.noResults")}</p>
      )}
    </main>
  );
}
