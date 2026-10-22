"use client";

import { ChevronDown, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import type { EvidenceCitation } from "@/lib/chat-types";

// One source is one row: tag, complete title, institution and year. The
// literal passage is one tap away, not gone: the product's contract is a
// verifiable quotation, so it stays in the page (and in the HTML) and only
// stops pushing the next source down the screen.
export function EvidenceCard({ citation }: { citation: EvidenceCitation }) {
  const t = useTranslations("demo");
  const attribution = [
    citation.organization,
    citation.year ? `(${citation.year})` : null,
  ].filter(Boolean).join(" ");
  const snippet = citation.snippet?.trim();

  const row = (
    <div className="flex items-start gap-3">
      <span className="ad-ev-tag mt-0.5 shrink-0">{citation.tag}</span>
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm font-medium leading-snug text-ink">{citation.title}</p>
        {attribution && <p className="mt-1 text-xs leading-relaxed text-ink-soft">{attribution}</p>}
      </div>
    </div>
  );

  // Red flags name a guideline without retrieving a passage: nothing to
  // unfold, so the whole row is the link. Never show empty quotation marks.
  if (!snippet) {
    return (
      <div className="border-t border-line">
        {citation.url ? (
          <a href={citation.url} target="_blank" rel="noopener noreferrer" className="ad-ev-row flex min-h-11 items-start gap-2">
            <div className="min-w-0 flex-1">{row}</div>
            <span className="sr-only">{t("uxNewTab")}</span>
            <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-primary-text" strokeWidth={1.8} aria-hidden />
          </a>
        ) : (
          row
        )}
      </div>
    );
  }

  return (
    <details className="group border-t border-line">
      <summary className="ad-ev-row flex min-h-11 cursor-pointer list-none items-start gap-2 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 flex-1">
          {row}
          <span className="mt-1 block pl-9 text-xs text-primary-text">
            {t("uxLiteralPassage")}
          </span>
        </div>
        <ChevronDown
          className="mt-1 h-4 w-4 shrink-0 text-ink-soft motion-safe:transition-transform group-open:rotate-180"
          strokeWidth={2}
          aria-hidden
        />
      </summary>
      {/* The corpus stores a summary of each source, not its exact words, so
          no quotation marks: the original is one tap away, below. */}
      <blockquote className="whitespace-pre-wrap break-words pl-9 text-sm leading-relaxed text-ink-soft">{snippet}</blockquote>
      {citation.url && (
        <a
          href={citation.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex min-h-11 items-center gap-1.5 pl-9 text-xs text-primary-text hover:text-primary-text-hover mb-1"
        >
          {t("uxOpenSource")}
          <span className="sr-only">: {citation.title}. {t("uxNewTab")}</span>
          <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
        </a>
      )}
    </details>
  );
}
