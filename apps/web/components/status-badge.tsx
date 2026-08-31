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

export function StatusBadge({ status }: { status: DocumentStatus }) {
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
      {status === "failed" && (
        <span className="flex items-center gap-1 text-[11px] font-medium text-error-text" role="alert">
          <RefreshCw className="h-3 w-3" strokeWidth={2.2} />
          {t("failedHint")}
        </span>
      )}
    </span>
  );
}
