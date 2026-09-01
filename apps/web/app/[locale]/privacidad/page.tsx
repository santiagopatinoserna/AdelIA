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
  const t = await getTranslations({ locale, namespace: "privacy" });
  return {
    title: t("title"),
    description: t("metaDescription"),
    alternates: publicPageAlternates(locale, "/privacidad"),
  };
}

export default function PrivacyPage() {
  const t = useTranslations("privacy");

  const sections = [
    ["whatTitle", "whatBody"],
    ["whereTitle", "whereBody"],
    ["retentionTitle", "retentionBody"],
    ["recordingsTitle", "recordingsBody"],
    ["rightsTitle", "rightsBody"],
    // Audit 4.8. The page promises "no te rastreamos", and the funnel the
    // product needed could easily have broken that promise. It does not, and
    // the only way a reader can know is if the page says exactly what is
    // counted: a date, an event name and an integer, no cookie, no IP, no
    // identifier. The section sits BEFORE "Lo que nunca hacemos" so it is
    // read as part of the tracking answer, not as a footnote to it.
    ["countersTitle", "countersBody"],
    ["neverTitle", "neverBody"],
    ["contactTitle", "contactBody"],
  ] as const;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <header className="mx-auto flex max-w-6xl items-center justify-between border-b border-line px-6 py-6">
        <span className="font-display text-2xl font-semibold tracking-tight text-ink">
          Adel<span className="text-accent-text">IA</span>
        </span>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-ink-soft transition-colors hover:text-primary-text-hover"
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} />
          {t("back")}
        </Link>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-2xl space-y-8 px-6 py-12 md:py-16">
        <div>
          <h1 className="text-balance font-display text-4xl leading-tight tracking-tight text-ink">
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
              <h2 className="font-display text-xl font-semibold text-ink">
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
