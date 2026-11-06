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
      // The answer's [N] marker shows this number and jumps here.
      data-cite-target={`rec_${index}`}
      className="inline-flex min-h-[28px] items-center gap-1 rounded-md border border-primary-tint-line bg-primary-tint px-2 py-1 text-xs text-primary-text underline decoration-primary-tint-line underline-offset-2 transition-colors hover:border-line-control hover:bg-primary-tint-line hover:decoration-primary-text"
      title={citation.raw_quote.slice(0, 200)}
    >
      <span data-testid="source-number" className="ad-src-num ad-src-num-rec no-underline">
        {index}
      </span>
      {t("citationLabel")}
      <ArrowUpRight className="h-3 w-3 shrink-0 no-underline" strokeWidth={2.2} />
    </Link>
  );
}
