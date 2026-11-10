import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { readGuests } from "../guests";
import { type CheckResult, summarize } from "../kit";
import { type Issue, type JourneyStep, rankIssues, renderReport, usabilitySettings } from "./kit";
import { readEntries } from "./page";

// The battery's report: report.html (problems ranked by what bothers her
// most, journeys, performance, first screens, axe, every check and the
// shots) and summary.json, the smoke suite's shape plus the ranked problems.
// Printed last: where the report is and the ten worst problems.
/** observations.txt in the run folder: one line per thing seen in the shots. */
export function readObservations(runDir: string): string[] {
  const file = join(runDir, "observations.txt");
  return existsSync(file) ? readFileSync(file, "utf8").split("\n").map((l) => l.trim()).filter(Boolean) : [];
}

export default class UsabilityReporter implements Reporter {
  private results: CheckResult[] = [];
  private startedAt = new Date().toISOString();

  onTestEnd(test: TestCase, result: TestResult) {
    const annotations = [...test.annotations, ...(result.annotations ?? [])];
    this.results.push({
      title: test.title,
      status: result.status,
      durationMs: result.duration,
      error: result.error?.message,
      notes: [...new Set(annotations.filter((a) => a.type === "note" && a.description).map((a) => a.description!))],
      shots: result.attachments
        .filter((a) => a.path && a.contentType === "image/png")
        .map((a) => a.path as string),
    });
  }

  onEnd() {
    const settings = usabilitySettings(process.env, { home: homedir(), now: new Date() });
    const runDir = settings.runDir;
    const summary = summarize({ baseURL: settings.baseURL, runDir, startedAt: this.startedAt }, this.results, readGuests(runDir));
    const entries = readEntries(runDir);
    const issues = entries.filter((e) => e.type === "issue") as (Issue & { type: "issue" })[];
    const html = renderReport({
      baseURL: settings.baseURL,
      startedAt: this.startedAt,
      runDir,
      checks: summary.checks.map((c) => ({ id: c.id, title: c.title, ok: c.ok, detail: c.detail, durationMs: c.duration_ms })),
      issues: issues.map(({ kind, where, detail }) => ({ kind, where, detail })),
      metrics: entries.flatMap((e) => (e.type === "metric" ? [{ section: e.section, key: e.key, values: e.values }] : [])),
      journeys: entries.flatMap((e) => (e.type === "journey" ? [{ name: e.name, steps: e.steps as JourneyStep[] }] : [])),
      shots: this.results.flatMap((r) => r.shots).filter((s) => !s.includes("/artifacts/")),
      observations: readObservations(runDir),
    });
    mkdirSync(runDir, { recursive: true });
    writeFileSync(join(runDir, "report.html"), html);
    const ranked = rankIssues(issues);
    writeFileSync(join(runDir, "summary.json"), JSON.stringify({ ...summary, problems: ranked }, null, 2) + "\n");
    const top = ranked.slice(0, 10).map((r, i) => `${i + 1}. ${r.label}: ${r.detail} (${r.count})`).join("\n");
    process.stdout.write(
      `\nusability report: ${join(runDir, "report.html")}\n` +
        `checks: ${summary.checks.filter((c) => c.ok).length} ok, ${summary.checks.filter((c) => c.ok === false).length} failed; ` +
        `guests left: ${summary.guests.filter((g) => !g.erased).length}\n${top}\n`,
    );
  }

  printsToStdio() {
    return true;
  }
}
