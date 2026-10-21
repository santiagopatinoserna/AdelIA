"use client";

import { ChevronDown, ExternalLink } from "lucide-react";
import type { EvidenceCitation } from "@/lib/chat-types";

// One source is one row: tag, complete title, institution and year. The
// literal passage is one tap away, not gone: the product's contract is a
// verifiable quotation, so it stays in the page (and in the HTML) and only
// stops pushing the next source down the screen.
export function EvidenceCard({ citation }: { citation: EvidenceCitation }) {
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
      <div className="border-t border-line py-3">
        {citation.url ? (
          <a href={citation.url} target="_blank" rel="noopener" className="flex items-start gap-2 rounded-lg">
            <div className="min-w-0 flex-1">{row}</div>
            <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-primary-text" strokeWidth={1.8} aria-hidden />
          </a>
        ) : (
          row
        )}
      </div>
    );
  }

  return (
    <details className="group border-t border-line py-3">
      <summary className="flex min-h-11 cursor-pointer list-none items-start gap-2 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 flex-1">{row}</div>
        <ChevronDown
          className="mt-1 h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180"
          strokeWidth={2}
          aria-hidden
        />
      </summary>
      <blockquote className="mt-3 pl-9 text-sm leading-relaxed text-ink-soft">“{snippet}”</blockquote>
      {citation.url && (
        <a
          href={citation.url}
          target="_blank"
          rel="noopener"
          className="mt-3 inline-flex min-h-11 items-center gap-1.5 pl-9 text-xs text-primary-text hover:text-primary-text-hover"
        >
          {attribution || citation.title}
          <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
        </a>
      )}
    </details>
  );
}
