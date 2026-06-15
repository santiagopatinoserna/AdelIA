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
      className="inline-flex items-center gap-1 rounded-md border border-pine-100 bg-pine-50 px-2 py-0.5 text-[11px] text-pine-700 transition-colors hover:border-pine-200 hover:bg-pine-100"
      title={citation.raw_quote.slice(0, 200)}
    >
      <span className="font-mono font-semibold">[{index}]</span> {t("citationLabel")}
    </Link>
  );
}
