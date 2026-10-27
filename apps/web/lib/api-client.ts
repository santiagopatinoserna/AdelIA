// Server-side API client. Signs requests with the session JWT via auth().
// NEVER import from a "use client" component — auth pulls in pg (Node-only).
// Client components use lib/api-client-browser.ts instead (same surface,
// requests proxied through /api/backend so the token stays server-side).

import { auth } from "@/lib/auth";

import { makeApi } from "./api-endpoints";

// Server-side fetches must use the internal upstream inside docker; the
// public origin is what the browser sees, not necessarily reachable here.
export const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export type {
  DocumentDTO,
  DocumentStatus,
  EmailAliasDTO,
  TelegramLinkDTO,
} from "./api-endpoints";

async function authedFetch(path: string, init?: RequestInit) {
  const session = await auth();
  const token = session?.jwt;
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
}

const api = makeApi(authedFetch);

export const listDocuments = api.listDocuments;
export const getDocument = api.getDocument;
export const briefings = api.briefings;
export const ingestion = api.ingestion;
export const enrichment = api.enrichment;
export const billingStatus = api.billingStatus;
export const onboarding = api.onboarding;
export const today = api.today;
export type { BabyOnboarding, BillingStatus, OnboardingStatus, TodayDTO, TodayItem } from "./api-endpoints";
