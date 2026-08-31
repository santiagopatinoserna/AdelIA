"use client";
import { Link } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
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
      className="inline-flex min-h-[28px] items-center gap-1 rounded-md border border-primary-tint-line bg-primary-tint px-2 py-1 text-xs text-primary-text underline decoration-primary-tint-line underline-offset-2 transition-colors hover:border-line-control hover:bg-primary-tint-line hover:decoration-primary-text"
      title={citation.raw_quote.slice(0, 200)}
    >
      <span className="font-mono font-semibold no-underline">[{index}]</span>
      {t("citationLabel")}
      <ArrowUpRight className="h-3 w-3 shrink-0 no-underline" strokeWidth={2.2} />
    </Link>
  );
}
