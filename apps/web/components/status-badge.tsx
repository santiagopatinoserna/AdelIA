"use client";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import type { DocumentStatus } from "@/lib/api-client-browser";

const styles: Record<DocumentStatus, { badge: string; dot: string }> = {
// "Processing" is the system working, so it takes the info role (harbor)
// rather than borrowing amber, which now means "discover". The DOT carries
// no text, so it uses the *-text token (3:1 on its own tint), never *-line.
  processing: { badge: "bg-info-tint text-info-text ring-info-line", dot: "bg-info-text" },
  ready: { badge: "bg-success-tint text-success-text ring-success-line", dot: "bg-success-text" },
  failed: { badge: "bg-error-tint text-error-text ring-error-line", dot: "bg-error-text" },
};

// `hint={false}` when the caller prints the failed hint itself: in a card the
// hint under the badge took the row's width and left the file name as "sa…"
// at 390 px (RECORRIDO_POC.md).
export function StatusBadge({ status, hint = true }: { status: DocumentStatus; hint?: boolean }) {
  const t = useTranslations("dashboard.status");
  const s = styles[status];
  // Friendly, de-jargoned label: a soft ETA while we read the document.
  const label = status === "processing" ? t("processingEta") : t(status);
  return (
    <span className="flex shrink-0 flex-col items-end gap-1.5">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${s.badge}`}
        role={status === "processing" ? "status" : undefined}
        aria-live={status === "processing" ? "polite" : undefined}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${s.dot} ${status === "processing" ? "animate-pulse" : ""}`} />
        {label}
      </span>
      {status === "failed" && hint && <FailedHint />}
    </span>
  );
}

export function FailedHint({ className = "" }: { className?: string }) {
  const t = useTranslations("dashboard.status");
  return (
    <span className={`flex items-center gap-1 text-[11px] font-medium text-error-text ${className}`} role="alert">
      <RefreshCw className="h-3 w-3" strokeWidth={2.2} />
      {t("failedHint")}
    </span>
  );
}
