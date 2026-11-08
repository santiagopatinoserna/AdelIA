import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { readGuests } from "./guests";
import { type CheckResult, smokeSettings, summarize } from "./kit";

// One JSON for Hermes: every check with ok or failure and its detail, the
// screenshots, and every guest the run opened with whether it is gone. Written
// to <run folder>/summary.json and printed last on stdout.
export default class SummaryReporter implements Reporter {
  private results: CheckResult[] = [];
  private startedAt = new Date().toISOString();

  onTestEnd(test: TestCase, result: TestResult) {
    const annotations = [...test.annotations, ...(result.annotations ?? [])];
    const notes = [
      ...new Set(
        annotations
          .filter((a) => ["note", "fixme", "skip"].includes(a.type) && a.description)
          .map((a) => a.description as string),
      ),
    ];
    this.results.push({
      title: test.title,
      status: result.status,
      durationMs: result.duration,
      error: result.error?.message,
      notes,
      shots: result.attachments
        .filter((a) => a.path && a.contentType === "image/png")
        .map((a) => a.path as string),
    });
  }

  onEnd() {
    const settings = smokeSettings(process.env, { home: homedir(), now: new Date() });
    const summary = summarize(
      { baseURL: settings.baseURL, runDir: settings.runDir, startedAt: this.startedAt },
      this.results,
      readGuests(settings.runDir),
    );
    mkdirSync(settings.runDir, { recursive: true });
    const file = join(settings.runDir, "summary.json");
    writeFileSync(file, JSON.stringify(summary, null, 2) + "\n");
    process.stdout.write(`\nprod smoke summary: ${file}\n${JSON.stringify(summary, null, 2)}\n`);
  }

  printsToStdio() {
    return true;
  }
}
