// Our own short links for the social networks: /r/<code> (2026-11-08). The
// table lives in the API (apps/api/adelia/services/short_links.py); this is
// what the web needs before asking it. app/r/[code]/route.ts uses both.

/** A code is a few letters and digits; anything else is not worth a request. */
export function looksLikeCode(code: string): boolean {
  return /^[a-z0-9]{1,16}$/i.test(code);
}

// Link previews (the card a chat app or a network draws when the link is
// pasted), crawlers and checkers. They are sent where the link goes, so the
// preview is right, but they are not counted: a click is a person. In-app
// browsers (Instagram, TikTok's "BytedanceWebview") are people and do not
// match. Same spirit as the API's bot filter (services/analytics._BOT_UA).
const PREVIEW_FETCHER = new RegExp(
  [
    "bot", "crawl", "spider", "slurp", "headless", "lighthouse", "preview",
    "facebookexternalhit", "facebookcatalog", "meta-externalagent", "embedly", "whatsapp",
    "curl", "wget", "python-", "httpx", "aiohttp", "axios", "node-fetch", "go-http", "java/",
    "okhttp", "scrapy", "phantomjs", "puppeteer", "playwright", "selenium", "pingdom",
    "uptime", "monitor",
  ].join("|"),
  "i",
);

export function isLinkPreviewFetcher(userAgent: string | null | undefined): boolean {
  const ua = (userAgent ?? "").trim();
  return ua === "" || PREVIEW_FETCHER.test(ua);
}
