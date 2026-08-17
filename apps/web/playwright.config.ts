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
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3001",
    trace: "retain-on-failure",
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
