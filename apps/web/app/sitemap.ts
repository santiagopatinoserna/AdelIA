import type { MetadataRoute } from "next";

import { defaultLocale, locales } from "@/lib/i18n";
import { PUBLIC_PATHS, SITE_URL } from "@/lib/seo";

// Served at /sitemap.xml. One entry per locale and public page, each carrying
// the hreflang alternates of its siblings (x-default = Spanish).
export default function sitemap(): MetadataRoute.Sitemap {
  const entries: MetadataRoute.Sitemap = [];
  for (const path of PUBLIC_PATHS) {
    const languages: Record<string, string> = {};
    for (const l of locales) languages[l] = `${SITE_URL}/${l}${path}`;
    languages["x-default"] = `${SITE_URL}/${defaultLocale}${path}`;
    for (const locale of locales) {
      entries.push({
        url: `${SITE_URL}/${locale}${path}`,
        changeFrequency: path === "" ? "weekly" : "monthly",
        priority: path === "" ? 1 : 0.5,
        alternates: { languages },
      });
    }
  }
  return entries;
}
