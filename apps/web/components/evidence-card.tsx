"use client";

import { ExternalLink } from "lucide-react";
import type { EvidenceCitation } from "@/lib/chat-types";

export function EvidenceCard({ citation }: { citation: EvidenceCitation }) {
  const attribution = [
    citation.organization,
    citation.year ? `(${citation.year})` : null,
  ].filter(Boolean).join(" ");

  // A source is something to read, not a badge. Keep the complete title and
  // passage visible, especially when the parent is using a phone at night.
  const inner = (
    <div className="rounded-xl border border-line bg-surface-2 p-4 text-sm leading-relaxed text-ink transition-colors hover:border-line-control">
      <div className="flex items-start gap-3">
        <span className="ad-ev-tag mt-0.5 shrink-0">{citation.tag}</span>
        <span className="min-w-0 flex-1 break-words font-medium">{citation.title}</span>
        {citation.url && (
          <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-primary-text" strokeWidth={1.8} aria-hidden />
        )}
      </div>
      {attribution && <div className="mt-2 text-xs leading-relaxed text-ink-soft">{attribution}</div>}
      {/* Red flags name a guideline without retrieving a passage. Never show
          empty quotation marks or imply a quotation where there is none. */}
      {citation.snippet?.trim() && (
        <blockquote className="mt-3 border-t border-line pt-3 text-sm leading-relaxed text-ink-soft">
          “{citation.snippet}”
        </blockquote>
      )}
    </div>
  );
  return citation.url ? (
    <a href={citation.url} target="_blank" rel="noopener" className="block rounded-xl">
      {inner}
    </a>
  ) : inner;
}
