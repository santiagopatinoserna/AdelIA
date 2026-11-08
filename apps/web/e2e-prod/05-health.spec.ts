import { expect, test } from "@playwright/test";

import { note } from "./browser";

// Check 5: the API is ready through to Postgres (/healthz) and the web says
// which build it runs (/api/version). The versions go into the summary.
// On the live site nginx maps /healthz to the API; against a local stack set
// PROD_SMOKE_API_URL to the API's own origin.
const API = (process.env.PROD_SMOKE_API_URL ?? "").replace(/\/+$/, "");

test("5 /healthz y /api/version", async ({ request }) => {
  const health = await request.get(`${API}/healthz`);
  expect(health.status(), "/healthz status").toBe(200);
  const h = (await health.json()) as {
    status?: string;
    version?: string;
    checks?: { database?: { status?: string; schema_revision?: string } };
  };
  expect(h.status).toBe("ok");
  expect(h.checks?.database?.status).toBe("ok");

  const version = await request.get("/api/version");
  expect(version.status(), "/api/version status").toBe(200);
  const v = (await version.json()) as { buildId?: string };
  expect(typeof v.buildId).toBe("string");
  expect(v.buildId).not.toBe("");

  note(
    `api ${h.version}, schema ${h.checks?.database?.schema_revision}, web build ${v.buildId}`,
  );
});
