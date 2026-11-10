import { expect, test } from "@playwright/test";

import {
  MOBILE_CPU_RATE,
  MOBILE_NETWORK,
  PERF_SAMPLES,
  type PerfPage,
  type PerfSample,
  VIEWPORTS,
  median,
  perfIssues,
} from "./kit";
import { issues, needGuest, note, openContext, record } from "./page";

// A mid-range phone on a slow 4G line (kit.MOBILE_*), a cold cache every
// load: the landing's and the panel's largest paint, how long until the field
// takes what she types (React has hydrated it), and the JavaScript each page
// downloads. Medians of PERF_SAMPLES loads against kit.PERF_LIMITS.

const PAGES: { name: PerfPage; path: string; guest: boolean; field: string | null }[] = [
  { name: "landing", path: "/es", guest: false, field: "#demo-question" },
  { name: "panel", path: "/es/dashboard", guest: true, field: "[data-testid=agent-canvas] textarea" },
  { name: "settings", path: "/es/dashboard/settings", guest: true, field: null },
  { name: "privacy", path: "/es/privacidad", guest: false, field: null },
];

for (const p of PAGES) {
  test(`45.${p.name} Rendimiento en móvil`, async ({ browser, baseURL }) => {
    if (p.guest) needGuest();
    const samples: Required<PerfSample>[] = [];
    for (let i = 0; i < PERF_SAMPLES; i++) {
      const { context, page } = await openContext(browser, {
        viewport: VIEWPORTS[1], scheme: "light", locale: "es", guest: p.guest, baseURL: baseURL!,
      });
      try {
        const cdp = await context.newCDPSession(page);
        await cdp.send("Network.enable");
        await cdp.send("Network.emulateNetworkConditions", MOBILE_NETWORK);
        await cdp.send("Emulation.setCPUThrottlingRate", { rate: MOBILE_CPU_RATE });
        await page.addInitScript((field) => {
          const w = window as unknown as { __lcp: number; __typeReady: number | null };
          w.__lcp = 0;
          w.__typeReady = null;
          new PerformanceObserver((list) => {
            for (const e of list.getEntries()) w.__lcp = e.startTime;
          }).observe({ type: "largest-contentful-paint", buffered: true });
          if (!field) return;
          // Typing counts once React owns the field: before hydration the
          // letters land in a box whose state is about to be replaced.
          const tick = () => {
            const el = document.querySelector(field) as HTMLTextAreaElement | null;
            if (el && !el.disabled && Object.keys(el).some((k) => k.startsWith("__reactProps"))) {
              w.__typeReady = performance.now();
              return;
            }
            setTimeout(tick, 25);
          };
          tick();
        }, p.field);
        await page.goto(p.path, { waitUntil: "load", timeout: 120_000 });
        if (p.field)
          await page.waitForFunction(() => (window as unknown as { __typeReady: number | null }).__typeReady !== null, null, { timeout: 60_000 });
        await page.waitForTimeout(1500);
        const m = await page.evaluate(() => {
          const w = window as unknown as { __lcp: number; __typeReady: number | null };
          const js = performance
            .getEntriesByType("resource")
            .filter((r) => (r as PerformanceResourceTiming).initiatorType === "script" || /\.js(\?|$)/.test(r.name))
            .reduce((n, r) => n + ((r as PerformanceResourceTiming).transferSize || (r as PerformanceResourceTiming).encodedBodySize), 0);
          return { lcpMs: w.__lcp, typeMs: w.__typeReady ?? 0, jsKB: js / 1024 };
        });
        samples.push(m);
      } finally {
        await context.close();
      }
    }
    const med: PerfSample = {
      lcpMs: median(samples.map((s) => s.lcpMs)),
      jsKB: median(samples.map((s) => s.jsKB)),
      ...(p.field ? { typeMs: median(samples.map((s) => s.typeMs)) } : {}),
    };
    record({
      type: "metric", section: "perf", key: p.name,
      values: {
        lcpMs: Math.round(med.lcpMs!),
        typeMs: med.typeMs === undefined ? "" : Math.round(med.typeMs),
        jsKB: Math.round(med.jsKB!),
        muestras_lcp: samples.map((s) => Math.round(s.lcpMs)).join(" / "),
      },
    });
    const found = issues(perfIssues(p.name, med));
    note(`median LCP ${Math.round(med.lcpMs!)} ms, type ${med.typeMs === undefined ? "-" : Math.round(med.typeMs)} ms, JS ${Math.round(med.jsKB!)} KB`);
    expect(found).toEqual([]);
  });
}
