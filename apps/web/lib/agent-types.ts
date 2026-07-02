// Agent-mode DTOs + SSE stream event types. No auth import — safe for client bundles.

export type AgentCard = {
  type: "action" | "confirm" | "question" | "lab" | "briefing" | "document" | "profile" | "insight";
  id: string;
  payload: Record<string, unknown>;
  actions: { label: string; intent: string }[];
};

export type AgentStreamEvent =
  | { type: "start" }
  | { type: "token"; content: string }
  | { type: "tool_call"; tool_name: string }
  | { type: "card"; card: AgentCard }
  | { type: "final" }
  | { type: "error"; content: string };

export function* parseAgentBlocks(
  read: () => string,
  write: (rest: string) => void,
): Generator<AgentStreamEvent> {
  let buffer = read().replace(/\r\n/g, "\n");
  let idx: number;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const block = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    let eventType = "";
    let dataStr = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) eventType = line.slice(6).trim();
      else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
    }
    if (!eventType) continue;
    let data: Record<string, unknown> = {};
    try { data = dataStr ? JSON.parse(dataStr) : {}; }
    catch { console.warn("agent: bad SSE data", dataStr); continue; }
    switch (eventType) {
      case "start": yield { type: "start" }; break;
      case "token": yield { type: "token", content: String(data.content ?? "") }; break;
      case "tool_call": yield { type: "tool_call", tool_name: String(data.tool_name ?? "") }; break;
      case "card": yield { type: "card", card: data.card as AgentCard }; break;
      case "final": yield { type: "final" }; break;
      case "error": yield { type: "error", content: String(data.content ?? "") }; break;
      default: break;
    }
  }
  write(buffer);
}
