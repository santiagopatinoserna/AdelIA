"use client";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import type { DocumentStatus } from "@/lib/api-client-browser";

const styles: Record<DocumentStatus, { badge: string; dot: string }> = {
  processing: { badge: "bg-honey-100 text-honey-700 ring-honey-200", dot: "bg-honey-500" },
  ready: { badge: "bg-pine-50 text-pine-700 ring-pine-100", dot: "bg-pine-500" },
  failed: { badge: "bg-clay-50 text-clay-600 ring-clay-100", dot: "bg-clay-500" },
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
        <span className="flex items-center gap-1 text-[11px] font-medium text-clay-600" role="alert">
          <RefreshCw className="h-3 w-3" strokeWidth={2.2} />
          {t("failedHint")}
        </span>
      )}
    </span>
  );
}
