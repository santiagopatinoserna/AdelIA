"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import { Bookmark, CalendarCheck, Eye, MessageCircle, Stethoscope } from "lucide-react";
import remarkGfm from "remark-gfm";
import { useTranslations } from "next-intl";

export type AnswerCorpusStats = { sources: number; chunks: number };

// Only a composed answer may claim to draw on sources. Numeric record markers
// are required before mentioning the sample child's history.
export function AnswerSourceContext({ kind, answer, corpusStats }: {
  kind: string;
  answer: string;
  corpusStats?: AnswerCorpusStats;
}) {
  const t = useTranslations("demo");
  if (kind !== "answer") return null;
  return (
    <div data-testid="answer-source-context" className="mt-2 space-y-2 text-sm leading-relaxed text-ink-soft">
      <p>{t(/\[[1-9]\d*\]/.test(answer) ? "sourceContextHistory" : "sourceContextEvidence")}</p>
      <p>{t("sourceContextConsult")}</p>
      {corpusStats && (
        <p data-testid="answer-library-total">
          {t("sourceContextLibrary", {
            sources: corpusStats.sources, chunks: corpusStats.chunks,
          })}
        </p>
      )}
    </div>
  );
}

const markdownComponents: Components = {
  p: ({ node, ...props }) => <p className="whitespace-pre-wrap" {...props} />,
  strong: ({ node, ...props }) => <strong className="font-semibold" {...props} />,
  h1: ({ node, ...props }) => <h3 className="mt-6 text-lg font-semibold leading-snug" {...props} />,
  h2: ({ node, ...props }) => <h3 className="mt-6 text-lg font-semibold leading-snug" {...props} />,
  h3: ({ node, ...props }) => <h4 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  h4: ({ node, ...props }) => <h5 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  h5: ({ node, ...props }) => <h6 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  h6: ({ node, ...props }) => <h6 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  ul: ({ node, ...props }) => <ul className="list-disc space-y-2 pl-6" {...props} />,
  ol: ({ node, ...props }) => <ol className="list-decimal space-y-2 pl-6" {...props} />,
  li: ({ node, ...props }) => <li className="pl-1 [&>p]:my-2" {...props} />,
  a: ({ node, ...props }) => (
    <a className="rounded-sm text-primary-text underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4" {...props} />
  ),
  table: ({ node, ...props }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-base" {...props} />
    </div>
  ),
  th: ({ node, ...props }) => <th className="border border-line px-3 py-2 text-left font-semibold" {...props} />,
  td: ({ node, ...props }) => <td className="border border-line px-3 py-2 text-left" {...props} />,
  pre: ({ node, ...props }) => <pre className="overflow-x-auto whitespace-pre-wrap text-base" {...props} />,
};

function Md({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {children}
    </ReactMarkdown>
  );
}

const PLAN_KEYS = ["today", "watch", "doctor", "remember", "mothers"] as const;
type PlanKey = (typeof PLAN_KEYS)[number];
type PlanSection = { key: PlanKey; title: string; body: string };
const PLAN_ICONS = {
  today: CalendarCheck, watch: Eye, doctor: Stethoscope, remember: Bookmark, mothers: MessageCircle,
};

/*
 * The answer contract asks for an action plan under four exact headings
 * (apps/api/adelia/services/answer_contract.py, PLAN_HEADINGS), plus one
 * optional fifth, "mothers": what other parents report, from the experience
 * tier, placed after the four. Only those exact headings become plan
 * sections; any other text stays Markdown, in order, so nothing the model
 * wrote is dropped or reworded. A thematic break between sections is layout,
 * not content, and is the one thing removed.
 */
export function parsePlan(text: string, titles: Record<PlanKey, string>) {
  const byTitle = new Map(PLAN_KEYS.map((key) => [normalize(titles[key]), key]));
  const lines = text.split("\n");
  const sections: PlanSection[] = [];
  const intro: string[] = [];
  let current: PlanSection | null = null;
  for (const line of lines) {
    const heading = /^#{1,4}\s+(.+?)\s*$/.exec(line);
    const key = heading ? byTitle.get(normalize(heading[1])) : undefined;
    if (key) {
      current = { key, title: titles[key], body: "" };
      sections.push(current);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) continue;
    if (current) current.body += `${line}\n`;
    else intro.push(line);
  }
  return { intro: intro.join("\n").trim(), sections };
}

function normalize(value: string) {
  return value.replace(/[*_:]/g, "").replace(/[’']/g, "'").trim().toLowerCase();
}

const CONTENT_CLASS = "mt-4 max-w-[62ch] space-y-4 break-words text-base leading-[1.7] text-ink [&>:first-child]:mt-0 [&>:last-child]:mb-0";

// Presentation only: never infer clinical sections or rewrite the model's text.
// Like Markdown in chat, use the parser's safe URL transform and no raw-HTML plugin.
// The surrounding answer owns h2, so supplied headings begin at h3.
export function AnswerContent({ children }: { children: string }) {
  const t = useTranslations("demo");
  const titles = Object.fromEntries(PLAN_KEYS.map((key) => [key, t(`plan.${key}`)])) as Record<PlanKey, string>;
  const plan = parsePlan(children, titles);

  if (plan.sections.length === 0) {
    return (
      <div
        data-testid="answer-content"
        className={`${CONTENT_CLASS} [&>p:first-child]:text-lg [&>p:first-child]:font-medium [&>p:first-child]:leading-relaxed`}
      >
        <Md>{children}</Md>
      </div>
    );
  }

  return (
    <div data-testid="answer-content" className={CONTENT_CLASS}>
      {plan.intro && (
        <div data-testid="plan-intro" className="text-lg font-medium leading-relaxed [&>p]:whitespace-pre-wrap">
          <Md>{plan.intro}</Md>
        </div>
      )}
      {plan.sections.map((section) => {
        const Icon = PLAN_ICONS[section.key];
        const urgent = section.key === "doctor";
        // Experience, not evidence: a soft neutral tint and a label that says
        // so, nothing that could be read as a clinical card.
        const mothers = section.key === "mothers";
        return (
          <section
            key={section.key}
            data-testid={`plan-section-${section.key}`}
            className={urgent
              ? "rounded-xl bg-error-tint px-4 py-3 text-ink"
              : mothers
                ? "rounded-xl bg-surface-2 px-4 py-3 text-ink"
                : "border-t border-line pt-4"}
          >
            <h3 className={`flex items-center gap-2 text-base font-semibold leading-snug ${urgent ? "text-error-text" : "text-ink"}`}>
              <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
              {section.title}
            </h3>
            {mothers && (
              <p className="mt-1 text-sm leading-relaxed text-ink-soft">{t("mothersLabel")}</p>
            )}
            <div className="mt-2 space-y-2 [&>:first-child]:mt-0">
              <Md>{section.body.trim()}</Md>
            </div>
          </section>
        );
      })}
    </div>
  );
}
