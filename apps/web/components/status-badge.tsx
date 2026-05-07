"use client";
import { useTranslations } from "next-intl";
import type { DocumentStatus } from "@/lib/api-client";

const styles: Record<DocumentStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700",
  processing: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  failed: "bg-rose-100 text-rose-800",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const t = useTranslations("dashboard.status");
  // Backend never produces "uploaded" today (T8 derive_status returns
  // processing|ready|failed only). Map "uploaded" defensively to "processing"
  // until v0.1.1 schema cleanup removes the dead enum value.
  const label = status === "uploaded" ? "processing" : status;
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs ${styles[status]}`}>
      {t(label)}
    </span>
  );
}
