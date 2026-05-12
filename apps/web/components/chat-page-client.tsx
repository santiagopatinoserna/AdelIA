"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ChatSession,
  type Citation,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  streamChat,
} from "@/lib/chat-client";
import { ChatSessionsSidebar } from "./chat-sessions-sidebar";
import { ChatMessageBubble } from "./chat-message";
import { ChatInput } from "./chat-input";

type LocalMsg = {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
};

export function ChatPageClient({
  initialSessions,
  jwt,
  locale,
  titleText,
}: {
  initialSessions: ChatSession[];
  jwt: string;
  locale: string;
  titleText: string;
}) {
  const [sessions, setSessions] = useState<ChatSession[]>(initialSessions);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const loadSession = useCallback(async (id: string) => {
    setActiveId(id);
    const detail = await getChatSession(id);
    setMessages(
      detail.messages.map((m) => ({
        role: m.role,
        content: m.content,
        citations: m.citations,
      }))
    );
  }, []);

  const newSession = useCallback(() => {
    setActiveId(null);
    setMessages([]);
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    await deleteChatSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setMessages([]);
    }
  }, [activeId]);

  const handleSubmit = useCallback(async (text: string) => {
    setBusy(true);
    const userMsg: LocalMsg = { role: "user", content: text, citations: [] };
    setMessages((prev) => [...prev, userMsg, { role: "assistant", content: "", citations: [] }]);
    try {
      let createdSessionId: string | null = null;
      for await (const event of streamChat(jwt, text, activeId)) {
        if (event.type === "start") {
          createdSessionId = event.session_id;
        } else if (event.type === "token") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: last.content + event.content };
            }
            return updated;
          });
        } else if (event.type === "final") {
          createdSessionId = createdSessionId ?? event.session_id;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, citations: event.citations };
            }
            return updated;
          });
        } else if (event.type === "error") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: `Error: ${event.content}` };
            }
            return updated;
          });
        }
      }
      if (createdSessionId && !activeId) {
        setActiveId(createdSessionId);
        const refreshed = await listChatSessions().catch(() => sessions);
        setSessions(refreshed);
      }
    } catch (e) {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last.role === "assistant" && !last.content) {
          updated[updated.length - 1] = { ...last, content: `Error: ${String(e)}` };
        }
        return updated;
      });
    } finally {
      setBusy(false);
    }
  }, [activeId, jwt, sessions]);

  return (
    <div className="flex w-full">
      <ChatSessionsSidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={loadSession}
        onNew={newSession}
        onDelete={handleDelete}
      />
      <section className="flex flex-1 flex-col">
        <header className="border-b border-slate-200 bg-white px-6 py-4">
          <h1 className="text-base font-semibold">{titleText}</h1>
        </header>
        <div ref={scrollRef} className="flex-1 overflow-y-auto bg-slate-50 px-6 py-6">
          <div className="mx-auto max-w-3xl space-y-3">
            {messages.map((m, i) => (
              <ChatMessageBubble key={i} message={m} locale={locale} />
            ))}
          </div>
        </div>
        <ChatInput onSubmit={handleSubmit} disabled={busy} />
      </section>
    </div>
  );
}
