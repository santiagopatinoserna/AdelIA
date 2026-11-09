"use client";

import { useId, type KeyboardEvent, type MouseEvent } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { ChevronDown } from "lucide-react";
import remarkGfm from "remark-gfm";
import { useTranslations } from "next-intl";

// A remark plugin that turns the citation markers of an answer, [ev_N],
// [ex_N] and [N], into a small number: the number printed on its source card
// (evidence, or what other mothers say) or on its record in her history,
// drawn differently. A mother read "limpia y seca [ev_1][ev_2]" as programmer
// text in production (prod journey 2026-11-06).
// The model's text is untouched, character for character: the marker stays in
// the DOM inside a hidden span and the number is drawn from data-n by CSS, so
// the text still reads and verifies as the model wrote it (UX_PRINCIPLES 11)
// and nothing clinical changes. A marker whose card is on the page acts as a
// button that takes her there; its name is "Fuente 1" or "Historial 2". It is
// a span with role="button", not a <button>: under the answer a visible
// <button> in a list means a suggestion came back (mother-first-answer.spec),
// and markers sit in list items.
// mdast-util-to-hast turns a node's data.hName/hProperties/hChildren into the
// element it emits, so no raw HTML is involved and the markdown stays inert.
// It lives in this file, not in lib/, because answer-reading.spec.ts and
// citation-plugin.spec.ts compile this module with a plain require that does
// not know the @/ alias.
type MdNode = {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: Record<string, unknown>;
};

const MARKER = /(\[(?:ev_\d+|ex_\d+|\d+)\])/;

export type CiteOptions = {
  // Spoken before the number: "Fuente" for a source, "Historial" for a record.
  labels: { source: string; record: string };
  // Whether the record cards ([N]) are on the page. The demo has none: its
  // history is the sample child's and has no card per record.
  recordLinks?: boolean;
};

// "[ev_2]" -> ev_2 / 2, "[3]" -> rec_3 / 3. `key` is the card's data-cite-target.
export function parseMarker(marker: string) {
  const inner = marker.slice(1, -1);
  const kind = inner.startsWith("ev_") ? "ev" : inner.startsWith("ex_") ? "ex" : "rec";
  const n = inner.replace(/^e[vx]_/, "");
  return { inner, kind, n, key: kind === "rec" ? `rec_${n}` : inner } as const;
}

function citeNode(marker: string, options: CiteOptions, linked: boolean): MdNode {
  const { inner, kind, n } = parseMarker(marker);
  const label = `${kind === "rec" ? options.labels.record : options.labels.source} ${n}`;
  const button = linked && (kind !== "rec" || options.recordLinks === true);
  return {
    type: "citeMarker",
    data: {
      hName: "span",
      hProperties: {
        className: ["ad-cite", `ad-cite-${kind}`],
        dataCite: inner,
        dataN: n,
        ariaLabel: label,
        // A span is not announced by its aria-label unless it has a role.
        ...(button ? { role: "button", tabIndex: 0 } : { role: "img" }),
      },
      hChildren: [{
        type: "element", tagName: "span",
        properties: { className: ["ad-cite-raw"] },
        children: [{ type: "text", value: marker }],
      }],
    },
  };
}

function split(value: string, options: CiteOptions, linked: boolean): MdNode[] {
  return value
    .split(MARKER)
    .filter((part) => part !== "")
    .map((part) => (MARKER.test(part) ? citeNode(part, options, linked) : { type: "text", value: part }));
}

// Inside a Markdown link a button would be a control within a control: the
// marker is drawn the same but stays inert there.
function walk(node: MdNode, options: CiteOptions, linked: boolean) {
  if (!node.children) return;
  const children: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value && MARKER.test(child.value)) {
      children.push(...split(child.value, options, linked));
    } else {
      walk(child, options, linked && child.type !== "link" && child.type !== "linkReference");
      children.push(child);
    }
  }
  node.children = children;
}

const DEFAULT_CITE_OPTIONS: CiteOptions = { labels: { source: "Source", record: "Record" } };

export function remarkCiteMarkers(options: CiteOptions = DEFAULT_CITE_OPTIONS) {
  return (tree: MdNode) => walk(tree, options, true);
}

// The card a marker points to is the first one with its key AFTER this answer
// and before the next answer: in a thread, every answer is followed by its
// own cards, and an earlier answer may carry the same ev_1.
export function findCiteTarget(root: HTMLElement, key: string): HTMLElement | null {
  const answers = Array.from(document.querySelectorAll<HTMLElement>("[data-testid='answer-content']"));
  const next = answers[answers.indexOf(root) + 1] ?? null;
  for (const el of document.querySelectorAll<HTMLElement>(`[data-cite-target="${CSS.escape(key)}"]`)) {
    if (!(root.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    if (next && !(el.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    return el;
  }
  return null;
}

// Open the list of sources and the card itself if they are folded, bring the
// card into view and move focus to it, so a keyboard or screen reader user
// lands where a finger would.
export function revealCiteTarget(target: HTMLElement) {
  for (let el: HTMLElement | null = target; el; el = el.parentElement) {
    if (el instanceof HTMLDetailsElement) el.open = true;
  }
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  const focusable = target instanceof HTMLDetailsElement
    ? target.querySelector<HTMLElement>(":scope > summary")
    : target.matches("a[href], button") ? target : target.querySelector<HTMLElement>("a[href], button");
  focusable?.focus({ preventScroll: true });
}

function onCite(event: MouseEvent<HTMLElement> | KeyboardEvent<HTMLElement>) {
  const cite = (event.target as HTMLElement).closest<HTMLElement>('[data-cite][role="button"]');
  if (!cite) return;
  // Enter and Space, as on a native button; Space must not scroll the page.
  if ("key" in event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
  }
  const target = findCiteTarget(event.currentTarget, parseMarker(`[${cite.dataset.cite}]`).key);
  if (target) revealCiteTarget(target);
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

// The same map one level up, for a page whose only heading above the answer
// is its h1 (the chat, the agent once the thread has started): there the
// answer's own headings start at h2, or axe reports a skipped level.
const markdownComponentsH2: Components = {
  ...markdownComponents,
  h1: ({ node, ...props }) => <h2 className="mt-6 text-lg font-semibold leading-snug" {...props} />,
  h2: ({ node, ...props }) => <h2 className="mt-6 text-lg font-semibold leading-snug" {...props} />,
  h3: ({ node, ...props }) => <h3 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  h4: ({ node, ...props }) => <h4 className="mt-5 text-base font-semibold leading-snug" {...props} />,
  h5: ({ node, ...props }) => <h5 className="mt-5 text-base font-semibold leading-snug" {...props} />,
};

function Md({ children, level = 3, cites }: { children: string; level?: 2 | 3; cites: CiteOptions }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, [remarkCiteMarkers, cites]]}
      components={level === 2 ? markdownComponentsH2 : markdownComponents}
    >
      {children}
    </ReactMarkdown>
  );
}

const PLAN_KEYS = ["today", "watch", "doctor", "remember", "mothers"] as const;
type PlanKey = (typeof PLAN_KEYS)[number];
type PlanSection = { key: PlanKey; title: string; body: string };

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
// No icon on any title (2026-11-09, "no sé dónde leer"): five pictograms beside
// five words added a second thing to read per section. The titles are the
// sans of the body, so the only serif on the panel stays its greeting.
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
// `level` is where the answer's headings start: 3 under a page that titles
// the answer with an h2 (the demo), 2 where the page has only its h1.
// `recordLinks`: the page renders a card per record ([N]) after the answer.
export function AnswerContent({ children, level = 3, recordLinks = false }: {
  children: string;
  level?: 2 | 3;
  recordLinks?: boolean;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  const t = useTranslations("demo");
  const tp = useTranslations("panel");
  const tAll = useTranslations();
  // Existing words on purpose: the three catalogs are being edited elsewhere.
  const cites: CiteOptions = {
    labels: { source: tAll("questionnaire.sourceLabel"), record: tAll("dashboard.navHistory") },
    recordLinks,
  };
  const uid = useId();
  const titles = Object.fromEntries(PLAN_KEYS.map((key) => [key, t(`plan.${key}`)])) as Record<PlanKey, string>;
  const plan = parsePlan(children, titles);

  if (plan.sections.length === 0) {
    return (
      <div
        data-testid="answer-content"
        onClick={onCite}
        onKeyDown={onCite}
        className={`${CONTENT_CLASS} space-y-4 [&>p:first-child]:text-lead [&>p:first-child]:font-medium`}
      >
        <Md level={level} cites={cites}>{children}</Md>
      </div>
    );
  }

  const sectionId = (key: PlanKey) => `${uid}-plan-${key}`;
  // The map of the plan: one tap to "Cuándo ir al médico" instead of 1.6 to
  // 1.9 screens of scrolling (AUDITORIA_UX.md, problem 3). It hides nothing:
  // every section stays open below it. Since 2026-11-09 it is that one jump
  // and no more ("no sé dónde leer"): "Hoy" follows the opening directly and
  // "Vigila" follows "Hoy", so four pills on two rows only stood between her
  // and what to do. UX_PRINCIPLES 12 asked for the whole map; the mother's
  // complaint wins, and the jump that matters for safety stays.
  const doctorAt = plan.sections.findIndex((section) => section.key === "doctor");
  const mapped = doctorAt > 0 ? [plan.sections[doctorAt]] : [];
  // What other mothers say is apart and folded when it follows a plan; it is
  // experience, never evidence, and it is the one part of an answer she can
  // leave for later. Its title and label stay visible, so she knows it is
  // there and what it is. When it IS the answer (experience_only) it is open.
  const foldMothers = plan.sections.some((section) => section.key !== "mothers");
  function jump(key: PlanKey) {
    const target = document.getElementById(sectionId(key));
    if (!target) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    target.querySelector<HTMLElement>(Heading)?.focus({ preventScroll: true });
  }

  return (
    <div data-testid="answer-content" onClick={onCite} onKeyDown={onCite} className={`${CONTENT_CLASS} space-y-8`}>
      {plan.intro && (
        <div data-testid="plan-intro" className="text-lead font-medium [&>p]:whitespace-pre-wrap">
          <Md level={level} cites={cites}>{plan.intro}</Md>
        </div>
      )}
      {mapped.length > 0 && (
        <nav aria-label={t("planMap")} data-testid="plan-map" className="-mt-4 flex flex-wrap gap-2">
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
        const doctor = section.key === "doctor";
        const mothers = section.key === "mothers";
        const body = (
          <div className="mt-2 space-y-2 [&>:first-child]:mt-0">
            <Md level={level} cites={cites}>{section.body.trim()}</Md>
          </div>
        );
        return (
          <section
            key={section.key}
            id={sectionId(section.key)}
            data-testid={`plan-section-${section.key}`}
            className={`scroll-mt-4 text-ink ${SECTION_CLASS[section.key]}`}
          >
            <Heading
              tabIndex={-1}
              className={`font-sans text-lg font-semibold leading-snug ${doctor ? "text-error-text" : "text-ink"}`}
            >
              {section.title}
            </Heading>
            {mothers && (
              <p className="mt-1 text-sm leading-relaxed text-ink-soft">{t("mothersLabel")}</p>
            )}
            {mothers && foldMothers ? (
              <details data-testid="mothers-fold" className="group/mothers mt-1">
                <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 text-sm font-medium text-primary-text [&::-webkit-details-marker]:hidden">
                  {tp("mothersOpen")}
                  <ChevronDown className="h-4 w-4 shrink-0 group-open/mothers:rotate-180" strokeWidth={2} aria-hidden />
                </summary>
                {body}
              </details>
            ) : body}
          </section>
        );
      })}
    </div>
  );
}
