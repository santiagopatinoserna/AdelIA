import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Link } from "@/lib/navigation";
import { ArrowLeft } from "lucide-react";

import { ConsentControl } from "@/components/analytics";
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
  // Guests of the landing (2026-11-06): their own block of keys, drafted for
  // Santiago's review, rendered after the sections every account reads.
  const tg = useTranslations("guestSpace");

  const sections = [
    ["whatTitle", "whatBody"],
    ["whereTitle", "whereBody"],
    ["retentionTitle", "retentionBody"],
    ["recordingsTitle", "recordingsBody"],
    ["rightsTitle", "rightsBody"],
    // Audit 4.8. The page promised "no te rastreamos" (consented measurement
    // since 2026-11-07, analyticsBody below), and the funnel the
    // product needed could easily have broken that promise. It does not, and
    // the only way a reader can know is if the page says exactly what is
    // counted: a date, an event name and an integer, no cookie, no IP, no
    // identifier. The section sits BEFORE "Lo que nunca hacemos" so it is
    // read as part of the tracking answer, not as a footnote to it.
    ["countersTitle", "countersBody"],
    // Decision of 2026-11-07: the consented journey, right after the counters
    // so the two ways we measure read side by side. DRAFT for Santiago's
    // review (legal basis, the 13 months, the 3 years of proof).
    ["analyticsTitle", "analyticsBody"],
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
            <section
              key={titleKey}
              // The guest section links here instead of repeating the list.
              id={titleKey === "whereTitle" ? "encargados" : undefined}
              className="ad-card p-6"
            >
              <h2 className="font-display text-xl font-semibold text-ink">
                {t(titleKey)}
              </h2>
              <p className="mt-3 text-[15px] leading-relaxed text-ink">
                {t(bodyKey)}
              </p>
            </section>
          ))}
          {/* The second layer of the banner ("Detalles") and the footer's
              "Cookies" land here: what is stored, and the switch to change
              or withdraw the answer at any time. */}
          <section id="cookies" data-testid="privacy-cookies" className="ad-card scroll-mt-6 p-6">
            <h2 className="font-display text-xl font-semibold text-ink">{t("cookiesTitle")}</h2>
            <p className="mt-3 text-[15px] leading-relaxed text-ink">{t("cookiesBody")}</p>
            <h3 className="mt-5 text-base font-semibold text-ink">{t("cookiesChoiceTitle")}</h3>
            <div className="mt-2">
              <ConsentControl source="privacy" />
            </div>
          </section>
          <section id="sin-cuenta" data-testid="privacy-guest" className="ad-card p-6">
            <h2 className="font-display text-xl font-semibold text-ink">{tg("privacyTitle")}</h2>
            <p className="mt-3 text-[15px] leading-relaxed text-ink">
              {tg.rich("privacyBody", {
                processors: (chunks) => (
                  <a href="#encargados" className="underline underline-offset-4">{chunks}</a>
                ),
              })}
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
