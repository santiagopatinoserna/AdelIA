"use client";

import type { EvidenceCitation } from "@/lib/chat-client";

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
    <div className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 hover:bg-amber-100">
      <div className="font-medium">
        📘 {citation.tag} · {citation.title}
      </div>
      {attribution && <div className="text-[10px] text-amber-700">{attribution}</div>}
      <div className="mt-1 line-clamp-2 text-[11px] italic">"{citation.snippet}"</div>
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
