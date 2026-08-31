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
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-accent-tint-line bg-accent-tint/60 p-3 text-sm text-ink">
      <span className="flex items-center gap-2">
        <RefreshCw className="h-4 w-4 shrink-0 text-accent-text" strokeWidth={2.2} />
        {t("briefing.staleBanner")}
      </span>
      <button
        type="button"
        onClick={onRegenerate}
        disabled={disabled}
        className="ad-btn ad-btn-accent shrink-0 px-3 py-1.5 text-xs font-medium"
      >
        {t("briefing.regenerate")}
      </button>
    </div>
  );
}
