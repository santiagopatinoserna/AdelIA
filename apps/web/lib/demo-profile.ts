// The fictional baby lives in ONE place, the API, and both the record card and
// the context the model is given are built from it (adelia/demo/fixture.py).
// A second copy in the message catalogues would drift, and the first thing to
// drift would be the numbers the answer cites back at the visitor.
// Moved out of demo/page.tsx when the demo became part of the landing, so
// there is still one loader and one shape.

const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export type DemoItem = {
  kind: "report" | "lab" | "consulta" | "diary";
  title: string;
  meta: string;
  date: string;
  lines: string[];
};

export type DemoProfile = {
  is_demo: boolean;
  baby_name: string;
  age_label: string;
  banner: string;
  record_title: string;
  record_note: string;
  suggested: string[];
  items: DemoItem[];
};

// This cache is ONLY for the anonymous, fictional /demo/profile endpoint.
// A minute bounds drift from the API fixture used to answer questions. Never
// reuse this loader/cache for an authenticated child's record. One entry per
// supported locale bounds memory; in-flight visits share the same request.
const FRESH_MS = 60_000;
const profiles = new Map<string, { at: number; pending: Promise<DemoProfile | null> }>();

export function resetDemoProfileCache(): void {
  profiles.clear();
}

export async function loadDemoProfile(locale: string): Promise<DemoProfile | null> {
  const language = locale.split("-")[0].toLowerCase();
  const key = ["es", "en", "fr"].includes(language) ? language : "es";
  const now = Date.now();
  const hit = profiles.get(key);
  const sameDay = hit && Math.floor(hit.at / 86_400_000) === Math.floor(now / 86_400_000);
  if (hit && sameDay && now - hit.at < FRESH_MS) return hit.pending;

  const pending = fetchProfile(key);
  const entry = { at: now, pending };
  profiles.set(key, entry);
  const value = await pending;
  // A failed request must not poison the cache, nor delete a newer refresh.
  if (!value && profiles.get(key) === entry) profiles.delete(key);
  return value;
}

// Do not share a response unless it explicitly declares itself fictional and
// has the renderable shape. A bad upstream payload degrades to unavailable.
function isDemoProfile(body: unknown): body is DemoProfile {
  if (typeof body !== "object" || body === null) return false;
  const b = body as Record<string, unknown>;
  const strings = (value: unknown): value is string[] =>
    Array.isArray(value) && value.every(item => typeof item === "string");
  return b.is_demo === true &&
    [b.baby_name, b.age_label, b.banner, b.record_title, b.record_note]
      .every(value => typeof value === "string") &&
    strings(b.suggested) && Array.isArray(b.items) && b.items.every(item => {
      if (typeof item !== "object" || item === null) return false;
      return ["report", "lab", "consulta", "diary"].includes(item.kind) &&
        [item.title, item.meta, item.date].every(value => typeof value === "string") &&
        strings(item.lines);
    });
}

async function fetchProfile(locale: string): Promise<DemoProfile | null> {
  try {
    const res = await fetch(`${API_URL}/demo/profile?locale=${encodeURIComponent(locale)}`, {
      cache: "no-store",
      credentials: "omit",
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) return null;
    const body: unknown = await res.json();
    return isDemoProfile(body) ? body : null;
  } catch {
    return null;
  }
}
