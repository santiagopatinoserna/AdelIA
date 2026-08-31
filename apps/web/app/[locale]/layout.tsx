import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import type { Metadata, Viewport } from "next";
import { Fraunces, Hanken_Grotesk } from "next/font/google";

import { ServiceWorkerRegister } from "@/components/sw-register";
import { locales } from "@/lib/i18n";
import { IOS_SPLASH } from "@/lib/ios-splash";
import { SITE_URL } from "@/lib/seo";
import "../globals.css";

// Distinctive editorial pairing: characterful serif display + humanist sans.
// Both are variable on the weight axis ONLY. Fraunces with the extra `opsz`
// and `SOFT` axes was a 121 KB latin woff2 (36 % of the landing's transfer
// and its LCP element); weight-only is 37 KB and still renders the 540/560
// weights globals.css asks for. Google serves that same variable file for an
// explicit weight list, so "variable" costs nothing over listing 400/500/600.
const fraunces = Fraunces({
  subsets: ["latin"],
  weight: "variable",
  style: ["normal"],
  variable: "--font-fraunces",
  display: "swap",
  preload: true,
});
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  weight: "variable",
  style: ["normal"],
  variable: "--font-hanken",
  display: "swap",
  preload: true,
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(locales, locale)) notFound();
  const c = await getTranslations({ locale, namespace: "common" });
  const h = await getTranslations({ locale, namespace: "home" });
  // Middle dot, the same separator as the sub-page template below: no em
  // dashes in user-facing text (tab title, og/twitter title, search snippet).
  const title = `${c("appName")} · ${c("tagline")}`;
  const description = `${h("hero")} ${h("subhero")}`;
  return {
    metadataBase: new URL(SITE_URL),
    title: { default: title, template: `%s · ${c("appName")}` },
    description,
    applicationName: "AdelIA",
    // The manifest link, apple-touch-icon, startup images and the
    // apple-mobile-web-app-* tags are written in the explicit <head> below,
    // not here. The manifest is per locale (app/[locale]/manifest.webmanifest),
    // so there is no app/manifest.ts and Next emits no manifest link of its own.
    icons: {
      icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    },
    openGraph: {
      type: "website",
      siteName: "AdelIA",
      title,
      description,
      locale,
      // og:image comes from the file-based app/[locale]/opengraph-image.tsx
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

export const viewport: Viewport = {
  // One entry per scheme, so the browser chrome (iOS status bar, Android task
  // switcher) follows the page instead of painting deep pine over a cream
  // daytime UI. Values are --color-canvas in each scheme (globals.css).
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f1e9" },
    { media: "(prefers-color-scheme: dark)", color: "#071813" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // The on-screen keyboard shrinks the layout viewport (100dvh follows it)
  // instead of overlaying the page, so fixed bars and the chat input stay
  // above the keyboard. MobileBottomNav hides itself while a text field has
  // focus AND the visual viewport has actually shrunk (a keyboard, not a mere
  // focus: physical keyboards and Android's Back key never blur the field).
  interactiveWidget: "resizes-content",
};

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // The middleware skips paths with a dot (/robots.txt, /foo.txt, /favicon.ico),
  // so they reach this layout with the bogus "locale" as the segment. Without
  // this guard they rendered the Spanish home with a 200 and lang="foo.txt".
  if (!hasLocale(locales, locale)) notFound();
  const messages = await getMessages();
  return (
    <html lang={locale} className={`${fraunces.variable} ${hanken.variable}`}>
      <head>
        {/* Anti-flash, before any paint: if the reader has explicitly chosen a
            scheme (the switcher stores "light" | "dark" under `adelia-theme`;
            absent = follow the system), stamp it on <html> so the dark tokens
            win from the first frame and opening the app at 3 a.m. never fires
            a white flash. No dependency, no library. If localStorage throws
            (private mode, storage blocked) the catch leaves the system
            scheme, which is the correct fallback. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('adelia-theme');if(t==='dark'||t==='light')document.documentElement.dataset.theme=t}catch(e){}",
          }}
        />
        {/* Explicit on purpose. Next 15.5 streams `metadata` into the <body>
            for regular user agents (React hoists it later), but Chrome only
            honours a manifest link that is inside <head> at parse time and
            Safari reads apple-mobile-web-app-* the same way: with these in
            `metadata` the PWA was not installable (LH11 PWA 0.38 on /es).
            scripts/server-verify.sh and deploy-prod.sh curl this. */}
        <link rel="manifest" href={`/${locale}/manifest.webmanifest`} />
        <link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png" />
        {/* Startup image = the splash iOS shows while the installed app boots
            (Android derives its own from the manifest). iOS only uses an image
            whose pixel size matches the device exactly, hence one <link> per
            iPhone class; the PNGs come from scripts/gen-ios-splash.mjs. */}
        {IOS_SPLASH.map(({ w, h, r }) => (
          <link
            key={`${w}x${h}@${r}x`}
            rel="apple-touch-startup-image"
            media={`screen and (device-width: ${w}px) and (device-height: ${h}px) and (-webkit-device-pixel-ratio: ${r}) and (orientation: portrait)`}
            href={`/icons/splash/${w}x${h}@${r}x.png`}
          />
        ))}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        {/* "default" keeps the iOS status bar legible in BOTH schemes: it
            follows themeColor above. "black-translucent" would paint the
            status bar over the header. */}
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="AdelIA" />
      </head>
      <body className="antialiased">
        <NextIntlClientProvider messages={messages}>
          {children}
          {/* Inside the provider: it renders the translated "new version" notice. */}
          <ServiceWorkerRegister />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
