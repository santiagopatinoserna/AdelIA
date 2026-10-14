import { expect, test } from "@playwright/test";

import { getCorpusStats, resetCorpusStatsCache } from "@/lib/corpus-stats";

// Pure: no browser, no server. getCorpusStats takes its fetcher and clock as
// arguments, so every outcome of GET /clinical/corpus-stats is reproduced here.
// The landing prints these figures instead of a number typed in the catalogs
// (audit 1.1); what it must never do is print a wrong one, so every failure
// below ends in null or in the last good answer, never in a guess.

const GOOD = {
  sources: 127,
  chunks: 301,
  year_min: 1980,
  year_max: 2026,
  sources_without_year: 0,
  by_type: { guideline: 54, paper: 62, protocol: 3, reference: 8 },
};

function answer(body: unknown, status = 200): typeof fetch {
  return (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;
}

function counting(inner: typeof fetch): { fetcher: typeof fetch; calls: () => number } {
  let n = 0;
  return {
    fetcher: ((...args: Parameters<typeof fetch>) => {
      n += 1;
      return inner(...args);
    }) as typeof fetch,
    calls: () => n,
  };
}

test.beforeEach(() => resetCorpusStatsCache());

test("returns what the API counted", async () => {
  expect(await getCorpusStats({ fetcher: answer(GOOD), now: () => 0 })).toEqual(GOOD);
});

test("keeps a year range of null when no source has a year", async () => {
  const body = { ...GOOD, year_min: null, year_max: null, sources_without_year: 127 };
  expect(await getCorpusStats({ fetcher: answer(body), now: () => 0 })).toEqual(body);
});

test("asks the API once inside the freshness window and again after it", async () => {
  const c = counting(answer(GOOD));
  await getCorpusStats({ fetcher: c.fetcher, now: () => 0 });
  await getCorpusStats({ fetcher: c.fetcher, now: () => 4 * 60 * 1000 });
  expect(c.calls()).toBe(1);
  await getCorpusStats({ fetcher: c.fetcher, now: () => 6 * 60 * 1000 });
  expect(c.calls()).toBe(2);
});

test("is null, not a guess, when the API cannot answer", async () => {
  const down = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  expect(await getCorpusStats({ fetcher: down, now: () => 0 })).toBeNull();
  resetCorpusStatsCache();
  expect(await getCorpusStats({ fetcher: answer({ detail: "boom" }, 500), now: () => 0 })).toBeNull();
});

test("is null for a payload that does not match the contract", async () => {
  for (const body of [
    null,
    "127",
    {},
    { ...GOOD, sources: "127" },
    { ...GOOD, chunks: -1 },
    { ...GOOD, sources: 1.5 },
    { ...GOOD, year_min: "1980" },
    { ...GOOD, by_type: null },
  ]) {
    resetCorpusStatsCache();
    expect(await getCorpusStats({ fetcher: answer(body), now: () => 0 })).toBeNull();
  }
});

test("an empty corpus has nothing to advertise", async () => {
  const empty = { ...GOOD, sources: 0, chunks: 0, year_min: null, year_max: null };
  expect(await getCorpusStats({ fetcher: answer(empty), now: () => 0 })).toBeNull();
});

test("serves the last good figure when a refresh fails", async () => {
  await getCorpusStats({ fetcher: answer(GOOD), now: () => 0 });
  const down = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  expect(await getCorpusStats({ fetcher: down, now: () => 10 * 60 * 1000 })).toEqual(GOOD);
});

test("does not wait out the timeout on every render while the API is down", async () => {
  const down = counting((async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch);
  await getCorpusStats({ fetcher: down.fetcher, now: () => 0 });
  await getCorpusStats({ fetcher: down.fetcher, now: () => 10_000 });
  expect(down.calls()).toBe(1);
  await getCorpusStats({ fetcher: down.fetcher, now: () => 40_000 });
  expect(down.calls()).toBe(2);
});
