import { useTranslations } from "next-intl";

import { Link } from "@/lib/navigation";
import type { DocumentDTO } from "@/lib/api-client";
import { StatusBadge } from "./status-badge";
import { FileText, Mic } from "lucide-react";

export function DocumentCard({ doc, locale }: { doc: DocumentDTO; locale: string }) {
  const t = useTranslations("dashboard");
  const isConsulta = doc.source === "consulta";
  // Recordings get a human title ("Consulta del 20 de agosto de 2026"), not
  // the raw filename the recorder generated.
  const title = isConsulta
    ? t("consultaDocTitle", {
        date: new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(
          new Date(doc.created_at),
        ),
      })
    : doc.file_name;
  const Icon = isConsulta ? Mic : FileText;
  return (
    <Link
      href={`/dashboard/documents/${doc.id}`}
      className="ad-card ad-card-hover block p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100">
            <Icon className="h-4 w-4" strokeWidth={2} />
          </span>
          <span className="truncate text-sm font-medium text-ink">{title}</span>
        </div>
        <StatusBadge status={doc.status} />
      </div>
      <p className="mt-3 pl-12 font-mono text-xs text-ink-soft">
        {new Date(doc.created_at).toLocaleString(locale)}
      </p>
    </Link>
  );
}
