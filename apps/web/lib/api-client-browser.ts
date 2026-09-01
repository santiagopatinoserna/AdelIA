// Browser-side API client for "use client" components. Same surface as
// lib/api-client.ts, but requests go through the same-origin /api/backend
// proxy, which attaches the backend JWT server-side. The token never
// reaches the browser and FastAPI needs no CORS exposure.

import { makeApi } from "./api-endpoints";

export type {
  DocumentDTO,
  DocumentStatus,
  EmailAliasDTO,
  TelegramLinkDTO,
} from "./api-endpoints";

function proxyFetch(path: string, init?: RequestInit) {
  return fetch(`/api/backend${path}`, { ...init, cache: "no-store" });
}

const api = makeApi(proxyFetch);

export const listDocuments = api.listDocuments;
export const getDocument = api.getDocument;
export const deleteDocument = api.deleteDocument;
export const reprocessDocument = api.reprocessDocument;
export const setSpeakerNames = api.setSpeakerNames;
export const briefings = api.briefings;
export const ingestion = api.ingestion;
export const enrichment = api.enrichment;
export const onboarding = api.onboarding;
