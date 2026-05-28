"use client";
import { CitationCard } from "./citation-card";
import { EvidenceCard } from "./evidence-card";
import type { ChatMessage, Citation, EvidenceCitation } from "@/lib/chat-client";

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
        className={`max-w-[80%] rounded-lg px-4 py-3 text-sm ${
          isUser
            ? "bg-slate-900 text-white"
            : "bg-white border border-slate-200 text-slate-800"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {!isUser && message.citations.length > 0 && (
          <div className="mt-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">
              🟡 Tu data
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {message.citations.map((c, i) => (
                <CitationCard key={c.chunk_id} citation={c} index={i + 1} locale={locale} />
              ))}
            </div>
          </div>
        )}
        {!isUser && evidence.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] uppercase tracking-wide text-amber-700">
              📘 Evidencia clínica
            </div>
            <div className="mt-1 flex flex-col gap-1">
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
