// Consented visitor journeys (decision of Santiago, 2026-11-07).
//
// Browser half of apps/api/adelia/services/analytics.py. Three rules, each
// tested in e2e/analytics-consent.spec.ts:
//
//   1. Nothing before "Aceptar". Until the visitor accepts, no id is drawn,
//      nothing is written to storage except her answer, and no event leaves
//      the page. A rejection or the browser's GPC signal keeps it that way.
//   2. Never what she writes. An event is a page, a pressed element's stable
//      name, a scroll band or a funnel step. Text fields are never read, the
//      query string never leaves (the landing can carry a question in it,
//      lib/landing-question.ts), and inside the panel or any element marked
//      `data-track-private` a click is named by its role alone.
//   3. Never in her way. Events wait in memory and leave in batches with
//      sendBeacon (when the page is hidden, every few seconds, or right before
//      a navigation the page itself starts), so no request delays a tap.
//
// The consent lives in localStorage, not in a cookie: the server never needs
// it on a request, and the API checks every batch against the proof it holds.
// No React context: components read the state with useSyncExternalStore and
// call track(), so nothing here re-renders the layout's providers (the
// duplicated-DOM bug of 7adb21c).

export const CONSENT_VERSION = "2026-11-08";

export type ConsentState = "unknown" | "accepted" | "rejected" | "gpc";
export type FunnelStep =
  | "landing_view"
  | "first_interaction"
  | "guest_created"
  | "question_sent"
  | "answer_shown"
  | "follow_up"
  | "recording_started"
  | "recording_finished"
  | "save_requested"
  | "account_saved"
  | "signup"
  | "trial_started"
  | "payment";

type AnalyticsEvent = {
  ts: number;
  type: "pageview" | "click" | "scroll" | "step";
  path: string;
  element?: string;
  depth?: number;
  step?: FunnelStep;
};

const CONSENT_KEY = "adelia-analytics-consent";
const VISITOR_KEY = "adelia-analytics-visitor";
const SESSION_KEY = "adelia-analytics-session";
const ENDPOINT = "/api/analytics";
// 13 months, the same as the events (services/analytics.EVENT_RETENTION_DAYS):
// after that the banner asks again.
const CONSENT_MAX_AGE_MS = 396 * 24 * 3600 * 1000;
const SESSION_IDLE_MS = 30 * 60 * 1000;
const FLUSH_EVERY_MS = 5000;
const FLUSH_AT = 20;
const LABEL_MAX = 40;
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"] as const;
const LANDING = /^\/(es|en|fr)\/?$/;
export const PRIVATE_PAGES = /^\/(es|en|fr)\/(dashboard|onboarding)(\/|$)/;

type StoredConsent = { v: string; choice: "accepted" | "rejected"; id: string; at: number };

// ---------------------------------------------------------------- consent

function gpc(): boolean {
  return (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true;
}

function readStored(): StoredConsent | null {
  try {
    const raw = localStorage.getItem(CONSENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredConsent;
    if (parsed.choice !== "accepted" && parsed.choice !== "rejected") return null;
    return parsed;
  } catch {
    return null;
  }
}

function computeState(): ConsentState {
  if (typeof window === "undefined") return "unknown";
  if (gpc()) return "gpc";
  const stored = readStored();
  if (!stored || stored.v !== CONSENT_VERSION || Date.now() - stored.at > CONSENT_MAX_AGE_MS) {
    return "unknown";
  }
  return stored.choice;
}

const listeners = new Set<() => void>();
let snapshot: ConsentState | null = null;

export function consentSnapshot(): ConsentState {
  if (snapshot === null) snapshot = computeState();
  return snapshot;
}

// The server renders nothing for the banner: what she chose is only known in
// her browser. "pending" keeps the server HTML and the first client render
// identical, and useSyncExternalStore switches to the real value right after
// hydration without an effect calling setState.
export function consentServerSnapshot(): ConsentState | "pending" {
  return "pending";
}

export function subscribeConsent(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === CONSENT_KEY) refresh();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function refresh() {
  snapshot = computeState();
  listeners.forEach((l) => l());
}

function randomId(): string {
  return crypto.randomUUID();
}

function postConsent(body: Record<string, unknown>) {
  try {
    void fetch(`${ENDPOINT}/consent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      keepalive: true,
      body: JSON.stringify(body),
    }).catch(() => {});
  } catch {
    // The proof is best effort; her choice is already applied in this browser.
  }
}

/**
 * Apply her answer. "accepted" draws the ids and measures the page she is on;
 * "rejected" after an acceptance is a withdrawal: the ids are deleted here and
 * the server deletes what this browser sent.
 */
export function setConsent(choice: "accepted" | "rejected", source: "banner" | "settings" | "privacy") {
  if (gpc()) return;
  const before = readStored();
  const id = before?.id ?? randomId();
  const withdrawing = choice === "rejected" && before?.choice === "accepted";
  let visitor: string | null = null;
  try {
    visitor = localStorage.getItem(VISITOR_KEY);
    localStorage.setItem(CONSENT_KEY, JSON.stringify({ v: CONSENT_VERSION, choice, id, at: Date.now() }));
    if (choice === "rejected") {
      localStorage.removeItem(VISITOR_KEY);
      sessionStorage.removeItem(SESSION_KEY);
    }
  } catch {
    // Storage refused: the choice holds for this page only, and nothing is sent.
  }
  queue.length = 0;
  postConsent({
    consent_id: id,
    choice: withdrawing ? "withdrawn" : choice,
    version: CONSENT_VERSION,
    source,
    ...(withdrawing && visitor ? { forget_visitor: visitor } : {}),
  });
  refresh();
  if (choice === "accepted") {
    pageview(location.pathname);
    if (LANDING.test(location.pathname)) track("landing_view");
  }
}

function accepted(): boolean {
  return typeof window !== "undefined" && consentSnapshot() === "accepted";
}

// ---------------------------------------------------------------- ids and origin

function visitorId(): string {
  let id = localStorage.getItem(VISITOR_KEY);
  if (!id) {
    id = randomId();
    localStorage.setItem(VISITOR_KEY, id);
  }
  return id;
}

type SessionInfo = { id: string; last: number; interacted?: boolean };

function session(): SessionInfo {
  const now = Date.now();
  let info: SessionInfo | null = null;
  try {
    info = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null") as SessionInfo | null;
  } catch {
    info = null;
  }
  if (!info || now - info.last > SESSION_IDLE_MS) info = { id: randomId(), last: now };
  info.last = now;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(info));
  return info;
}

function markInteracted(): boolean {
  const info = session();
  if (info.interacted) return false;
  info.interacted = true;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(info));
  return true;
}

/**
 * Where this visit came from: the referring domain (never its URL) and the
 * UTM parameters of the link. Read from the page as it is, never stored
 * before consent. A visitor sent from the landing to the panel by a full
 * navigation arrives with the landing as referrer, so its UTM are read from
 * there; the server keeps whatever the session's first batch said.
 */
export function originOf(href: string, referrer: string): Record<string, string | null> {
  const here = new URL(href);
  let refUrl: URL | null = null;
  try {
    refUrl = referrer ? new URL(referrer) : null;
  } catch {
    refUrl = null;
  }
  const internal = refUrl !== null && refUrl.host === here.host;
  const utmFrom = here.searchParams.has("utm_source") || !internal ? here : refUrl!;
  const out: Record<string, string | null> = {
    referrer: refUrl && !internal ? refUrl.hostname : null,
  };
  for (const key of UTM_KEYS) out[key] = utmFrom.searchParams.get(key)?.slice(0, 100) ?? null;
  return out;
}

let origin: Record<string, string | null> | null = null;
let landingPath: string | null = null;

function context() {
  if (!origin) {
    origin = originOf(location.href, document.referrer);
    landingPath = location.pathname;
  }
  return {
    ...origin,
    landing_path: landingPath,
    locale: document.documentElement.lang || null,
    lang: navigator.language || null,
    screen_w: window.screen?.width ?? null,
    screen_h: window.screen?.height ?? null,
  };
}

// ---------------------------------------------------------------- queue

const queue: AnalyticsEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

function push(event: Omit<AnalyticsEvent, "ts" | "path"> & { path?: string }) {
  if (!accepted()) return;
  try {
    queue.push({ ts: Date.now(), path: event.path ?? location.pathname, ...event } as AnalyticsEvent);
    session();
  } catch {
    return;
  }
  if (queue.length >= FLUSH_AT) flush();
  else if (!timer) timer = setTimeout(flush, FLUSH_EVERY_MS);
}

/** Send what is waiting, now. Safe to call from pagehide. */
export function flush() {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (!queue.length || !accepted()) {
    queue.length = 0;
    return;
  }
  const stored = readStored();
  if (!stored) return;
  let body: string;
  try {
    body = JSON.stringify({
      consent_id: stored.id,
      visitor_id: visitorId(),
      session_id: session().id,
      context: context(),
      events: queue.splice(0, queue.length),
    });
  } catch {
    return;
  }
  const url = `${ENDPOINT}/collect`;
  // A string body goes as text/plain: no preflight, and the API reads it as
  // JSON whatever the content type (services/analytics.parse_body).
  if (navigator.sendBeacon?.(url, body)) return;
  void fetch(url, { method: "POST", body, keepalive: true, credentials: "omit" }).catch(() => {});
}

// ---------------------------------------------------------------- what is measured

let lastPageview: { path: string; at: number } | null = null;

/** One view of `path`. Accepting the banner measures the page she is on, and
 * the tracker that mounts right after would count it again: same path within
 * a second is the same view. */
export function pageview(path: string) {
  const now = Date.now();
  if (lastPageview && lastPageview.path === path && now - lastPageview.at < 1000) return;
  if (!accepted()) return;
  lastPageview = { path, at: now };
  push({ type: "pageview", path });
}

/** A funnel step. `now`: the page is about to navigate, send it first. */
export function track(step: FunnelStep, options?: { now?: boolean }) {
  push({ type: "step", step });
  if (options?.now) flush();
}

export function trackScroll(depth: 25 | 50 | 75 | 100) {
  push({ type: "scroll", depth });
}

const TESTID = /^[a-z][a-z0-9-]{1,40}$/;
const ROLE_OF: Record<string, string> = {
  A: "link", BUTTON: "button", SUMMARY: "summary", SELECT: "select", LABEL: "label",
};

/**
 * The name a click is stored under, or null when it is not a control.
 *
 * In order: `data-track`, a `data-testid` that is a plain name, and on
 * public pages only the aria-label or the visible text (copy we wrote).
 * Inside the panel and the onboarding, and inside `data-track-private`, both
 * can be hers (a document title, a conversation named after her question,
 * her baby's name, a questionnaire answer read out in an aria-label), so the
 * role is all that is kept.
 */
export function elementName(target: Element, pathname: string): string | null {
  const control = target.closest(
    "[data-track], a, button, summary, select, label, [role=button], [role=link], [role=tab], input[type=checkbox], input[type=radio]",
  );
  if (!control) return null;
  const role =
    control.getAttribute("role") ??
    (control instanceof HTMLInputElement ? control.type : ROLE_OF[control.tagName] ?? "control");
  const named = control.getAttribute("data-track");
  if (named) return named.slice(0, 64);
  const testid = control.getAttribute("data-testid");
  if (testid && TESTID.test(testid) && !/\d{3,}/.test(testid)) return testid;
  if (control.closest("[data-track-private]") || PRIVATE_PAGES.test(pathname)) return role;
  const aria = control.getAttribute("aria-label");
  if (aria) return `${role}:${aria.trim().slice(0, LABEL_MAX)}`;
  const text = (control.textContent ?? "").replace(/\s+/g, " ").trim();
  return text ? `${role}:${text.slice(0, LABEL_MAX)}` : role;
}

export function trackClick(target: Element) {
  if (!accepted()) return;
  const name = elementName(target, location.pathname);
  if (name) push({ type: "click", element: name });
}

/** The first tap or key of the session, once. */
export function trackInteraction() {
  if (!accepted()) return;
  try {
    if (markInteracted()) track("first_interaction");
  } catch {
    // sessionStorage refused: no step rather than one per tap.
  }
}
