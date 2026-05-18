import { auth } from "@/lib/auth";

import type {
  BriefingCreate,
  BriefingDetailOut,
  BriefingOut,
} from "./briefing-types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export type DocumentDTO = {
  id: string;
  source: "web" | "manual";
  mime_type: string;
  s3_key: string;
  raw_text: string | null;
  created_at: string;
  processed_at: string | null;
  status: DocumentStatus;
  entity_count: number;
  chunk_count: number;
};

async function authedFetch(path: string, init?: RequestInit) {
  const session = await auth();
  const token = session?.jwt;
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
}

export async function listDocuments(): Promise<DocumentDTO[]> {
  const res = await authedFetch("/documents");
  if (!res.ok) throw new Error(`listDocuments: ${res.status}`);
  return res.json();
}

export async function getDocument(id: string): Promise<DocumentDTO> {
  const res = await authedFetch(`/documents/${id}`);
  if (!res.ok) throw new Error(`getDocument: ${res.status}`);
  return res.json();
}

// M5 briefings namespace
export const briefings = {
  async create(input: BriefingCreate): Promise<BriefingOut> {
    const res = await authedFetch("/briefings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) throw new Error(`briefings.create: ${res.status}`);
    return res.json();
  },

  async list(): Promise<BriefingOut[]> {
    const res = await authedFetch("/briefings");
    if (!res.ok) throw new Error(`briefings.list: ${res.status}`);
    return res.json();
  },

  async getById(id: string): Promise<BriefingDetailOut> {
    const res = await authedFetch(`/briefings/${id}`);
    if (!res.ok) throw new Error(`briefings.getById: ${res.status}`);
    return res.json();
  },

  async regenerate(id: string): Promise<BriefingOut> {
    const res = await authedFetch(`/briefings/${id}/regenerate`, { method: "POST" });
    if (!res.ok) throw new Error(`briefings.regenerate: ${res.status}`);
    return res.json();
  },

  async remove(id: string): Promise<void> {
    const res = await authedFetch(`/briefings/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`briefings.remove: ${res.status}`);
  },
};
