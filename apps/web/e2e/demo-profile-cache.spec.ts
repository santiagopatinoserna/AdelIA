import { expect, test } from "@playwright/test";
import { loadDemoProfile, resetDemoProfileCache } from "@/lib/demo-profile";

// No API, browser, account, or LLM. Patch only the HTTP boundary.
const originalFetch = globalThis.fetch;
const originalNow = Date.now;
const GOOD = {
  is_demo: true, baby_name: "Lucía", age_label: "5 meses", banner: "Datos ficticios",
  record_title: "Historial ficticio", record_note: "Ejemplo", suggested: ["Pregunta"],
  items: [{ kind: "report", title: "Informe", meta: "Ejemplo", date: "2026-10-01", lines: [] }],
};

test.beforeEach(() => resetDemoProfileCache());

test.afterEach(() => {
  globalThis.fetch = originalFetch;
  Date.now = originalNow;
});

test("reuses the public fictional fixture for repeated and concurrent visits", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls++;
    await new Promise(resolve => setTimeout(resolve, 10));
    return Response.json(GOOD);
  }) as typeof fetch;
  const profiles = await Promise.all(Array.from({ length: 8 }, () => loadDemoProfile("es")));
  expect(profiles).toEqual(Array(8).fill(GOOD));
  expect(await loadDemoProfile("es")).toEqual(GOOD);
  expect(calls).toBe(1);
});

test("expires after one minute and never reuses yesterday's dates", async () => {
  let now = Date.UTC(2026, 9, 21, 23, 59, 30);
  Date.now = () => now;
  let calls = 0;
  globalThis.fetch = (async () => { calls++; return Response.json(GOOD); }) as typeof fetch;
  await loadDemoProfile("es");
  now += 31_000;
  await loadDemoProfile("es");
  expect(calls).toBe(2);
  now += 61_000;
  await loadDemoProfile("es");
  expect(calls).toBe(3);
});

test("isolates locale entries and keeps the API locale fallback", async () => {
  const urls: string[] = [];
  globalThis.fetch = (async (url) => {
    urls.push(String(url));
    return Response.json({ ...GOOD, baby_name: new URL(String(url)).searchParams.get("locale") });
  }) as typeof fetch;
  for (const locale of ["es", "en", "fr"]) await loadDemoProfile(locale);
  expect((await loadDemoProfile("EN-gb"))?.baby_name).toBe("en");
  expect((await loadDemoProfile("invalid"))?.baby_name).toBe("es");
  expect(urls.map(url => new URL(url).searchParams.get("locale"))).toEqual(["es", "en", "fr"]);
});

test("rejects non-fictional or malformed profiles instead of caching them", async () => {
  for (const body of [{ ...GOOD, is_demo: false }, {}, { ...GOOD, items: null }]) {
    globalThis.fetch = (async () => Response.json(body)) as typeof fetch;
    expect(await loadDemoProfile("es")).toBeNull();
  }
  globalThis.fetch = (async () => Response.json(GOOD)) as typeof fetch;
  expect(await loadDemoProfile("es")).toEqual(GOOD);
});

test("does not cache HTTP, network or JSON failures", async () => {
  for (const fetcher of [
    async () => new Response("down", { status: 503 }),
    async () => { throw new TypeError("offline"); },
    async () => new Response("not json"),
  ]) {
    globalThis.fetch = fetcher as typeof fetch;
    expect(await loadDemoProfile("es")).toBeNull();
  }
  globalThis.fetch = (async () => Response.json(GOOD)) as typeof fetch;
  expect(await loadDemoProfile("es")).toEqual(GOOD);
});

test("sets a bounded timeout and never sends credentials", async () => {
  let options: RequestInit | undefined;
  globalThis.fetch = (async (_url, init) => { options = init; return Response.json(GOOD); }) as typeof fetch;
  await loadDemoProfile("es");
  expect(options?.credentials).toBe("omit");
  expect(options?.cache).toBe("no-store");
  expect(options?.signal).toBeInstanceOf(AbortSignal);
});

test("a stalled public API returns unavailable within the bounded timeout", async () => {
  globalThis.fetch = (async (_url, options) => new Promise<Response>((_resolve, reject) => {
    options?.signal?.addEventListener("abort", () => reject(options.signal?.reason), { once: true });
  })) as typeof fetch;
  const start = performance.now();
  expect(await loadDemoProfile("es")).toBeNull();
  expect(performance.now() - start).toBeLessThan(3500);
});
