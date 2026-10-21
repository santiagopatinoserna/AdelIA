import type { Metadata } from "next";

import { defaultLocale, locales } from "./i18n";

// Single source of truth for the public origin: metadataBase (layout),
// robots.txt and sitemap.xml all derive from it.
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://adelia.godi.ai";

// Locale-less paths of the indexable pages. Everything under /dashboard,
// /billing and /api is private (see app/robots.ts).
//
// "/demo" is not here any more: the demo moved onto the landing (audit 4.6
// still holds, the product working without an account is what a search engine
// finds at "/") and /demo only redirects there.
export const PUBLIC_PATHS = ["", "/profesionales", "/privacidad", "/terminos"] as const;

// Canonical + hreflang for one public page. Relative URLs: Next resolves them
// against metadataBase, so dev/prod origins never leak into the code. The
// middleware's own Link header is disabled (middleware.ts) so this is the
// only hreflang the page emits.
export function publicPageAlternates(locale: string, path: string): Metadata["alternates"] {
  const languages: Record<string, string> = {};
  for (const l of locales) languages[l] = `/${l}${path}`;
  languages["x-default"] = `/${defaultLocale}${path}`;
  return { canonical: `/${locale}${path}`, languages };
}
