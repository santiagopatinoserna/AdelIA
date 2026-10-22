import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { DemoAsk } from "@/components/demo-ask";
import { DemoRecord } from "@/components/demo-record";
import { FunnelVisit, StartLink } from "@/components/funnel";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { getCorpusStats } from "@/lib/corpus-stats";
import { loadDemoProfile } from "@/lib/demo-profile";
import { Link } from "@/lib/navigation";
import { publicPageAlternates } from "@/lib/seo";
import styles from "./home.module.css";

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
 * One screen, one job: ask a question. The landing and the demo used to be two
 * pages joined by a button, so a visitor paid a page load and a scroll before
 * seeing the product work. Now the question field is the first thing under the
 * headline and a suggested question is one tap from a cited answer.
 *
 * Surface: Command (one input, one result). The hero-and-sections shape of a
 * Decide page is gone on purpose: the answer is the proof, so the static
 * "one real answer" figure was removed with it.
 *
 *   1. headline, the no-account promise, the question (DemoAsk);
 *   2. who the question is about, folded and labelled as invented (DemoRecord);
 *   3. where the answers come from, in numbers counted by the API (#evidence);
 *   4. what it costs, with the trial terms (#pricing).
 *
 * The footer stays whole: the clinical disclaimer and the privacy and terms
 * links are not optional on a health product. /demo redirects here.
 * The figures never come from the catalogues: if the API does not answer, the
 * numbers are left out, so the page can be incomplete but never wrong.
 */
export default async function HomePage() {
  const t = await getTranslations();
  const locale = await getLocale();
  const [stats, profile] = await Promise.all([
    getCorpusStats(),
    loadDemoProfile(locale),
  ]);

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
    <div className={styles.home}>
      {/* One aggregate counter per page view, no cookie and no identifier
          (audit 4.8, components/funnel.tsx). Renders nothing. */}
      <FunnelVisit />

      <header className={styles.header}>
        <span className="font-display text-2xl font-semibold tracking-tight text-ink">
          Adel<span className="text-accent-text">IA</span>
        </span>
        <div className="flex items-center gap-3">
          <StartLink
            href="/dashboard"
            className="inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-medium text-primary-text hover:text-primary-text-hover"
          >
            {t("home.cta")}
          </StartLink>
          <LocaleSwitcher current={locale} compact />
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.workspace}>
        {/* 1. The question, first */}
        <section id="pregunta" className={styles.command}>
          <h1 className={styles.headline}>
            {t("home.calmTitle")}
          </h1>
          <div className={styles.ask}>
            <DemoAsk
              suggested={profile?.suggested ?? []}
              corpusStats={stats ? { sources: stats.sources, chunks: stats.chunks } : undefined}
            />
          </div>
        </section>

        {/* 2. Who it is about: fictional, folded */}
        <div className={styles.record}>
          <DemoRecord profile={profile} />
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">{t("demo.noStore")}</p>
        </div>

        </div>
        <details className={styles.support} data-testid="home-about">
          <summary className={styles.aboutToggle}>{t("home.aboutLabel")}</summary>
          <div className={styles.aboutContent}>
        {/* 3. Where the answers come from */}
        <section id="evidence" className={styles.supportSection}>
          <h2 className={styles.supportTitle}>
            {t("home.evTitle")}
          </h2>
          <p className={styles.supportBody}>{t("home.evBody")}</p>
          {evStats.length > 0 && (
            <dl className={styles.stats}>
              {evStats.map((s) => (
                <div key={s.label}>
                  <dd className={styles.statValue}>
                    {s.value}
                  </dd>
                  <dt className="mt-1 text-[0.8125rem] leading-snug text-ink-soft">{s.label}</dt>
                </div>
              ))}
            </dl>
          )}
          <p className={styles.organizations}>{evOrgs.join(" · ")}</p>
        </section>

        {/* 4. What it costs */}
        <section id="pricing" className={styles.supportSection}>
          <h2 className={styles.supportTitle}>{t("home.prTitle")}</h2>
          <div className={styles.plans}>
            {tiers.map((tier) => (
              <div key={tier.name} className={styles.plan}>
                <h3 className={styles.planName}>{tier.name}</h3>
                <p className="mt-2 flex items-baseline gap-1">
                  <span className={styles.price}>{tier.price}</span>
                  <span className="text-sm text-ink-soft">{tier.cadence}</span>
                </p>
                <p className={styles.planDescription}>{tier.desc}</p>
                {tier.external ? (
                  <a
                    href={tier.href}
                    target="_blank"
                    rel="noreferrer"
                    className={`ad-btn mt-3 w-full self-start px-5 py-2.5 text-sm ${
                      tier.primary ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <StartLink
                    href={tier.href}
                    className={`ad-btn mt-3 w-full self-start px-5 py-2.5 text-sm ${
                      tier.primary ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </StartLink>
                )}
                {tier.note && <p className={styles.trial}>{tier.note}</p>}
              </div>
            ))}
          </div>
        </section>
          </div>
        </details>
      </main>

      <footer className="border-t border-line">
        <div className={styles.footerInner}>
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
        <p className={styles.license}>
          © {t("home.footerLicense")}
        </p>
      </footer>
    </div>
  );
}
