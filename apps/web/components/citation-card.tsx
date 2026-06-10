"use client";
import { Link } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import type { Citation } from "@/lib/chat-types";

export function CitationCard({
  citation,
  index,
  locale,
}: {
  citation: Citation;
  index: number;
  locale: string;
}) {
  const t = useTranslations("chat");
  return (
    <Link
      href={`/dashboard/documents/${citation.document_id}`}
      className="inline-block rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] text-slate-700 hover:border-slate-400"
      title={citation.raw_quote.slice(0, 200)}
    >
      <span className="font-medium">[{index}]</span> {t("citationLabel")}
    </Link>
  );
}
