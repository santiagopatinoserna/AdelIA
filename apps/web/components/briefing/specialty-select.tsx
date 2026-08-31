"use client";

import { useTranslations } from "next-intl";

import { SPECIALTIES, type Specialty } from "@/lib/briefing-types";

interface Props {
  value: Specialty | "";
  onChange: (s: Specialty | "") => void;
  disabled?: boolean;
}

export function SpecialtySelect({ value, onChange, disabled }: Props) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="specialty" className="text-sm font-medium text-ink">
        {t("briefing.specialty.label")}
      </label>
      <p className="text-sm text-ink-soft">{t("briefing.specialty.helper")}</p>
      <select
        id="specialty"
        value={value}
        onChange={(e) => onChange(e.target.value as Specialty | "")}
        disabled={disabled}
        className="rounded-xl border border-line-control bg-surface px-3 py-2 text-base text-ink focus:border-primary-text disabled:bg-surface-2"
      >
        <option value="" disabled>
          {t("briefing.specialty.placeholder")}
        </option>
        {SPECIALTIES.map((s) => (
          <option key={s.value} value={s.value}>
            {t(s.labelKey)}
          </option>
        ))}
      </select>
    </div>
  );
}
