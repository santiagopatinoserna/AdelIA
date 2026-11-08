import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { GuestRecord } from "./kit";

// The guests a run opened, on disk in its folder: the worker writes, the
// reporter (another process) reads, and a guest left behind fails the run.

function file(runDir: string): string {
  return join(runDir, "guests.json");
}

export function readGuests(runDir: string): GuestRecord[] {
  if (!existsSync(file(runDir))) return [];
  return JSON.parse(readFileSync(file(runDir), "utf8")) as GuestRecord[];
}

export function saveGuest(runDir: string, record: GuestRecord): void {
  mkdirSync(runDir, { recursive: true });
  const rest = readGuests(runDir).filter((g) => g.id !== record.id);
  writeFileSync(file(runDir), JSON.stringify([...rest, record], null, 2) + "\n");
}
