import { expect, test } from "@playwright/test";
import { Pool } from "pg";

import { isLinkPreviewFetcher, looksLikeCode } from "../lib/short-links";

// Our own short links for the social networks (2026-11-08): /r/<code> goes to
// the landing with the UTM values of the community plan and counts the click
// in the anonymous funnel (apps/api/adelia/services/short_links.py). No cookie
// and no identifier, so the count holds even for a visitor who never answers
// the analytics banner. Link previews are resolved and not counted. An
// unknown code goes to the landing without an error.

const G02 =
  "/es?utm_source=redes&utm_medium=social&utm_campaign=lanzamiento_2026_11&utm_content=g02_fiebre3m";
const PHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";

function pool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

/** Today's count of one link, in UTC like services/funnel. */
async function clicks(code: string): Promise<number> {
  const db = pool();
  try {
    const res = await db.query(
      `SELECT count FROM funnel_counters
        WHERE day = (now() AT TIME ZONE 'UTC')::date AND event = $1`,
      [`link_${code}`],
    );
    return Number(res.rows[0]?.count ?? 0);
  } finally {
    await db.end();
  }
}

test.describe("pure", () => {
  test("link previews and checkers are told apart from people", () => {
    for (const ua of [
      "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
      "WhatsApp/2.23.20.0 A",
      "TelegramBot (like TwitterBot)",
      "Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com)",
      "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
      "curl/8.4.0",
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0 Safari/537.36",
      "",
    ]) {
      expect(isLinkPreviewFetcher(ua), ua).toBe(true);
    }
    for (const ua of [
      PHONE_UA,
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 300.0.0",
      "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36 musical_ly_2023 BytedanceWebview/d8a21c6",
    ]) {
      expect(isLinkPreviewFetcher(ua), ua).toBe(false);
    }
  });

  test("only a short plain code is worth asking the API about", () => {
    for (const code of ["g02", "G02", "ig", "g10"]) expect(looksLikeCode(code), code).toBe(true);
    for (const code of ["", "../es", "g02?x", "a".repeat(40), "g 02", "%2e%2e"]) {
      expect(looksLikeCode(code), code).toBe(false);
    }
  });
});

test.describe("against the stack", () => {
  test.use({ userAgent: PHONE_UA });

  test("a piece code goes to the landing with its UTM and counts one click", async ({ request }) => {
    const before = await clicks("g02");
    const res = await request.get("/r/g02", { maxRedirects: 0 });

    expect(res.status()).toBe(302);
    expect(res.headers()["location"]).toBe(G02);
    expect(res.headers()["set-cookie"]).toBeUndefined();
    expect(res.headers()["cache-control"]).toContain("no-store");
    await expect.poll(() => clicks("g02")).toBe(before + 1);

    // As people type it.
    const upper = await request.get("/r/G02", { maxRedirects: 0 });
    expect(upper.headers()["location"]).toBe(G02);
    await expect.poll(() => clicks("g02")).toBe(before + 2);
  });

  test("a bio code names its network", async ({ request }) => {
    const res = await request.get("/r/tt", { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(res.headers()["location"]).toBe(
      "/es?utm_source=tiktok&utm_medium=bio&utm_campaign=lanzamiento_2026_11&utm_content=perfil",
    );
  });

  test("a link preview is sent to the same place and not counted", async ({ playwright, baseURL }) => {
    const bot = await playwright.request.newContext({
      baseURL,
      userAgent: "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    });
    const before = await clicks("g05");
    const res = await bot.get("/r/g05", { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(res.headers()["location"]).toContain("utm_content=g05_verdura");
    await bot.dispose();
    // Give a stray count the time it would need to land.
    await new Promise((r) => setTimeout(r, 500));
    expect(await clicks("g05")).toBe(before);
  });

  test("an unknown code goes to the landing, no error, nothing counted", async ({ request }) => {
    for (const code of ["nope", "g11", "x".repeat(60)]) {
      const res = await request.get(`/r/${code}`, { maxRedirects: 0 });
      expect(res.status(), code).toBe(302);
      expect(res.headers()["location"], code).toBe("/");
    }
    const db = pool();
    try {
      const res = await db.query(
        "SELECT count(*) AS n FROM funnel_counters WHERE event IN ('link_nope', 'link_g11')",
      );
      expect(Number(res.rows[0].n)).toBe(0);
    } finally {
      await db.end();
    }
  });

  test("followed in a browser it lands on the landing with the UTM in the address", async ({ page }) => {
    await page.goto("/r/g09");
    await expect(page).toHaveURL(/\/es\?utm_source=redes&utm_medium=social&utm_campaign=lanzamiento_2026_11&utm_content=g09_grabar$/);
    await expect(page.getByTestId("landing-record")).toBeVisible();
    const cookies = await page.context().cookies();
    expect(cookies.filter((c) => /utm|link|visitor/i.test(c.name))).toEqual([]);
  });
});
