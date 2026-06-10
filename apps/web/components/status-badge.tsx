"use client";
import { useTranslations } from "next-intl";
import type { DocumentStatus } from "@/lib/api-client-browser";

const styles: Record<DocumentStatus, string> = {
  processing: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  failed: "bg-rose-100 text-rose-800",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const t = useTranslations("dashboard.status");
  const label = status;
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs ${styles[label]}`}>
      {t(label)}
    </span>
  );
}
