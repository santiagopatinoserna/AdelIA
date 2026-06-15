// Browser chat client for "use client" components. All requests go through
// the same-origin /api/backend proxy — the backend JWT never reaches the
// browser and SSE streams straight through the route handler.

import {
  parseBufferBlocks,
  type ChatSession,
  type ChatSessionDetail,
  type StreamEvent,
} from "./chat-types";

export type {
  ChatMessage,
  ChatSession,
  ChatSessionDetail,
  Citation,
  EvidenceCitation,
  StreamEvent,
} from "./chat-types";

export async function listChatSessions(): Promise<ChatSession[]> {
  const res = await fetch("/api/backend/chat/sessions", { cache: "no-store" });
  if (!res.ok) throw new Error(`listChatSessions: ${res.status}`);
  return res.json();
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  const res = await fetch(`/api/backend/chat/sessions/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`getChatSession: ${res.status}`);
  return res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await fetch(`/api/backend/chat/sessions/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok && res.status !== 204) throw new Error(`deleteChatSession: ${res.status}`);
}

export async function* streamChat(
  question: string,
  sessionId: string | null,
  locale: string = "es",
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch("/api/backend/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ session_id: sessionId, question, locale }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`streamChat failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    yield* parseBufferBlocks(() => buffer, (rest) => { buffer = rest; });
  }
  // Flush trailing partial block — if the server's final SSE message
  // doesn't end with \n\n (some proxies strip it), we'd otherwise drop
  // the 'final' event and its citations silently.
  if (buffer.trim()) {
    yield* parseBufferBlocks(() => buffer + "\n\n", (rest) => { buffer = rest; });
  }
}
