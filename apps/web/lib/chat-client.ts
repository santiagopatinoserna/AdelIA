import { auth } from "@/lib/auth";
import { API_URL } from "@/lib/api-client";

export type Citation = {
  chunk_id: string;
  document_id: string;
  raw_quote: string;
  page: number | null;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
};

export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatSessionDetail = ChatSession & {
  messages: ChatMessage[];
};

async function authedHeaders(): Promise<Record<string, string>> {
  const session = await auth();
  const token = session?.jwt;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function listChatSessions(): Promise<ChatSession[]> {
  const headers = await authedHeaders();
  const res = await fetch(`${API_URL}/chat/sessions`, { headers, cache: "no-store" });
  if (!res.ok) throw new Error(`listChatSessions: ${res.status}`);
  return res.json();
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  const headers = await authedHeaders();
  const res = await fetch(`${API_URL}/chat/sessions/${id}`, { headers, cache: "no-store" });
  if (!res.ok) throw new Error(`getChatSession: ${res.status}`);
  return res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const headers = await authedHeaders();
  const res = await fetch(`${API_URL}/chat/sessions/${id}`, {
    method: "DELETE",
    headers,
    cache: "no-store",
  });
  if (!res.ok && res.status !== 204) throw new Error(`deleteChatSession: ${res.status}`);
}

export type StreamEvent =
  | { type: "start"; session_id: string }
  | { type: "token"; content: string }
  | { type: "final"; session_id: string; citations: Citation[] }
  | { type: "error"; content: string };

export async function* streamChat(
  jwt: string,
  question: string,
  sessionId: string | null
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ session_id: sessionId, question }),
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


function* parseBufferBlocks(
  read: () => string,
  write: (rest: string) => void,
): Generator<StreamEvent> {
  let buffer = read();
  let blockEnd: number;
  while ((blockEnd = buffer.indexOf("\n\n")) !== -1) {
    const rawBlock = buffer.slice(0, blockEnd);
    buffer = buffer.slice(blockEnd + 2);
    const block = rawBlock.trim();
    if (!block) continue;

    let eventType = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) eventType = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch (e) {
      // SSE protocol issue or partial JSON — log + skip rather than
      // silently dropping diagnostic info.
      if (typeof console !== "undefined") {
        console.warn("[chat-client] SSE parse error", rawBlock, e);
      }
      continue;
    }

    if (eventType === "start") {
      yield { type: "start", session_id: String(payload.session_id ?? "") };
    } else if (eventType === "token") {
      yield { type: "token", content: String(payload.content ?? "") };
    } else if (eventType === "final") {
      yield {
        type: "final",
        session_id: String(payload.session_id ?? ""),
        citations: (payload.citations as Citation[]) ?? [],
      };
    } else if (eventType === "error") {
      yield { type: "error", content: String(payload.content ?? "unknown error") };
    }
  }
  write(buffer);
}
