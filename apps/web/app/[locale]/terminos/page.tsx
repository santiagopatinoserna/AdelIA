import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Link } from "@/lib/navigation";
import { ArrowLeft } from "lucide-react";

import { publicPageAlternates } from "@/lib/seo";

// Server component (only translations + links): no client bundle for a
// static legal page, and generateMetadata can live in the same file.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "terms" });
  return {
    title: t("title"),
    description: t("intro"),
    alternates: publicPageAlternates(locale, "/terminos"),
  };
}

export default function TermsPage() {
  const t = useTranslations("terms");

  const sections = [
    ["whatTitle", "whatBody"],
    ["accountTitle", "accountBody"],
    ["trialTitle", "trialBody"],
    ["useTitle", "useBody"],
    ["dataTitle", "dataBody"],
    ["liabilityTitle", "liabilityBody"],
    ["lawTitle", "lawBody"],
  ] as const;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <header className="mx-auto flex max-w-6xl items-center justify-between border-b border-line px-6 py-6">
        <span className="font-display text-2xl font-semibold tracking-tight text-pine-900">
          Adel<span className="text-honey-500">IA</span>
        </span>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-ink-soft transition-colors hover:text-pine-700"
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} />
          {t("back")}
        </Link>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-2xl space-y-8 px-6 py-12 md:py-16">
        <div>
          <h1 className="text-balance font-display text-4xl leading-tight tracking-tight text-pine-900">
            {t("title")}
          </h1>
          <p className="mt-3 font-mono text-xs text-ink-faint">{t("updated")}</p>
          <p className="mt-6 text-lg leading-relaxed text-ink-soft">
            {t("intro")}
          </p>
        </div>

        <div className="space-y-8">
          {sections.map(([titleKey, bodyKey]) => (
            <section key={titleKey} className="ad-card p-6">
              <h2 className="font-display text-xl font-semibold text-pine-900">
                {t(titleKey)}
              </h2>
              <p className="mt-3 text-[15px] leading-relaxed text-ink">
                {t(bodyKey)}
              </p>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
