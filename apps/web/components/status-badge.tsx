"use client";
import { useTranslations } from "next-intl";
import type { DocumentStatus } from "@/lib/api-client-browser";

const styles: Record<DocumentStatus, { badge: string; dot: string }> = {
  processing: { badge: "bg-honey-100 text-honey-600 ring-honey-200", dot: "bg-honey-500" },
  ready: { badge: "bg-pine-50 text-pine-700 ring-pine-100", dot: "bg-pine-500" },
  failed: { badge: "bg-clay-50 text-clay-600 ring-clay-100", dot: "bg-clay-500" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const t = useTranslations("dashboard.status");
  const s = styles[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${s.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot} ${status === "processing" ? "animate-pulse" : ""}`} />
      {t(status)}
    </span>
  );
}
