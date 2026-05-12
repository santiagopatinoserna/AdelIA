"use client";
import { CitationCard } from "./citation-card";
import type { ChatMessage, Citation } from "@/lib/chat-client";

export function ChatMessageBubble({
  message,
  locale,
}: {
  message: ChatMessage | { role: "user" | "assistant"; content: string; citations: Citation[] };
  locale: string;
}) {
  const isUser = message.role === "user";
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
          <div className="mt-2 flex flex-wrap gap-1">
            {message.citations.map((c, i) => (
              <CitationCard key={c.chunk_id} citation={c} index={i + 1} locale={locale} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
