"use client";

import { ExternalLink } from "lucide-react";
import type { EvidenceCitation } from "@/lib/chat-types";

export function EvidenceCard({
  citation,
}: {
  citation: EvidenceCitation;
}) {
  const attribution = [
    citation.organization,
    citation.year ? `(${citation.year})` : null,
  ]
    .filter(Boolean)
    .join(" ");
  const Inner = (
    <div className="rounded-lg border border-accent-tint-line bg-accent-tint/60 p-2.5 text-xs text-ink transition-colors hover:bg-accent-tint">
      <div className="flex items-center gap-1.5 font-medium">
        <span className="ad-ev-tag">
          {citation.tag}
        </span>
        <span className="min-w-0 flex-1 truncate">{citation.title}</span>
        {citation.url && <ExternalLink className="h-3 w-3 shrink-0 text-accent-text" strokeWidth={2} />}
      </div>
      {attribution && <div className="mt-0.5 text-[10px] text-ink-soft">{attribution}</div>}
      <div className="mt-1 line-clamp-2 text-[11px] italic text-ink-soft">“{citation.snippet}”</div>
    </div>
  );
  if (citation.url) {
    return (
      <a href={citation.url} target="_blank" rel="noopener" className="block">
        {Inner}
      </a>
    );
  }
  return Inner;
}
