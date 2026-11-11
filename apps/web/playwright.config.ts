import { defineConfig } from "@playwright/test";

// Local E2E against a running stack:
//   docker compose -f infra/docker-compose.dev.yml up -d
//   pnpm dev:api  (or uvicorn on :8000)
//   pnpm --filter @adelia/web build && pnpm --filter @adelia/web start -p 3001
//   pnpm --filter @adelia/web e2e
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    // CI's headless shell crashed with SIGSEGV while creating browser contexts.
    // Use Chromium's full new-headless implementation, without retrying tests.
    channel: process.env.CI ? "chromium" : undefined,
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3001",
    trace: "retain-on-failure",
    // public/sw.js registers on hydration and then sits between the page and
    // the network: a turn mocked with page.route reached the real API (no
    // model key: "Ahora no puedo responderte") in a different spec each time.
    // Also applies to browser.newContext() in a spec. Only e2e/pwa-sw.spec.ts,
    // which tests the worker, opens a context with "allow" (ask-helper.spec.ts).
    serviceWorkers: "block",
    // Fake mic: lets Chromium feed MediaRecorder a synthetic audio device in
    // headless CI, without a real permission prompt — needed by
    // consulta-record.spec.ts (getUserMedia + MediaRecorder).
    launchOptions: {
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
      ],
    },
  },
  reporter: [["list"]],
});
