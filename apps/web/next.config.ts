import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./lib/i18n.ts");
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// In dev, Next.js React Fast Refresh evaluates code via eval() and connects an
// HMR websocket — both blocked by the production CSP, which silently breaks
// client hydration (forms/buttons go dead). Relax only in development;
// production keeps the strict policy unchanged.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";
const connectSrc = isDev
  ? `connect-src 'self' ${API_URL} ws: http://localhost:*`
  : `connect-src 'self' ${API_URL}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone server bundle for the production Docker image.
  output: "standalone",
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
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
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
