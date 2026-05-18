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
      <label className="text-sm font-medium">{t("briefing.specialty.label")}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Specialty)}
        disabled={disabled}
        className="rounded border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-500 disabled:bg-slate-100"
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
