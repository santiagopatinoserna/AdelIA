import type { MetadataRoute } from "next";

import { locales } from "@/lib/i18n";
import { SITE_URL } from "@/lib/seo";

// Served at /robots.txt (file convention). Lives at the app root, outside
// [locale], so the path never falls through to the locale layout as HTML.
export default function robots(): MetadataRoute.Robots {
  // Private: the app itself, the auth-gated paywall and the API (lib/seo.ts).
  const disallow = [
    "/dashboard",
    "/billing",
    "/api",
    ...locales.flatMap((l) => [`/${l}/dashboard`, `/${l}/billing`]),
  ];
  return {
    rules: { userAgent: "*", allow: "/", disallow },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
