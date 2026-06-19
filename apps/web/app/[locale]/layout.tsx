import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import type { Metadata, Viewport } from "next";
import { Fraunces, Hanken_Grotesk } from "next/font/google";

import { ServiceWorkerRegister } from "@/components/sw-register";
import "../globals.css";

// Distinctive editorial pairing — characterful serif display + humanist sans.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  axes: ["opsz", "SOFT"],
});
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
  display: "swap",
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const c = await getTranslations({ locale, namespace: "common" });
  const h = await getTranslations({ locale, namespace: "home" });
  const title = `${c("appName")} — ${c("tagline")}`;
  const description = `${h("hero")} ${h("subhero")}`;
  return {
    metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://adelia.godi.ai"),
    title: { default: title, template: `%s · ${c("appName")}` },
    description,
    applicationName: "AdelIA",
    appleWebApp: { capable: true, title: "AdelIA", statusBarStyle: "default" },
    icons: {
      icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
      apple: "/icons/apple-touch-icon.png",
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
  themeColor: "#0a2820",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const messages = await getMessages();
  return (
    <html lang={locale} className={`${fraunces.variable} ${hanken.variable}`}>
      <body className="antialiased">
        <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
