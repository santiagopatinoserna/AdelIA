// Browser chat client for "use client" components. All requests go through
// the same-origin /api/backend proxy — the backend JWT never reaches the
// browser and SSE streams straight through the route handler.

import {
  parseBufferBlocks,
  type ChatSession,
  type ChatSessionDetail,
  type StreamEvent,
} from "./chat-types";
import { isLocalRedactionEnabled, redactOutgoingQuestion } from "./redaction/chat";

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

/**
 * `profileId` is which child the question is about. The API resolves null to
 * the account's default profile, and the answer, the age that gates the red
 * flags and the citations are then all about the same child (audit 4.1, 4.2).
 *
 * This is the one place the question leaves the browser for the chat API, so it
 * is the one call site of local redaction (lib/redaction/chat.ts). That is
 * behind NEXT_PUBLIC_LOCAL_REDACTION, which is OFF: with it off `redaction` is
 * null, the body below is exactly what it always was and the stream is passed
 * through untouched.
 */
export async function* streamChat(
  question: string,
  sessionId: string | null,
  locale: string = "es",
  signal?: AbortSignal,
  profileId?: string | null,
): AsyncGenerator<StreamEvent> {
  const redaction = isLocalRedactionEnabled()
    ? await redactOutgoingQuestion(question, sessionId)
    : null;
  const res = await fetch("/api/backend/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      session_id: sessionId,
      question: redaction ? redaction.question : question,
      locale,
      profile_id: profileId ?? null,
    }),
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
    const events = parseBufferBlocks(() => buffer, (rest) => { buffer = rest; });
    yield* redaction ? redaction.events(events) : events;
  }
  // Flush trailing partial block — if the server's final SSE message
  // doesn't end with \n\n (some proxies strip it), we'd otherwise drop
  // the 'final' event and its citations silently.
  if (buffer.trim()) {
    const events = parseBufferBlocks(() => buffer + "\n\n", (rest) => { buffer = rest; });
    yield* redaction ? redaction.events(events) : events;
  }
  if (redaction) yield* redaction.finish();
}
