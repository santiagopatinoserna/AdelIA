"use client";

import ReactMarkdown from "react-markdown";
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

// Presentation only: never infer clinical sections or rewrite the model's text.
// Like Markdown in chat, use the parser's safe URL transform and no raw-HTML plugin.
// The surrounding answer owns h2, so supplied headings begin at h3.
export function AnswerContent({ children }: { children: string }) {
  return (
    <div
      data-testid="answer-content"
      className="mt-4 max-w-[62ch] space-y-4 break-words text-base leading-[1.7] text-ink [&>:first-child]:mt-0 [&>:last-child]:mb-0 [&>p:first-child]:text-lg [&>p:first-child]:font-medium [&>p:first-child]:leading-relaxed"
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
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
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
