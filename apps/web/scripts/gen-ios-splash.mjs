// Renders the iOS startup images (apple-touch-startup-image) into
// public/icons/splash from app/icon.svg: the manifest's background colour
// with the icon centred, one PNG per iPhone class of lib/ios-splash.ts,
// because iOS only shows a startup image whose pixel size matches the
// device exactly. Playwright's Chromium does the rasterising (no new deps).
//
//   cd apps/web && node scripts/gen-ios-splash.mjs
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BACKGROUND = "#f4f1e9"; // manifest background_color
const ICON_RATIO = 0.28; // icon side as a fraction of the screen width

// Same list as lib/ios-splash.ts (a .ts import would need a TS loader here).
const src = readFileSync(path.join(root, "lib/ios-splash.ts"), "utf8");
const SIZES = [...src.matchAll(/\{\s*w:\s*(\d+),\s*h:\s*(\d+),\s*r:\s*(\d+)\s*\}/g)].map((m) => ({
  w: Number(m[1]),
  h: Number(m[2]),
  r: Number(m[3]),
}));
if (SIZES.length === 0) throw new Error("no sizes found in lib/ios-splash.ts");

const svg = readFileSync(path.join(root, "app/icon.svg"), "utf8");
const icon = `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
const out = path.join(root, "public/icons/splash");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
try {
  for (const { w, h, r } of SIZES) {
    const context = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: r });
    const page = await context.newPage();
    const side = Math.round(w * ICON_RATIO);
    await page.setContent(
      `<!doctype html><html><head><meta name="viewport" content="width=device-width"></head>` +
        `<body style="margin:0;width:${w}px;height:${h}px;background:${BACKGROUND};display:flex;align-items:center;justify-content:center">` +
        `<img src="${icon}" width="${side}" height="${side}" style="display:block" alt=""></body></html>`,
    );
    const file = path.join(out, `${w}x${h}@${r}x.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`${path.relative(root, file)}  ${w * r}x${h * r}px`);
    await context.close();
  }
} finally {
  await browser.close();
}
