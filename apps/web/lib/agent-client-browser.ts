import { parseAgentBlocks, type AgentStreamEvent, type AgentCard } from "@/lib/agent-types";

export async function* streamAgent(
  body: { message?: string; profile_id?: string | null; locale?: string; card_action?: object },
  signal?: AbortSignal,
): AsyncGenerator<AgentStreamEvent> {
  const res = await fetch("/api/backend/agent/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ locale: "es", ...body }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`streamAgent failed: ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    yield* parseAgentBlocks(() => buffer, (rest) => { buffer = rest; });
  }
  if (buffer.trim()) yield* parseAgentBlocks(() => buffer + "\n\n", (rest) => { buffer = rest; });
}

export async function getSuggestions(profileId: string | null, locale: string): Promise<AgentCard[]> {
  const qs = new URLSearchParams({ locale });
  if (profileId) qs.set("profile_id", profileId);
  const res = await fetch(`/api/backend/agent/suggestions?${qs.toString()}`, { cache: "no-store" });
  if (!res.ok) return [];
  const json = (await res.json()) as { cards: AgentCard[] };
  return json.cards ?? [];
}
