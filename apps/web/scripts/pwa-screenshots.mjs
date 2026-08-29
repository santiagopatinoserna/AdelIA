// Regenerates the two manifest screenshots (public/screenshots/*-390x844.png,
// the "richer install UI" of Chrome on Android) from a RUNNING build, so the
// install sheet shows the app as it is: an old capture kept showing a header
// (language pill) the phone shell no longer has. Seeds a trial user and mints
// its session cookie exactly like e2e/utils/session.ts. Run it against the
// dev pair of scripts/server-verify.sh, then commit the PNGs:
//
//   cd apps/web && AUTH_SECRET=ci-only-secret E2E_BASE_URL=http://localhost:3004 \
//     node scripts/pwa-screenshots.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import { SignJWT } from "jose";
import { encode } from "next-auth/jwt";
import pg from "pg";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3004";
const SECRET = process.env.AUTH_SECRET ?? "ci-only-secret";
const COOKIE_NAME = "authjs.session-token";
const SHOTS = [
  ["/es/dashboard", "agent-home-390x844.png"],
  ["/es/dashboard/consulta/grabar", "grabar-consulta-390x844.png"],
];

const pool = new pg.Pool({
  host: process.env.POSTGRES_HOST ?? "localhost",
  port: Number(process.env.POSTGRES_PORT ?? "5434"),
  user: process.env.POSTGRES_USER ?? "adelia",
  password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
  database: process.env.POSTGRES_DB ?? "adelia",
});
const email = `pwa-shots-${Date.now()}@adelia.test`;
const { rows } = await pool.query(
  `INSERT INTO users (email, subscription_status, trial_end)
   VALUES ($1, 'trialing', now() + interval '30 days') RETURNING id`,
  [email],
);
const userId = rows[0].id;
const rawJwt = await new SignJWT({ sub: userId, email })
  .setProtectedHeader({ alg: "HS256" })
  .setIssuedAt()
  .setExpirationTime("1h")
  .sign(new TextEncoder().encode(SECRET));
const value = await encode({ token: { sub: userId, email, rawJwt }, secret: SECRET, salt: COOKIE_NAME });

const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
    locale: "es-ES",
  });
  await context.addCookies([
    { name: COOKIE_NAME, value, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax", secure: false },
  ]);
  const page = await context.newPage();
  for (const [route, file] of SHOTS) {
    await page.goto(BASE + route, { waitUntil: "networkidle" });
    // Settled UI: entrance animations done, nothing focused (no focus ring).
    await page.evaluate(() =>
      Promise.race([
        Promise.allSettled(document.getAnimations().map((a) => a.finished)),
        new Promise((r) => setTimeout(r, 2000)),
      ]),
    );
    await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : null));
    await page.waitForTimeout(300);
    const out = path.join(root, "public/screenshots", file);
    await page.screenshot({ path: out, fullPage: false });
    console.log(`${path.relative(root, out)}  <- ${route}`);
  }
  await context.close();
} finally {
  await browser.close();
  await pool.query(`DELETE FROM users WHERE id = $1`, [userId]);
  await pool.end();
}
