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
  const stats = await getCorpusStats();
  const profile = await loadDemoProfile(locale);

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

      <header className="mx-auto flex max-w-3xl items-center justify-between px-5 py-3 sm:px-6">
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
          <LocaleSwitcher current={locale} />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-5 pb-16 sm:px-6">
        {/* 1. The question, first */}
        <section id="pregunta" className="pt-3 md:pt-10">
          <h1 className="max-w-[18ch] text-balance font-display text-[1.75rem] leading-[1.1] tracking-tight text-ink md:text-5xl">
            {t("home.hero")}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-soft">{t("demo.noStore")}</p>
          <div className="mt-5">
            <DemoAsk suggested={profile?.suggested ?? []} />
          </div>
        </section>

        {/* 2. Who it is about: fictional, folded */}
        <div className="mt-8">
          <DemoRecord profile={profile} />
        </div>

        {/* 3. Where the answers come from */}
        <section id="evidence" className="mt-12 scroll-mt-24 border-t border-line pt-6">
          <h2 className="max-w-[26ch] text-balance font-display text-2xl leading-tight text-ink md:text-3xl">
            {t("home.evTitle")}
          </h2>
          <p className="mt-3 max-w-[52ch] text-base leading-relaxed text-ink-soft">{t("home.evBody")}</p>
          {evStats.length > 0 && (
            <dl className="mt-5 grid max-w-xl grid-cols-3 gap-4">
              {evStats.map((s) => (
                <div key={s.label}>
                  <dd className="font-display text-2xl font-semibold tracking-tight text-primary-text md:text-3xl">
                    {s.value}
                  </dd>
                  <dt className="mt-1 text-xs leading-snug text-ink-soft">{s.label}</dt>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-6 max-w-[60ch] text-sm leading-relaxed text-ink-soft">{evOrgs.join(" · ")}</p>
        </section>

        {/* 4. What it costs */}
        <section id="pricing" className="mt-12 scroll-mt-24 border-t border-line pt-6">
          <h2 className="font-display text-2xl leading-tight text-ink md:text-3xl">{t("home.prTitle")}</h2>
          <div className="mt-6 grid gap-8 md:grid-cols-2 md:gap-12">
            {tiers.map((tier) => (
              <div key={tier.name} className="flex flex-col">
                <h3 className="font-display text-xl text-ink">{tier.name}</h3>
                <p className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-4xl font-semibold text-ink">{tier.price}</span>
                  <span className="text-sm text-ink-soft">{tier.cadence}</span>
                </p>
                <p className="mt-3 max-w-[40ch] text-sm leading-relaxed text-ink-soft">{tier.desc}</p>
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
                {tier.note && <p className="mt-3 text-sm text-ink-soft">{tier.note}</p>}
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-8 sm:px-6 md:flex-row md:items-start md:justify-between">
          <p className="max-w-md text-sm leading-relaxed text-ink-soft">{t("home.footerDisclaimer")}</p>
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
        <p className="mx-auto max-w-3xl px-5 pb-8 font-mono sm:px-6 text-xs text-ink-faint">
          © {t("home.footerLicense")}
        </p>
      </footer>
    </div>
  );
}
