"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { CitationCard } from "./citation-card";
import { EvidenceCard } from "./evidence-card";
import { AnswerContent } from "./answer-content";
import { Database, BookMarked, Copy, Check } from "lucide-react";
import type { ChatMessage, Citation, EvidenceCitation } from "@/lib/chat-types";

export function ChatMessageBubble({
  message,
  locale,
}: {
  message:
    | ChatMessage
    | {
        role: "user" | "assistant";
        content: string;
        citations: Citation[];
        evidence_citations?: EvidenceCitation[];
      };
  locale: string;
}) {
  const t = useTranslations("chat");
  const isUser = message.role === "user";
  const evidence = message.evidence_citations ?? [];
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      {/* Her question is a bubble; the answer is a page to read, at full
          width, rendered like the demo's (plan sections and map, quiet
          citation markers), not squeezed into an 80 % bubble at 14 px. */}
      <div
        className={isUser
          ? "max-w-[85%] rounded-2xl rounded-br-md bg-primary-tint px-4 py-2.5 text-base text-ink"
          : "w-full min-w-0 text-ink [&_[data-testid=answer-content]]:mt-0"}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words leading-relaxed">{message.content}</p>
        ) : message.content.trim() ? (
          <AnswerContent level={2} recordLinks={message.citations.length > 0}>
            {message.content}
          </AnswerContent>
        ) : (
          <span className="flex items-center gap-1 py-1" role="status" aria-label="…">
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-primary-text" />
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-primary-text" style={{ animationDelay: "150ms" }} />
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-primary-text" style={{ animationDelay: "300ms" }} />
          </span>
        )}
        {!isUser && message.citations.length > 0 && (
          <div className="mt-3 border-t border-line pt-3">
            <div className="ad-eyebrow flex items-center gap-1.5">
              <Database className="h-3 w-3" strokeWidth={2.4} />
              {t("citationSourceUserData")}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {message.citations.map((c, i) => (
                <CitationCard key={c.chunk_id} citation={c} index={i + 1} locale={locale} />
              ))}
            </div>
          </div>
        )}
        {!isUser && evidence.length > 0 && (
          <div className="mt-3 border-t border-line pt-3">
            <div className="ad-eyebrow flex items-center gap-1.5 !text-accent-text">
              <BookMarked className="h-3 w-3" strokeWidth={2.4} />
              {t("citationSourceEvidence")}
            </div>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {evidence.map((ev) => (
                <EvidenceCard key={ev.tag} citation={ev} />
              ))}
            </div>
          </div>
        )}
        {!isUser && message.content.trim() && (
          <button
            type="button"
            onClick={copy}
            className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-sm text-ink-soft transition-colors hover:text-primary-text-hover"
          >
            {copied ? (
              <Check className="h-4 w-4 text-primary-text" strokeWidth={2.4} />
            ) : (
              <Copy className="h-4 w-4" strokeWidth={2} />
            )}
            {copied ? t("copied") : t("copy")}
          </button>
        )}
      </div>
    </div>
  );
}
