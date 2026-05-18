"use client";

import { useTranslations } from "next-intl";

interface Props {
  onRegenerate: () => void;
  disabled?: boolean;
}

export function StaleBanner({ onRegenerate, disabled }: Props) {
  const t = useTranslations();
  return (
    <div className="mb-4 flex items-center justify-between rounded border border-yellow-300 bg-yellow-50 p-3 text-sm text-yellow-900">
      <span>{t("briefing.staleBanner")}</span>
      <button
        type="button"
        onClick={onRegenerate}
        disabled={disabled}
        className="rounded bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700 disabled:bg-slate-400"
      >
        {t("briefing.regenerate")}
      </button>
    </div>
  );
}
