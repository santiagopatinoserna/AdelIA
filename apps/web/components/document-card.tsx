import { useTranslations } from "next-intl";

import { formatDay, formatInstant } from "@/lib/dates";
import { Link } from "@/lib/navigation";
import type { DocumentDTO } from "@/lib/api-client";
import { FailedHint, StatusBadge } from "./status-badge";
import { FileText, Mic } from "lucide-react";

export function DocumentCard({ doc, locale }: { doc: DocumentDTO; locale: string }) {
  const t = useTranslations("dashboard");
  const isConsulta = doc.source === "consulta";
  // Recordings get a human title ("Consulta del 20 de agosto de 2026"), not
  // the raw filename the recorder generated.
  // Telegram diary entries are titled by the day they describe, not by
  // the "diario-2026-08-27.ogg" filename the bot generated.
  const title = isConsulta
    ? t("consultaDocTitle", { date: formatInstant(doc.created_at, locale, "long") })
    : doc.diary_date
      ? t("diaryDocTitle", { date: formatDay(doc.diary_date, locale) })
      : doc.file_name;
  const Icon = isConsulta || (doc.diary_date && doc.mime_type.startsWith("audio/")) ? Mic : FileText;
  return (
    <Link
      href={`/dashboard/documents/${doc.id}`}
      className="ad-card ad-card-hover block p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
            <Icon className="h-4 w-4" strokeWidth={2} />
          </span>
          <span className="truncate text-base font-medium text-ink">{title}</span>
        </div>
        <StatusBadge status={doc.status} hint={false} />
      </div>
      {/* A date she reads ("3 nov 2026, 1:23"), not a log stamp with seconds
          in monospace. */}
      <p className="mt-2 pl-12 text-sm text-ink-soft">
        {formatInstant(doc.created_at, locale)}
      </p>
      {doc.status === "failed" && <FailedHint className="mt-1 pl-12" />}
    </Link>
  );
}
