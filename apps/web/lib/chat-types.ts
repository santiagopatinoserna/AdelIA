// Chat DTOs + SSE stream event types. No auth import — safe for client bundles.

export type Citation = {
  chunk_id: string;
  document_id: string;
  raw_quote: string;
  page: number | null;
};

export type EvidenceCitation = {
  tag: string;
  source_id: string;
  chunk_id: string;
  title: string;
  organization?: string | null;
  year?: number | null;
  url?: string | null;
  snippet: string;
  distance?: number;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  evidence_citations?: EvidenceCitation[];
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

export type StreamEvent =
  | { type: "start"; session_id: string }
  | { type: "token"; content: string }
  | { type: "final"; session_id: string; citations: Citation[] }
  | { type: "error"; content: string };

export function* parseBufferBlocks(
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
