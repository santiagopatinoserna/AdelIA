"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Render assistant answers as real markdown (bold, lists, headings, tables)
// instead of literal "**asterisks**". Raw HTML is NOT enabled (react-markdown
// default), so there is no XSS surface from model output. Every element is
// mapped to the clinical-warmth tokens; `node` is dropped so it never leaks to
// the DOM. Partial/streaming markdown renders gracefully (react-markdown parses
// what it has on each token).
export function Markdown({ children }: { children: string }) {
  return (
    <div className="space-y-2.5 leading-relaxed [&_:first-child]:mt-0 [&_:last-child]:mb-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ node, ...p }) => <p className="leading-relaxed" {...p} />,
          strong: ({ node, ...p }) => <strong className="font-semibold text-ink" {...p} />,
          em: ({ node, ...p }) => <em className="italic" {...p} />,
          a: ({ node, ...p }) => (
            <a
              className="font-medium text-pine-600 underline decoration-pine-200 underline-offset-2 hover:text-pine-700"
              target="_blank"
              rel="noopener noreferrer"
              {...p}
            />
          ),
          ul: ({ node, ...p }) => <ul className="list-disc space-y-1 pl-5 marker:text-pine-400" {...p} />,
          ol: ({ node, ...p }) => <ol className="list-decimal space-y-1 pl-5 marker:text-pine-400 marker:font-medium" {...p} />,
          li: ({ node, ...p }) => <li className="leading-relaxed [&>p]:my-0" {...p} />,
          h1: ({ node, ...p }) => <h1 className="text-[1.05rem] font-semibold text-pine-900" {...p} />,
          h2: ({ node, ...p }) => <h2 className="text-[1rem] font-semibold text-pine-900" {...p} />,
          h3: ({ node, ...p }) => <h3 className="text-[0.95rem] font-semibold text-pine-800" {...p} />,
          blockquote: ({ node, ...p }) => (
            <blockquote className="border-l-2 border-pine-200 pl-3 italic text-ink-soft" {...p} />
          ),
          code: ({ node, ...p }) => (
            <code className="rounded bg-pine-50 px-1 py-0.5 font-mono text-[0.85em] text-pine-700" {...p} />
          ),
          pre: ({ node, ...p }) => (
            <pre
              className="overflow-x-auto rounded-lg bg-pine-900 p-3 text-xs text-pine-50 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-pine-50"
              {...p}
            />
          ),
          hr: ({ node, ...p }) => <hr className="border-line" {...p} />,
          table: ({ node, ...p }) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[0.85em]" {...p} />
            </div>
          ),
          th: ({ node, ...p }) => <th className="border border-line bg-surface-2 px-2 py-1 text-left font-semibold" {...p} />,
          td: ({ node, ...p }) => <td className="border border-line px-2 py-1" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
