"use client";

import { useId } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { Bookmark, CalendarCheck, Eye, MessageCircle, Stethoscope } from "lucide-react";
import remarkGfm from "remark-gfm";
import { useTranslations } from "next-intl";

// A remark plugin that wraps the literal citation markers of an answer,
// [ev_N], [ex_N] and [N], in <span class="ad-cite">. The text is untouched,
// character for character: the marker is still there to read and to verify
// (UX_PRINCIPLES 11), it just stops weighing what the sentence weighs.
// mdast-util-to-hast turns a node's data.hName into the element it emits, so
// no raw HTML is involved and the markdown stays inert. It lives in this file,
// not in lib/, because answer-reading.spec.ts compiles this module with a
// plain require that does not know the @/ alias.
type MdNode = {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: Record<string, unknown>;
};

const MARKER = /(\[(?:ev_\d+|ex_\d+|\d+)\])/;

function split(value: string): MdNode[] {
  return value
    .split(MARKER)
    .filter((part) => part !== "")
    .map((part) =>
      MARKER.test(part)
        ? { type: "text", value: part, data: { hName: "span", hProperties: { className: ["ad-cite"] } } }
        : { type: "text", value: part },
    );
}

function walk(node: MdNode) {
  if (!node.children) return;
  const children: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value && MARKER.test(child.value)) {
      children.push(...split(child.value));
    } else {
      walk(child);
      children.push(child);
    }
  }
  node.children = children;
}

export function remarkCiteMarkers() {
  return (tree: MdNode) => walk(tree);
}

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
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkCiteMarkers]} components={markdownComponents}>
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

const CONTENT_CLASS = "mt-4 max-w-[62ch] break-words text-answer text-ink [&>:first-child]:mt-0 [&>:last-child]:mb-0";

// Section looks (docs/design/REDISENO.md). "Hoy" is what to do now: a honey
// rule. "Cuándo ir al médico" is visible and distinct but calm: a clay rule
// on a soft tint, its heading in the error text colour; the full error fill
// is kept for the emergency. "Lo que cuentan otras madres" is experience,
// not evidence: a neutral tint and a label that says so.
const SECTION_CLASS: Record<PlanKey, string> = {
  today: "border-l-[3px] border-today-line pl-4",
  watch: "",
  doctor: "rounded-r-2xl border-l-[3px] border-doctor-line bg-doctor-tint py-3 pl-4 pr-4",
  remember: "",
  mothers: "rounded-xl bg-surface-2 px-4 py-3",
};

// Presentation only: never infer clinical sections or rewrite the model's text.
// Like Markdown in chat, use the parser's safe URL transform and no raw-HTML plugin.
// The surrounding answer owns h2, so supplied headings begin at h3.
export function AnswerContent({ children }: { children: string }) {
  const t = useTranslations("demo");
  const uid = useId();
  const titles = Object.fromEntries(PLAN_KEYS.map((key) => [key, t(`plan.${key}`)])) as Record<PlanKey, string>;
  const plan = parsePlan(children, titles);

  if (plan.sections.length === 0) {
    return (
      <div
        data-testid="answer-content"
        className={`${CONTENT_CLASS} space-y-4 [&>p:first-child]:text-lead [&>p:first-child]:font-medium`}
      >
        <Md>{children}</Md>
      </div>
    );
  }

  const sectionId = (key: PlanKey) => `${uid}-plan-${key}`;
  // The map of the plan: one tap to "Cuándo ir al médico" instead of 1.6 to
  // 1.9 screens of scrolling (AUDITORIA_UX.md, problem 3). It hides nothing:
  // every section stays open below it. Only the clinical sections are listed;
  // what other mothers say is for later and sits last anyway.
  const mapped = plan.sections.filter((section) => section.key !== "mothers");
  function jump(key: PlanKey) {
    const target = document.getElementById(sectionId(key));
    if (!target) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    target.querySelector<HTMLElement>("h3")?.focus({ preventScroll: true });
  }

  return (
    <div data-testid="answer-content" className={`${CONTENT_CLASS} space-y-6`}>
      {plan.intro && (
        <div data-testid="plan-intro" className="text-lead font-medium [&>p]:whitespace-pre-wrap">
          <Md>{plan.intro}</Md>
        </div>
      )}
      {mapped.length > 1 && (
        <nav aria-label={t("planMap")} data-testid="plan-map" className="-mt-2 flex flex-wrap gap-2">
          {mapped.map((section) => (
            <button
              key={section.key}
              type="button"
              onClick={() => jump(section.key)}
              className={`ad-pill ${section.key === "doctor" ? "!border-doctor-line text-error-text" : ""}`}
            >
              {section.title}
            </button>
          ))}
        </nav>
      )}
      {plan.sections.map((section) => {
        const Icon = PLAN_ICONS[section.key];
        const doctor = section.key === "doctor";
        const mothers = section.key === "mothers";
        return (
          <section
            key={section.key}
            id={sectionId(section.key)}
            data-testid={`plan-section-${section.key}`}
            className={`scroll-mt-4 text-ink ${SECTION_CLASS[section.key]}`}
          >
            <h3
              tabIndex={-1}
              className={`flex items-center gap-2 text-lg font-semibold leading-snug ${doctor ? "text-error-text" : "text-ink"}`}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={2} aria-hidden />
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
