// Server-side chat client (server components only — uses auth()).
// Client components use lib/chat-client-browser.ts.

import { auth } from "@/lib/auth";

import { API_URL } from "./api-client";
import type { ChatSession, ChatSessionDetail } from "./chat-types";

export type {
  ChatMessage,
  ChatSession,
  ChatSessionDetail,
  Citation,
  EvidenceCitation,
  StreamEvent,
} from "./chat-types";

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
