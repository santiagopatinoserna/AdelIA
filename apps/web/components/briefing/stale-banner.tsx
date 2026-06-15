"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";

interface Props {
  onRegenerate: () => void;
  disabled?: boolean;
}

export function StaleBanner({ onRegenerate, disabled }: Props) {
  const t = useTranslations();
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-honey-200 bg-honey-100/60 p-3 text-sm text-ink">
      <span className="flex items-center gap-2">
        <RefreshCw className="h-4 w-4 shrink-0 text-honey-600" strokeWidth={2.2} />
        {t("briefing.staleBanner")}
      </span>
      <button
        type="button"
        onClick={onRegenerate}
        disabled={disabled}
        className="ad-btn shrink-0 bg-honey-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-honey-600 disabled:opacity-50"
      >
        {t("briefing.regenerate")}
      </button>
    </div>
  );
}
