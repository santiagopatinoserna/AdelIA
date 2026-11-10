import AxeBuilder from "@axe-core/playwright";
import { type Browser, type BrowserContext, type Page, test } from "@playwright/test";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { armModelGuard, type ModelGuard } from "../browser";
import { QA_HEADERS } from "../kit";
import {
  type FirstScreen,
  type Issue,
  type JourneyStep,
  type Target,
  type Viewport,
  smallTargets,
  stubTurnFor,
} from "./kit";

// The browser half of the usability battery: the measures taken inside the
// page (first screen, tap targets, what covers a control, axe), the run's
// data file the report is built from, and the guest every check after 00
// borrows.

export const RUN_DIR = process.env.USABILITY_RUN_DIR!;
export const GUEST_STATE = () => join(RUN_DIR, "guest-state.json");

// --- the run's data -----------------------------------------------------------

export type Entry =
  | ({ type: "issue" } & Issue)
  | { type: "metric"; section: string; key: string; values: Record<string, number | string> }
  | { type: "journey"; name: string; steps: JourneyStep[] };

export function record(entry: Entry): void {
  mkdirSync(RUN_DIR, { recursive: true });
  appendFileSync(join(RUN_DIR, "data.jsonl"), JSON.stringify(entry) + "\n");
}

export function readEntries(runDir: string): Entry[] {
  const file = join(runDir, "data.jsonl");
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l) as Entry);
}

/** Record the problems and return them, for the check's own assertion. */
export function issues(list: Issue[]): Issue[] {
  for (const i of list) record({ type: "issue", ...i });
  return list;
}

/** A screenshot in the run folder, listed under this check. */
export async function shot(page: Page, name: string, fullPage = false): Promise<void> {
  mkdirSync(RUN_DIR, { recursive: true });
  const path = join(RUN_DIR, `${name}.png`);
  await page.screenshot({ path, fullPage });
  test.info().attachments.push({ name, path, contentType: "image/png" });
}

export function note(text: string): void {
  test.info().annotations.push({ type: "note", description: text });
}

// --- contexts -----------------------------------------------------------------

export type Scheme = "light" | "dark";

/**
 * A context of the matrix: the viewport, the colour scheme, the QA header, no
 * service worker, and the guest's session when `guest` is set. The model guard
 * is armed and, after it, the stub that answers the fixtures' turns in the
 * browser (Playwright tries the route added last first).
 */
export async function openContext(
  browser: Browser,
  opts: { viewport: Viewport; scheme: Scheme; locale: string; guest: boolean; baseURL: string },
): Promise<{ context: BrowserContext; page: Page; guard: ModelGuard; stubbed: Record<string, unknown>[]; errors: string[] }> {
  const context = await browser.newContext({
    baseURL: opts.baseURL,
    viewport: { width: opts.viewport.width, height: opts.viewport.height },
    isMobile: false,
    hasTouch: opts.viewport.phone,
    colorScheme: opts.scheme,
    locale: { es: "es-ES", en: "en-GB", fr: "fr-FR" }[opts.locale] ?? "es-ES",
    serviceWorkers: "block",
    extraHTTPHeaders: { ...QA_HEADERS },
    storageState: opts.guest ? GUEST_STATE() : undefined,
  });
  const guard = await armModelGuard(context);
  const stubbed: Record<string, unknown>[] = [];
  await context.route("**/api/backend/agent/turn", async (route) => {
    let body: unknown = null;
    try {
      body = route.request().postDataJSON();
    } catch {
      body = null;
    }
    const sse = stubTurnFor((body ?? {}) as Parameters<typeof stubTurnFor>[0]);
    if (sse === null) return route.fallback();
    stubbed.push(body as Record<string, unknown>);
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse });
  });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return { context, page, guard, stubbed, errors };
}

/** Network quiet and the entrance animations over (e2e/a11y.spec.ts says why). */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.evaluate(() =>
    Promise.race([
      Promise.allSettled(document.getAnimations().map((a) => a.finished)),
      new Promise((resolve) => setTimeout(resolve, 1500)),
    ]),
  );
}

// --- measures inside the page -------------------------------------------------

type ProbeArgs =
  | { mode: "first-screen" }
  | { mode: "targets" }
  | { mode: "covered" }
  | { mode: "keyboard"; selector: string; alsoVisible: string[] };

/**
 * Every measure taken inside the page, in one self-contained function: it is
 * serialised into the page, so it may use nothing from this module, and it
 * builds no code from strings (production's CSP would refuse that).
 */
function probe(args: ProbeArgs): unknown {
  const CONTROL =
    "a[href], button, input:not([type=hidden]), textarea, select, summary, " +
    "[role=button], [role=link], [role=checkbox], [role=tab]";
  const shown = (el: Element): boolean => {
    if (!el.isConnected) return false;
    if (el.closest('[hidden], [aria-hidden="true"], details:not([open]) > :not(summary)')) return false;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const nameOf = (el: Element): string => {
    const h = el as HTMLInputElement;
    const label =
      el.getAttribute("aria-label") ||
      (h.labels && h.labels[0] && h.labels[0].innerText) ||
      (el as HTMLElement).innerText ||
      el.getAttribute("placeholder") ||
      el.getAttribute("data-testid") ||
      el.tagName.toLowerCase();
    return label.replace(/\s+/g, " ").trim().slice(0, 48);
  };
  const describe = (el: Element | null): string => {
    if (!el) return "nothing";
    const owner = el.closest("[data-testid]");
    return owner ? owner.getAttribute("data-testid")! : el.id || el.tagName.toLowerCase();
  };
  // The part of the element the viewport and every clipping ancestor let through.
  const visibleRect = (el: Element) => {
    const r = el.getBoundingClientRect();
    let box = { l: Math.max(r.left, 0), t: Math.max(r.top, 0), r: Math.min(r.right, innerWidth), b: Math.min(r.bottom, innerHeight) };
    for (let a = el.parentElement; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === "visible" && s.overflowY === "visible") continue;
      const ar = a.getBoundingClientRect();
      box = { l: Math.max(box.l, ar.left), t: Math.max(box.t, ar.top), r: Math.min(box.r, ar.right), b: Math.min(box.b, ar.bottom) };
    }
    return box.r - box.l > 1 && box.b - box.t > 1 ? box : null;
  };
  // The box she can press: a checkbox or radio is pressed through its label.
  const hitBox = (el: Element) => {
    const h = el as HTMLInputElement;
    if (el.tagName === "INPUT" && ["checkbox", "radio"].includes(h.type) && h.labels && h.labels[0]) {
      const a = el.getBoundingClientRect();
      const b = h.labels[0].getBoundingClientRect();
      const l = Math.min(a.left, b.left);
      const t = Math.min(a.top, b.top);
      return { x: l, y: t, width: Math.max(a.right, b.right) - l, height: Math.max(a.bottom, b.bottom) - t };
    }
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  };
  const controls = (): Element[] => {
    const all = [...document.querySelectorAll(CONTROL)].filter(shown);
    // A control inside another (an icon button in a link) is one target.
    return all.filter((el) => !all.some((o) => o !== el && o.contains(el)));
  };
  const covering = (el: Element): Element | null => {
    const v = visibleRect(el);
    if (!v) return null;
    const w = v.r - v.l;
    const h = v.b - v.t;
    for (const [fx, fy] of [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]]) {
      const hit = document.elementFromPoint(v.l + w * fx, v.t + h * fy);
      if (!hit || el.contains(hit) || hit.contains(el)) continue;
      const labels = (el as HTMLInputElement).labels;
      if (labels && [...labels].some((l) => l.contains(hit))) continue;
      return hit;
    }
    return null;
  };
  const isWord = (w: string) => /[\p{L}\p{N}]/u.test(w);

  if (args.mode === "first-screen") {
    const inView = (r: DOMRect) =>
      r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && r.width > 1 && r.height > 1;
    const BLOCK = /^(block|flex|grid|list-item|table|table-cell|flow-root)$/;
    const units = new Set<Element>();
    let words = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.textContent || "";
      if (!isWord(text)) continue;
      const parent = n.parentElement;
      if (!parent || !shown(parent) || parent.closest(".sr-only, script, style, noscript")) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      if (![...range.getClientRects()].some(inView)) continue;
      words += text.split(/\s+/).filter(isWord).length;
      let unit: Element | null = parent;
      while (unit && unit !== document.body && !unit.matches(CONTROL) && !BLOCK.test(getComputedStyle(unit).display))
        unit = unit.parentElement;
      if (unit) units.add(unit);
    }
    const taps = controls().filter((el) => inView(el.getBoundingClientRect()));
    for (const el of taps) {
      units.add(el);
      const ph = el.getAttribute("placeholder");
      if (ph && !(el as HTMLInputElement).value) words += ph.split(/\s+/).filter(isWord).length;
    }
    return { blocks: units.size, taps: taps.length, words };
  }

  if (args.mode === "targets") {
    return controls().map((el) => {
      const b = hitBox(el);
      // A link inside a sentence: inline, with words of its block around it.
      let inline = false;
      if (el.tagName === "A" && getComputedStyle(el).display === "inline") {
        const block = el.parentElement;
        inline = !!block && (block.innerText || "").trim().length > ((el as HTMLElement).innerText || "").trim().length + 3;
      }
      return { name: nameOf(el), x: b.x, y: b.y + scrollY, width: b.width, height: b.height, inline };
    });
  }

  if (args.mode === "covered") {
    // The ways in of each screen: the field, sending, dictating, recording.
    const MAIN =
      "#demo-question, [data-track=landing-ask], [data-testid=landing-record], " +
      "[data-testid=agent-canvas] textarea, [data-testid=agent-canvas] .ad-btn-primary, " +
      "[data-testid=record-consult], [aria-pressed][aria-label]";
    const out: { by: string; control: string; main: boolean }[] = [];
    for (const el of controls()) {
      const hit = covering(el);
      if (hit) out.push({ by: describe(hit), control: nameOf(el), main: el.matches(MAIN) });
    }
    return out;
  }

  // keyboard: the field (and what must stay with it) fully on screen, uncovered.
  const out: string[] = [];
  const check = (sel: string, what: string) => {
    const el = document.querySelector(sel);
    if (!el) return out.push(`${what} no está`);
    const r = el.getBoundingClientRect();
    if (r.top < -0.5 || r.bottom > innerHeight + 0.5) return out.push(`${what} queda fuera de la pantalla con el teclado`);
    const hit = covering(el);
    if (hit) out.push(`${describe(hit)} tapa ${what} con el teclado`);
    return 0;
  };
  check(args.selector, "el campo");
  for (const sel of args.alsoVisible) check(sel, sel);
  return out;
}

/** Blocks, taps and words inside the first viewport, as she lands. */
export async function firstScreen(page: Page): Promise<FirstScreen> {
  return (await page.evaluate(probe, { mode: "first-screen" } as ProbeArgs)) as FirstScreen;
}

/** Every control on the page (scrolling allowed), with the box she can press. */
export async function tapTargets(page: Page): Promise<Target[]> {
  return (await page.evaluate(probe, { mode: "targets" } as ProbeArgs)) as Target[];
}

/**
 * Controls in view that something else sits on: the cookie banner, the bottom
 * bar, a sticky button. Five points of the visible part of each control are
 * probed; the first that lands on another element names it.
 */
export async function coveredControls(page: Page): Promise<{ by: string; control: string; main: boolean }[]> {
  return (await page.evaluate(probe, { mode: "covered" } as ProbeArgs)) as { by: string; control: string; main: boolean }[];
}

export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

/**
 * The keyboard opens over the field: focus it, take KEYBOARD_HEIGHT off the
 * viewport the way `interactive-widget=resizes-content` does, let the browser
 * bring the field into view as a phone does, and say what she cannot see.
 */
export async function keyboardProblems(
  page: Page,
  selector: string,
  v: Viewport,
  keyboard: number,
  alsoVisible: string[] = [],
  shotName?: string,
): Promise<string[]> {
  const field = page.locator(selector).first();
  await field.click();
  await page.setViewportSize({ width: v.width, height: v.height - keyboard });
  await page.waitForTimeout(400);
  await field.evaluate((el) => el.scrollIntoView({ block: "nearest" }));
  await page.waitForTimeout(200);
  const problems = (await page.evaluate(probe, { mode: "keyboard", selector, alsoVisible } as ProbeArgs)) as string[];
  if (shotName) await shot(page, shotName);
  await page.setViewportSize({ width: v.width, height: v.height });
  await page.locator("body").click({ position: { x: 1, y: 1 } }).catch(() => {});
  return problems;
}

/** Serious and critical axe violations, on the settled page. */
export async function axeBlocking(page: Page): Promise<{ id: string; impact: string; nodes: number; help: string }[]> {
  await settle(page);
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((v) => ["serious", "critical"].includes(v.impact ?? ""))
    .map((v) => ({ id: v.id, impact: v.impact ?? "", nodes: v.nodes.length, help: v.help }));
}

/** Is the guest's session state there (00 opened it)? Skips the check if not. */
export function needGuest(): void {
  test.skip(!existsSync(GUEST_STATE()), "no guest: 00 did not open one");
}

// --- what every screen of the matrix is checked for ---------------------------

/** 43.7 must not print as 44 in a line that says it is under 44. */
const px = (n: number) => (Number.isInteger(Math.round(n * 10) / 10) ? String(Math.round(n)) : n.toFixed(1));

/** Covered controls, sideways scrolling and small targets of the page as it is. */
export async function screenIssues(page: Page, where: string): Promise<Issue[]> {
  const out: Issue[] = [];
  for (const c of await coveredControls(page)) {
    // The cookie banner sits on the bottom of the landing until she answers
    // it; over a way in (the field, «Preguntar», recording) it is as bad as
    // anything else, over the rest it costs one tap.
    const kind = c.main || c.by !== "consent-banner" ? "control-covered" : "banner-covers";
    out.push({ kind, where, detail: `${c.by} tapa «${c.control}»` });
  }
  const over = await horizontalOverflow(page);
  if (over > 1) out.push({ kind: "horizontal-scroll", where, detail: `la página es ${over} px más ancha que la pantalla` });
  for (const t of smallTargets(await tapTargets(page)))
    out.push({ kind: "small-target", where, detail: `«${t.name}» ${px(t.width)}x${px(t.height)}` });
  return out;
}

export function errorIssues(errors: string[], where: string): Issue[] {
  return [...new Set(errors)].map((e) => ({ kind: "page-error" as const, where, detail: e.slice(0, 160) }));
}
