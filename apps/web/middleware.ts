import createMiddleware from "next-intl/middleware";
import type { NextRequest } from "next/server";

import { locales, defaultLocale } from "./lib/i18n";

const intl = createMiddleware({
  locales,
  defaultLocale,
  localePrefix: "always",
  // hreflang lives in the <head> of the public pages (lib/seo.ts); the
  // header variant would duplicate it and also tag private dashboard routes.
  alternateLinks: false,
});

// Pages that print an email address in their text leave here with
// `no-transform`. Cloudflare sits in front of adelia.godi.ai and its Email
// Address Obfuscation (on by default) rewrites every address in the HTML into
// a "[email protected]" link plus a decode script, so the text React hydrates
// is not the text the server rendered: React #418 on every visit to
// /dashboard/settings, whose danger zone reads "Escribe <email> para
// confirmar" (prod journey 2026-11-06). Next hydrates while the HTML still
// streams, so whether the decode script wins the race decides the rest; the
// legal pages print security@godi.ai and run the same risk. Cloudflare leaves
// a response with `Cache-Control: no-transform` as the server wrote it.
//
// Only these pages: Next's compression and Cloudflare's both skip a
// no-transform response, and every other page keeps its gzip. The rest of the
// value is what Next sends for them anyway (all render on demand); Next only
// writes its own Cache-Control when none is set, so this one carries it all.
// e2e/trial-account-hydration.spec.ts checks the header and walks the app
// behind a simulated Cloudflare, so a page that breaks the same way fails there.
const NO_TRANSFORM_CACHE_CONTROL =
  "private, no-cache, no-store, max-age=0, must-revalidate, no-transform";
const PRINTS_AN_ADDRESS = new RegExp(
  `^/(${locales.join("|")})/(dashboard/settings|privacidad|terminos|profesionales)/?$`,
);

export default function middleware(request: NextRequest) {
  const response = intl(request);
  if (PRINTS_AN_ADDRESS.test(request.nextUrl.pathname)) {
    response.headers.set("Cache-Control", NO_TRANSFORM_CACHE_CONTROL);
  }
  return response;
}

export const config = { matcher: ["/((?!api|_next|.*\\..*).*)"] };
