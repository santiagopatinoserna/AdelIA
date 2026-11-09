"use client";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import type { Citation, EvidenceCitation } from "@/lib/chat-types";
import { CitationCard } from "@/components/citation-card";
import { EvidenceCard } from "@/components/evidence-card";

// The sources of one answer on the panel, as one quiet line that opens
// ("no sé dónde leer", 2026-11-09). They used to sit open under every answer,
// two eyebrow titles and up to a screen of cards between the plan and the next
// question. Nothing is lost: every card is in the DOM, and a citation marker
// in the text opens this line and its card (answer-content revealCiteTarget
// walks up through every <details>).
//
// A red flag's guideline stays open, as on the demo (answer-sources.tsx): no
// reading layer between an urgent referral and its source. The guard marks it
// in the citation itself (clinical/red_flags.citation_for), so the web can
// tell without a `kind` on the agent's final event.
export function AgentSources({
  citations,
  evidence,
  locale,
}: {
  citations: Citation[];
  evidence: EvidenceCitation[];
  locale: string;
}) {
  const t = useTranslations("agent");
  const tp = useTranslations("panel");
  const count = citations.length + evidence.length;
  if (count === 0) return null;
  const urgent = evidence.some((e) => e.source_id?.startsWith("red_flag:"));
  return (
    <details
      data-testid="agent-sources"
      open={urgent || undefined}
      className="group/src mt-5 border-t border-line"
    >
      <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 text-sm text-ink-soft [&::-webkit-details-marker]:hidden">
        <span className="flex-1">{tp("sources", { count })}</span>
        <ChevronDown className="h-4 w-4 shrink-0 group-open/src:rotate-180" strokeWidth={2} aria-hidden />
      </summary>
      <div className="pb-2">
        {citations.length > 0 && (
          <div className="mt-1">
            <p className="text-sm font-medium text-ink">{t("citationSourceUserData")}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {citations.map((c, n) => (
                <CitationCard key={c.chunk_id} citation={c} index={n + 1} locale={locale} />
              ))}
            </div>
          </div>
        )}
        {evidence.length > 0 && (
          <div className={citations.length > 0 ? "mt-4" : "mt-1"}>
            <p className="text-sm font-medium text-ink">{t("citationSourceEvidence")}</p>
            <div className="mt-1.5 flex flex-col">
              {evidence.map((ev) => (
                <EvidenceCard key={ev.tag} citation={ev} />
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}
