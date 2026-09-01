"use client";

import { useTranslations } from "next-intl";
import { ShieldAlert } from "lucide-react";

/**
 * The fixed clinical disclaimer (audit 3.8).
 *
 * It used to be a clause in the system prompt ("End with ..."), which meant
 * it appeared only when the model chose to obey it: never on a refusal, never
 * on a red-flag referral, and never at all on the agent canvas, which is the
 * screen a parent actually lands on. The prompt no longer asks for it; this
 * component paints it instead, on both answering surfaces, in the three
 * languages, anchored to the composer so it is visible without scrolling.
 *
 * Rendered inside the input footer on purpose: that footer is the one part of
 * the column that never scrolls away.
 */
export function ClinicalDisclaimer({ className = "" }: { className?: string }) {
  const t = useTranslations("common");
  return (
    <p
      data-testid="clinical-disclaimer"
      className={`flex items-start gap-1.5 px-1 text-xs leading-snug text-ink-soft ${className}`}
    >
      <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0 text-accent-text" strokeWidth={2} aria-hidden />
      <span>{t("clinicalDisclaimer")}</span>
    </p>
  );
}
