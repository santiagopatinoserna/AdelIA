"use client";

import { BookOpen, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { AnswerSourceContext, type AnswerCorpusStats } from "./answer-content";
import { EvidenceCard } from "./evidence-card";
import type { EvidenceCitation } from "@/lib/chat-types";

// Only supporting documents are folded. The generated answer, its conditions,
// warnings and the fixed clinical disclaimer never live inside this disclosure.
export function AnswerSources({ citations, kind, answer, corpusStats }: {
  citations: EvidenceCitation[];
  kind: string;
  answer: string;
  corpusStats?: AnswerCorpusStats;
}) {
  const t = useTranslations("demo");
  if (!citations.length) return null;
  // Scientific sources first, then what other mothers say under its own
  // title, whatever order the payload came in: the experience tier is a layer
  // under the plan, never a peer of a guideline.
  // experience_only never lists a clinical card, whatever the payload says:
  // the title above the answer promised experience and nothing else.
  const evidence = kind === "experience_only" ? [] : citations.filter(c => c.tier !== "experience");
  const experience = citations.filter(c => c.tier === "experience");
  if (!evidence.length && !experience.length) return null;
  const contents = (
    <>
      <AnswerSourceContext kind={kind} answer={answer} corpusStats={corpusStats} />
      <div className="mt-3 flex flex-col">
        {evidence.map(citation => (
          <EvidenceCard key={`${citation.tag}-${citation.chunk_id}`} citation={citation} />
        ))}
      </div>
      {experience.length > 0 && (
        <div data-testid="experience-sources" className="mt-5">
          <h4 className="text-sm font-medium text-ink">{t("sourcesExperienceTitle")}</h4>
          <p className="mt-1 text-sm leading-relaxed text-ink-soft">{t("mothersLabel")}</p>
          <div className="mt-3 flex flex-col">
            {experience.map(citation => (
              <EvidenceCard key={`${citation.tag}-${citation.chunk_id}`} citation={citation} />
            ))}
          </div>
        </div>
      )}
    </>
  );

  // Emergency references remain immediately available; there is no secondary
  // reading layer between the urgent message and its supporting guideline.
  if (kind === "red_flag") return (
    <div className="mt-5">
      <h3 className="text-sm font-medium">{t("sourcesTitle")}</h3>
      {contents}
    </div>
  );
  return (
    <details data-testid="answer-depth" className="group/depth mt-5 border-y border-line">
      <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 py-3 text-left [&::-webkit-details-marker]:hidden">
        <BookOpen className="h-5 w-5 shrink-0 text-primary-text" strokeWidth={1.7} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-base font-medium text-ink">{t(kind === "experience_only" ? "readMoreTitleExperience" : "readMoreTitle")}</span>
          <span className="mt-0.5 block text-sm text-ink-soft">{t("readMoreSources", { count: citations.length })}</span>
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink-soft group-open/depth:rotate-180" aria-hidden />
      </summary>
      <div className="pb-4">{contents}</div>
    </details>
  );
}
