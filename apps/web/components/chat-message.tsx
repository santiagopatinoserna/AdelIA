"use client";
import { CitationCard } from "./citation-card";
import { EvidenceCard } from "./evidence-card";
import { Markdown } from "./markdown";
import { Database, BookMarked } from "lucide-react";
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
  const isUser = message.role === "user";
  const evidence = message.evidence_citations ?? [];
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] px-4 py-3 text-sm shadow-soft ${
          isUser
            ? "rounded-2xl rounded-br-md bg-gradient-to-b from-pine-600 to-pine-700 text-[#eef3ee]"
            : "rounded-2xl rounded-bl-md border border-line bg-surface text-ink"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        ) : message.content.trim() ? (
          <Markdown>{message.content}</Markdown>
        ) : (
          <span className="flex items-center gap-1 py-1" role="status" aria-label="…">
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-pine-400" />
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-pine-400" style={{ animationDelay: "150ms" }} />
            <span className="ad-typing-dot h-1.5 w-1.5 rounded-full bg-pine-400" style={{ animationDelay: "300ms" }} />
          </span>
        )}
        {!isUser && message.citations.length > 0 && (
          <div className="mt-3 border-t border-line pt-3">
            <div className="ad-eyebrow flex items-center gap-1.5">
              <Database className="h-3 w-3" strokeWidth={2.4} />
              {"Tu data"}
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
            <div className="ad-eyebrow flex items-center gap-1.5 !text-honey-600">
              <BookMarked className="h-3 w-3" strokeWidth={2.4} />
              {"Evidencia clínica"}
            </div>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {evidence.map((ev) => (
                <EvidenceCard key={ev.tag} citation={ev} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
