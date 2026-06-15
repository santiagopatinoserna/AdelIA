"use client";

import { useTranslations } from "next-intl";

import { SPECIALTIES, type Specialty } from "@/lib/briefing-types";

interface Props {
  value: Specialty;
  onChange: (s: Specialty) => void;
  disabled?: boolean;
}

export function SpecialtySelect({ value, onChange, disabled }: Props) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-ink">{t("briefing.specialty.label")}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Specialty)}
        disabled={disabled}
        className="rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100 disabled:bg-surface-2"
      >
        {SPECIALTIES.map((s) => (
          <option key={s.value} value={s.value}>
            {t(s.labelKey)}
          </option>
        ))}
      </select>
    </div>
  );
}
