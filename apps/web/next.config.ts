import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./lib/i18n.ts");
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// One id per `next build`, shared by Next's BUILD_ID, the client bundle
// (NEXT_PUBLIC_BUILD_ID) and GET /api/version. The service worker is
// registered as /sw.js?v=<id> and names its cache after it, so every deploy
// installs a fresh worker, purges the previous build's cache on activation
// and lets an open tab learn about the new version (components/sw-register).
// ADELIA_BUILD_ID overrides it (a git sha, for instance); the Docker build
// context has no .git, hence the UTC timestamp default (yyyymmddHHMMss: with
// seconds, so two builds started inside the same minute never share an id,
// a shared id meant the same /sw.js?v= and cache for two different bundles).
const BUILD_ID =
  process.env.ADELIA_BUILD_ID?.trim() ||
  new Date().toISOString().replace(/\D/g, "").slice(0, 14);

// In dev, Next.js React Fast Refresh evaluates code via eval() and connects an
// HMR websocket — both blocked by the production CSP, which silently breaks
// client hydration (forms/buttons go dead). Relax only in development;
// production keeps the strict policy unchanged.
//
// Cloudflare injects its Web Analytics beacon (static.cloudflareinsights.com/
// beacon.min.js, which posts to cloudflareinsights.com/cdn-cgi/rum) into every
// HTML response of adelia.godi.ai; nothing in this repository loads it. The
// privacy policy promises no tracking, so the beacon has to be switched off in
// the Cloudflare dashboard (README, "Cloudflare Web Analytics"). Until then the
// two origins below keep the console free of a CSP error on every page; drop
// them from script-src / connect-src once the beacon is off.
const CF_BEACON_SCRIPT = "https://static.cloudflareinsights.com";
const CF_BEACON_CONNECT = "https://cloudflareinsights.com";
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : `script-src 'self' 'unsafe-inline' ${CF_BEACON_SCRIPT}`;
const connectSrc = isDev
  ? `connect-src 'self' ${API_URL} ws: http://localhost:*`
  : `connect-src 'self' ${API_URL} ${CF_BEACON_CONNECT}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone server bundle for the production Docker image.
  output: "standalone",
  generateBuildId: async () => BUILD_ID,
  env: { NEXT_PUBLIC_BUILD_ID: BUILD_ID },
  // pg is Node-only; keep it out of webpack bundles (auth adapter uses it)
  serverExternalPackages: ["pg"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=()" },
          {
            key: "Content-Security-Policy",
            // 'unsafe-inline' script-src is the Next.js hydration baseline;
            // nonce-based CSP is the hardening follow-up. connect-src allows
            // the public API origin (share PDF links).
            value: [
              "default-src 'self'",
              scriptSrc,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              connectSrc,
              "font-src 'self' data:",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};
export default withNextIntl(nextConfig);
