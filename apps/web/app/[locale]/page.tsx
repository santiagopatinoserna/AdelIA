import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { ArrowRight } from "lucide-react";

import { FunnelVisit, StartLink } from "@/components/funnel";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { getCorpusStats } from "@/lib/corpus-stats";
import { Link } from "@/lib/navigation";
import { publicPageAlternates } from "@/lib/seo";

// Rendered per request, never frozen at build time: the corpus figures come
// from the API (GET /clinical/corpus-stats), which is not running during
// `next build`, and a page prerendered without them would stay that way.
export const dynamic = "force-dynamic";

const GITHUB_URL = "https://github.com/santiagopatinoserna/AdelIA";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "home" });
  return {
    description: t("metaDescription"),
    alternates: publicPageAlternates(locale, ""),
  };
}

/*
 * The landing says four things and then stops, because the reader is a mother
 * with a phone, often at night:
 *
 *   1. what AdelIA is, and the way to try it without an account (hero);
 *   2. proof that it does not invent answers (one real answer with its source);
 *   3. where the answers come from, in numbers counted by the API (#evidence);
 *   4. what it costs, with the trial terms (#pricing).
 *
 * The footer stays whole: the clinical disclaimer and the privacy and terms
 * links are not optional on a health product.
 *
 * Removed on purpose, not folded: "a day with AdelIA", the three feature
 * cards, the two-modes block, the history timeline, the comparison with a
 * generic chatbot and the open-source band. Each repeated what the proof and
 * #evidence already say, or explained the product to someone who has already
 * decided. The i18n keys are still in the catalogues and git has the JSX.
 * The figures never come from the catalogues: if the API does not answer, the
 * numbers are left out, so the page can be incomplete but never wrong.
 */
export default async function HomePage() {
  const t = await getTranslations();
  const locale = await getLocale();
  const stats = await getCorpusStats();

  const number = new Intl.NumberFormat(locale);
  const hasRange = stats !== null && stats.year_min !== null && stats.year_max !== null;
  const evStats =
    stats === null
      ? []
      : [
          { value: number.format(stats.sources), label: t("home.evStat1L") },
          { value: number.format(stats.chunks), label: t("home.evStat2L") },
          ...(hasRange
            ? [{ value: `${stats.year_min}–${stats.year_max}`, label: t("home.evStat3L") }]
            : []),
        ];
  // Institutions that stand behind at least one source in the corpus files.
  // tests/test_evidence_files.py fails when one of these names has no source
  // behind it, so the page cannot name an institution the corpus lacks.
  // "OMS" is "WHO" in English.
  const evOrgs = [
    "NICE",
    "American Academy of Pediatrics",
    locale === "en" ? "WHO" : "OMS",
    "Asociación Española de Pediatría",
    "AEPap",
    "NASPGHAN-ESPGHAN",
    "Santé publique France",
  ];
  // Two plans only. A third one ("with a specialist", 16 EUR) was advertised
  // once with nothing behind it (audit 4.10); it returns the day a paediatrician
  // is under contract, with a Price of its own.
  const tiers = [
    {
      name: t("home.prT1Name"),
      price: t("home.prT1Price"),
      cadence: t("home.prT1Cad"),
      desc: t("home.prT1Desc"),
      cta: t("home.prT1Cta"),
      href: GITHUB_URL,
      external: true,
      primary: false,
      note: null as string | null,
    },
    {
      name: t("home.prT2Name"),
      price: t("home.prT2Price"),
      cadence: t("home.prT2Cad"),
      desc: t("home.prT2Desc"),
      cta: t("home.prT2Cta"),
      href: "/billing",
      external: false,
      primary: true,
      note: t("home.prT2Trial") as string | null,
    },
  ];

  return (
    <div className="min-h-screen">
      {/* One aggregate counter per page view, no cookie and no identifier
          (audit 4.8, components/funnel.tsx). Renders nothing. */}
      <FunnelVisit />

      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <span className="font-display text-2xl font-semibold tracking-tight text-ink">
          Adel<span className="text-accent-text">IA</span>
        </span>
        <LocaleSwitcher current={locale} />
      </header>

      <main className="mx-auto max-w-5xl px-6 pb-[var(--ad-section)]">
        {/* 1. What it is, and the way in */}
        <section className="pb-12 pt-8 md:pb-[var(--ad-section)] md:pt-16">
          <h1 className="t-display max-w-[15ch] text-ink">
            {t("home.hero")}
          </h1>
          <p className="t-lede mt-6">{t("home.subhero")}</p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            <Link href="/demo" className="ad-btn ad-btn-primary w-full px-6 py-3 text-base sm:w-auto">
              {t("home.demoLink")}
              <ArrowRight className="h-4 w-4" strokeWidth={2.4} />
            </Link>
            <StartLink
              href="/dashboard"
              className="ad-btn ad-btn-ghost w-full px-5 py-3 text-base sm:w-auto"
            >
              {t("home.cta")}
            </StartLink>
          </div>
        </section>

        {/* 2. Proof: one real answer and the guideline it came from */}
        <figure className="max-w-2xl border-t border-line pt-8">
          <figcaption className="ad-eyebrow">{t("home.proofLabel")}</figcaption>
          <p className="mt-4 font-display text-[1.375rem] leading-snug tracking-tight text-ink">“{t("home.proofQuestion")}”</p>
          <p className="t-body mt-4 text-ink">
            {t("home.proofAnswer")} <span className="ad-ev-tag align-middle">ev_1</span>
          </p>
          <p className="t-small mt-4 text-ink-soft">{t("home.proofSource")}</p>
        </figure>

        {/* 3. Where the answers come from */}
        <section id="evidence" className="scroll-mt-24 border-t border-line pt-8 mt-[var(--ad-section)]">
          <h2 className="t-h2 max-w-[22ch] text-ink">
            {t("home.evTitle")}
          </h2>
          <p className="t-body mt-4 text-ink-soft">{t("home.evBody")}</p>
          {evStats.length > 0 && (
            <dl className="mt-8 grid max-w-xl grid-cols-3 gap-4">
              {evStats.map((s) => (
                <div key={s.label}>
                  <dd className="t-figure font-display text-2xl font-semibold text-primary-text md:text-3xl">
                    {s.value}
                  </dd>
                  <dt className="mt-1 text-[0.8125rem] leading-snug text-ink-soft">{s.label}</dt>
                </div>
              ))}
            </dl>
          )}
          <p className="t-small mt-8 text-ink-soft">{evOrgs.join(" · ")}</p>
        </section>

        {/* 4. What it costs */}
        <section id="pricing" className="scroll-mt-24 border-t border-line pt-8 mt-[var(--ad-section)]">
          <h2 className="t-h2 text-ink">{t("home.prTitle")}</h2>
          <div className="mt-8 grid gap-10 md:grid-cols-2 md:gap-16">
            {tiers.map((tier) => (
              <div key={tier.name} className="flex flex-col">
                <h3 className="t-h3 font-display text-ink">{tier.name}</h3>
                <p className="mt-2 flex items-baseline gap-1">
                  <span className="t-figure font-display text-4xl font-semibold text-ink">{tier.price}</span>
                  <span className="text-sm text-ink-soft">{tier.cadence}</span>
                </p>
                <p className="t-small mt-3 max-w-[40ch] text-ink-soft">{tier.desc}</p>
                {tier.external ? (
                  <a
                    href={tier.href}
                    target="_blank"
                    rel="noreferrer"
                    className={`ad-btn mt-5 w-full self-start px-5 py-2.5 text-sm sm:w-auto ${
                      tier.primary ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <StartLink
                    href={tier.href}
                    className={`ad-btn mt-5 w-full self-start px-5 py-2.5 text-sm sm:w-auto ${
                      tier.primary ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </StartLink>
                )}
                {tier.note && <p className="t-small mt-3 text-ink-soft">{tier.note}</p>}
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10 md:flex-row md:items-start md:justify-between">
          <p className="t-small max-w-md text-ink-soft">{t("home.footerDisclaimer")}</p>
          <nav className="flex flex-wrap gap-x-5 text-sm" aria-label="Footer">
            <Link href="/privacidad" className="py-2 text-ink-soft hover:text-primary-text-hover">
              {t("home.footerPrivacy")}
            </Link>
            <Link href="/terminos" className="py-2 text-ink-soft hover:text-primary-text-hover">
              {t("home.footerTerms")}
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="py-2 text-ink-soft hover:text-primary-text-hover"
            >
              {t("home.footerGithub")}
            </a>
          </nav>
        </div>
        <p className="mx-auto max-w-5xl px-6 pb-8 font-mono text-xs text-ink-faint">
          © {t("home.footerLicense")}
        </p>
      </footer>
    </div>
  );
}
