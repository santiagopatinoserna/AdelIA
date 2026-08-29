"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Menu, Stethoscope, Sparkles, ArrowUpRight, ArrowDown, UploadCloud, FileText } from "lucide-react";
import { Link } from "@/lib/navigation";
import {
  type ChatSession,
  type Citation,
  type EvidenceCitation,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  streamChat,
} from "@/lib/chat-client-browser";
import { ChatSessionsSidebar } from "./chat-sessions-sidebar";
import { ChatMessageBubble } from "./chat-message";
import { ChatInput } from "./chat-input";

type LocalMsg = {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  evidence_citations: EvidenceCitation[];
};

export function ChatPageClient({
  initialSessions,
  locale,
  titleText,
  hasDocs,
  initialQuestion,
}: {
  initialSessions: ChatSession[];
  locale: string;
  titleText: string;
  hasDocs: boolean;
  // A question handed over in the URL (?q=...), e.g. by the capability
  // showcase: sent once on mount as if the user had typed it.
  initialQuestion?: string;
}) {
  const t = useTranslations("chat");
  const [sessions, setSessions] = useState<ChatSession[]>(initialSessions);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // The handed-over question fires exactly once, whatever re-renders or
  // prop changes follow (strict-mode double effects included).
  const autoSentRef = useRef(false);
  // Increments whenever the visible conversation changes; in-flight stream
  // events from a previous epoch are dropped instead of appending tokens
  // to another session's history (or crashing on an empty list).
  const streamEpochRef = useRef(0);
  // Aborts the in-flight stream when the user presses Stop.
  const abortRef = useRef<AbortController | null>(null);

  const [atBottom, setAtBottom] = useState(true);

  // Only follow new content when the user is already near the bottom — don't
  // yank them down while they're reading earlier messages.
  useEffect(() => {
    if (atBottom) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, busy, atBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }

  function scrollToBottom() {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }

  const loadSession = useCallback(async (id: string) => {
    streamEpochRef.current += 1;
    setActiveId(id);
    const detail = await getChatSession(id);
    setMessages(
      detail.messages.map((m) => ({
        role: m.role,
        content: m.content,
        citations: m.citations,
        evidence_citations: m.evidence_citations ?? [],
      }))
    );
  }, []);

  const newSession = useCallback(() => {
    streamEpochRef.current += 1;
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
    const epoch = streamEpochRef.current;
    const stale = () => streamEpochRef.current !== epoch;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    const userMsg: LocalMsg = { role: "user", content: text, citations: [], evidence_citations: [] };
    setMessages((prev) => [
      ...prev,
      userMsg,
      { role: "assistant", content: "", citations: [], evidence_citations: [] },
    ]);
    try {
      let createdSessionId: string | null = null;
      for await (const event of streamChat(text, activeId, locale, controller.signal)) {
        if (stale()) break;
        if (event.type === "start") {
          createdSessionId = event.session_id;
        } else if (event.type === "token") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: last.content + event.content };
            }
            return updated;
          });
        } else if (event.type === "final") {
          createdSessionId = createdSessionId ?? event.session_id;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                citations: event.citations,
                evidence_citations: event.evidence_citations,
              };
            }
            return updated;
          });
        } else if (event.type === "error") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: t("errorAnswer") };
            }
            return updated;
          });
        }
      }
      if (createdSessionId && !activeId && !stale()) {
        setActiveId(createdSessionId);
        const refreshed = await listChatSessions().catch(() => sessions);
        setSessions(refreshed);
      }
    } catch (e) {
      // User switched sessions or pressed Stop — keep the partial answer, no error.
      if (stale() || controller.signal.aborted) return;
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant" && !last.content) {
          updated[updated.length - 1] = { ...last, content: t("errorAnswer") };
        }
        return updated;
      });
    } finally {
      setBusy(false);
    }
  }, [activeId, locale, sessions]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  // Question handed over in the URL: strip it first (a reload or a shared
  // link must not re-send it and open yet another session), then send it.
  useEffect(() => {
    if (!initialQuestion || autoSentRef.current) return;
    autoSentRef.current = true;
    try {
      window.history.replaceState(window.history.state, "", window.location.pathname);
    } catch {
      /* history blocked: the question still goes out, the URL just keeps it */
    }
    void handleSubmit(initialQuestion);
  }, [initialQuestion, handleSubmit]);

  return (
    <div className="flex w-full">
      <ChatSessionsSidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={(id) => { loadSession(id); setSidebarOpen(false); }}
        onNew={() => { newSession(); setSidebarOpen(false); }}
        onDelete={handleDelete}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <section className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-surface/80 px-4 py-3.5 backdrop-blur-md md:px-6">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label={t("openSessions")}
            className="ad-btn ad-btn-ghost h-9 w-9 p-0 md:hidden"
          >
            <Menu className="h-4 w-4" strokeWidth={2.2} />
          </button>
          <h1 className="text-lg text-pine-900">{titleText}</h1>
        </header>
        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
          <div className="mx-auto max-w-3xl">
            {messages.length === 0 && !hasDocs ? (
              <div className="ad-rise mx-auto mt-10 max-w-md text-center md:mt-16">
                <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-50 text-pine-500 ring-1 ring-pine-100">
                  <FileText className="h-7 w-7" strokeWidth={1.8} />
                </span>
                <h2 className="mt-5 font-display text-2xl text-pine-900">{t("noDocTitle")}</h2>
                <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">{t("noDocBody")}</p>
                <Link
                  href="/dashboard/upload"
                  className="ad-btn ad-btn-primary mt-6 inline-flex px-5 py-3 text-sm"
                >
                  <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
                  {t("noDocCta")}
                </Link>
              </div>
            ) : messages.length === 0 ? (
              <div className="ad-rise mx-auto mt-10 max-w-xl text-center md:mt-16">
                <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-50 text-pine-500 ring-1 ring-pine-100">
                  <Stethoscope className="h-7 w-7" strokeWidth={1.8} />
                </span>
                <h2 className="mt-5 font-display text-2xl text-pine-900">{t("emptyTitle")}</h2>
                <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">{t("emptySubtitle")}</p>
                <div className="mt-7 flex flex-col gap-2">
                  {[t("example1"), t("example2"), t("example3")].map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => handleSubmit(ex)}
                      disabled={busy}
                      className="ad-card ad-card-hover group flex items-center gap-3 px-4 py-3 text-left text-sm text-ink disabled:opacity-60"
                    >
                      <Sparkles className="h-4 w-4 shrink-0 text-honey-500" strokeWidth={2} />
                      <span className="flex-1">{ex}</span>
                      <ArrowUpRight className="h-4 w-4 shrink-0 text-ink-faint transition-colors group-hover:text-pine-500" strokeWidth={2} />
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {messages.map((m, i) => (
                  <ChatMessageBubble key={i} message={m} locale={locale} />
                ))}
              </div>
            )}
          </div>
        </div>
        {!atBottom && messages.length > 0 && (
          <button
            type="button"
            onClick={scrollToBottom}
            aria-label={t("scrollToLatest")}
            className="absolute bottom-24 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-pine-600 shadow-lift transition-colors hover:bg-pine-50 md:right-8"
          >
            <ArrowDown className="h-4 w-4" strokeWidth={2.2} />
          </button>
        )}
        <ChatInput onSubmit={handleSubmit} disabled={busy} onStop={stop} />
      </section>
    </div>
  );
}
