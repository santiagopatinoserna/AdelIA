import type { MetadataRoute } from "next";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { NextResponse } from "next/server";

import { locales } from "@/lib/i18n";

// /es|en|fr/manifest.webmanifest, linked from the explicit <head> of the
// locale layout. One manifest per language so the install sheet, the
// long-press shortcuts and the screenshot labels speak the user's language
// (a single Spanish app/manifest.ts served /en and /fr in Spanish). `id`,
// `scope` and the locale-less start_url / shortcut URLs are identical in the
// three, so it is ONE installed app whichever language it was installed
// from, and it opens in the language last chosen (NEXT_LOCALE cookie, via
// the middleware). The path has a dot, so the middleware never rewrites it,
// and being a static segment it wins over the [...rest] catch-all.
export const dynamic = "force-static";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

const SHORTCUT_ICONS = [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }];

export async function GET(_req: Request, { params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!hasLocale(locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "manifest" });

  const manifest: MetadataRoute.Manifest = {
    id: "/",
    name: t("name"),
    short_name: "AdelIA",
    description: t("description"),
    lang: locale,
    dir: "ltr",
    scope: "/",
    start_url: "/dashboard?source=pwa",
    display: "standalone",
    orientation: "portrait",
    // A manifest colour cannot be per scheme (there is no media syntax here),
    // and it is only read for the Android splash and the task-switcher tile
    // BEFORE the page paints. Both stay on the light canvas, which is also
    // what the light `themeColor` in the locale layout declares; once the page
    // is up, the per-scheme <meta name="theme-color"> takes over.
    background_color: "#f4f1e9",
    theme_color: "#f4f1e9",
    categories: ["health", "medical", "productivity"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/icon-512-maskable.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      {
        name: t("recordName"),
        short_name: t("recordShort"),
        description: t("recordDesc"),
        url: "/dashboard/consulta/grabar?source=pwa",
        icons: SHORTCUT_ICONS,
      },
      {
        name: t("diaryName"),
        short_name: t("diaryShort"),
        description: t("diaryDesc"),
        url: "/dashboard/ingestion/telegram?source=pwa",
        icons: SHORTCUT_ICONS,
      },
      {
        name: t("uploadName"),
        short_name: t("uploadShort"),
        description: t("uploadDesc"),
        url: "/dashboard/upload?source=pwa",
        icons: SHORTCUT_ICONS,
      },
    ],
    // 390x844 captures of the phone shell; scripts/pwa-screenshots.mjs
    // regenerates them whenever the header or these screens change.
    screenshots: [
      {
        src: "/screenshots/agent-home-390x844.png",
        sizes: "390x844",
        type: "image/png",
        form_factor: "narrow",
        label: t("screenshotAgent"),
      },
      {
        src: "/screenshots/grabar-consulta-390x844.png",
        sizes: "390x844",
        type: "image/png",
        form_factor: "narrow",
        label: t("screenshotRecord"),
      },
    ],
  };

  return NextResponse.json(manifest, {
    headers: {
      "Content-Type": "application/manifest+json",
      "Cache-Control": "public, max-age=0, must-revalidate",
    },
  });
}
