import { useTranslations, useLocale } from "next-intl";
import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import {
  ArrowRight,
  ArrowUpRight,
  ShieldCheck,
  Quote,
  MessagesSquare,
  Stethoscope,
  Code2,
  ScrollText,
  Server,
  KeyRound,
} from "lucide-react";

const GITHUB_URL = "https://github.com/santiagopatinoserna/AdelIA";

export default function HomePage() {
  const t = useTranslations();
  const locale = useLocale();
  const features = [
    { icon: ShieldCheck, title: t("home.feature1Title"), body: t("home.feature1Body") },
    { icon: Quote, title: t("home.feature2Title"), body: t("home.feature2Body") },
    { icon: MessagesSquare, title: t("home.feature3Title"), body: t("home.feature3Body") },
  ];
  const modeAExamples = [t("home.modeAEx1"), t("home.modeAEx2"), t("home.modeAEx3")];
  const modeBExamples = [t("home.modeBEx1"), t("home.modeBEx2"), t("home.modeBEx3")];
  const ossChips = [
    { icon: ScrollText, label: t("home.ossChip1") },
    { icon: Server, label: t("home.ossChip2") },
    { icon: KeyRound, label: t("home.ossChip3") },
  ];

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Top bar */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <span className="font-display text-2xl font-semibold tracking-tight text-pine-900">
          Adel<span className="text-honey-500">IA</span>
        </span>
        <div className="flex items-center gap-4">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            aria-label={t("home.footerGithub")}
            className="hidden text-ink-soft transition-colors hover:text-pine-700 sm:inline-flex"
          >
            <Code2 className="h-5 w-5" strokeWidth={1.9} />
          </a>
          <LocaleSwitcher current={locale} />
          <Link
            href="/dashboard"
            className="ad-btn ad-btn-ghost px-3.5 py-1.5 text-sm"
          >
            {t("home.cta")}
          </Link>
        </div>
      </header>

      {/* Hero */}
      <main className="mx-auto max-w-6xl px-6 pb-24 pt-10 md:pt-16">
        <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_0.95fr]">
          {/* Left: copy */}
          <div className="ad-rise" style={{ animationDelay: "60ms" }}>
            <p className="ad-eyebrow flex items-center gap-2">
              <Stethoscope className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.eyebrow")}
            </p>
            <h1 className="mt-5 text-balance font-display text-5xl leading-[1.04] tracking-tight text-pine-900 md:text-6xl">
              {t("home.hero")}
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-soft">
              {t("home.subhero")}
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link href="/dashboard" className="ad-btn ad-btn-primary px-6 py-3 text-base">
                {t("home.cta")}
                <ArrowRight className="h-4 w-4" strokeWidth={2.4} />
              </Link>
              <a href="#how" className="ad-btn ad-btn-ghost px-5 py-3 text-base">
                {t("home.ctaSecondary")}
              </a>
            </div>
          </div>

          {/* Right: evidence proof card — the differentiator */}
          <div className="ad-rise" style={{ animationDelay: "180ms" }}>
            <figure className="ad-card relative overflow-hidden p-6 md:p-7">
              <div
                aria-hidden
                className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-pine-100/50 blur-2xl"
              />
              <figcaption className="ad-eyebrow flex items-center gap-2">
                <Quote className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.proofLabel")}
              </figcaption>
              <p className="mt-4 text-sm font-medium italic text-ink-soft">
                “{t("home.proofQuestion")}”
              </p>
              <p className="mt-4 text-[15px] leading-relaxed text-ink">
                {t("home.proofAnswer")}{" "}
                <span className="ad-ev-tag align-middle">ev_1</span>
              </p>
              <div className="mt-5 border-t border-line pt-4">
                <p className="font-mono text-xs text-ink-faint">
                  {t("home.proofSource")}
                </p>
              </div>
            </figure>
          </div>
        </div>

        {/* Feature triad */}
        <section id="features" className="mt-24 scroll-mt-24">
          <div className="grid gap-5 sm:grid-cols-3">
            {features.map((f, i) => (
              <div
                key={f.title}
                className="ad-card ad-card-hover ad-rise p-6"
                style={{ animationDelay: `${260 + i * 90}ms` }}
              >
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                  <f.icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h2 className="mt-4 text-lg text-pine-900">{f.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-ink-soft">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* How it works — two modes, one vault */}
        <section id="how" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow">{t("home.modesEyebrow")}</p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-pine-900 md:text-4xl">
              {t("home.modesTitle")}
            </h2>
          </div>

          <div className="mt-12 grid gap-5 md:grid-cols-2">
            {/* Mode A — self-analysis (pine) */}
            <article className="ad-card relative overflow-hidden p-7 md:p-8">
              <span className="absolute right-6 top-6 font-display text-5xl font-semibold text-pine-50 select-none">
                A
              </span>
              <p className="ad-eyebrow">{t("home.modeALabel")}</p>
              <div className="mt-3 flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                  <MessagesSquare className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="font-display text-xl text-pine-900">{t("home.modeATitle")}</h3>
              </div>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.modeABody")}</p>
              <ul className="mt-5 flex flex-col gap-2">
                {modeAExamples.map((ex) => (
                  <li key={ex} className="flex items-start gap-2 text-sm text-ink">
                    <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-pine-400" strokeWidth={2.4} />
                    <span className="italic">“{ex}”</span>
                  </li>
                ))}
              </ul>
            </article>

            {/* Mode B — briefing (honey) */}
            <article className="ad-card relative overflow-hidden p-7 md:p-8">
              <span className="absolute right-6 top-6 font-display text-5xl font-semibold text-honey-100 select-none">
                B
              </span>
              <p className="ad-eyebrow !text-honey-600">{t("home.modeBLabel")}</p>
              <div className="mt-3 flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-honey-100 text-honey-600 ring-1 ring-honey-200">
                  <Stethoscope className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="font-display text-xl text-pine-900">{t("home.modeBTitle")}</h3>
              </div>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.modeBBody")}</p>
              <ul className="mt-5 flex flex-col gap-2">
                {modeBExamples.map((ex) => (
                  <li key={ex} className="flex items-start gap-2 text-sm text-ink">
                    <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-honey-500" strokeWidth={2.4} />
                    <span>{ex}</span>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </section>

        {/* Open-source / data sovereignty band */}
        <section className="mt-28">
          <div className="ad-grain ad-card relative overflow-hidden border-pine-800 bg-pine-900 p-8 md:p-12">
            <div
              aria-hidden
              className="pointer-events-none absolute -left-20 -top-24 h-64 w-64 rounded-full bg-pine-600/30 blur-3xl"
            />
            <div
              aria-hidden
              className="pointer-events-none absolute -bottom-28 right-0 h-64 w-64 rounded-full bg-honey-500/15 blur-3xl"
            />
            <div className="relative max-w-2xl">
              <p className="ad-eyebrow !text-honey-400">{t("home.ossEyebrow")}</p>
              <h2 className="mt-3 text-balance font-display text-3xl text-[#f3f7f3] md:text-4xl">
                {t("home.ossTitle")}
              </h2>
              <p className="mt-4 text-[15px] leading-relaxed text-pine-100">
                {t("home.ossBody")}
              </p>
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="ad-btn bg-[#f3f7f3] px-5 py-2.5 text-sm font-semibold text-pine-900 hover:bg-white"
                >
                  <Code2 className="h-4 w-4" strokeWidth={2} />
                  {t("home.ossCta")}
                  <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2.4} />
                </a>
                {ossChips.map((chip) => (
                  <span
                    key={chip.label}
                    className="inline-flex items-center gap-1.5 rounded-full border border-pine-600/60 bg-pine-800/60 px-3 py-1.5 text-xs font-medium text-pine-100"
                  >
                    <chip.icon className="h-3.5 w-3.5 text-honey-400" strokeWidth={2} />
                    {chip.label}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-12 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <span className="font-display text-xl font-semibold tracking-tight text-pine-900">
              Adel<span className="text-honey-500">IA</span>
            </span>
            <p className="mt-2 text-sm text-ink-soft">{t("home.footerTagline")}</p>
            <p className="mt-4 text-xs leading-relaxed text-ink-faint">
              {t("home.footerDisclaimer")}
            </p>
          </div>
          <nav className="flex flex-col gap-2.5 text-sm" aria-label="Footer">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-ink-soft transition-colors hover:text-pine-700"
            >
              <Code2 className="h-4 w-4" strokeWidth={2} />
              {t("home.footerGithub")}
            </a>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-1.5 text-ink-soft transition-colors hover:text-pine-700"
            >
              <ArrowRight className="h-4 w-4" strokeWidth={2} />
              {t("home.footerDashboard")}
            </Link>
          </nav>
        </div>
        <div className="border-t border-line">
          <p className="mx-auto max-w-6xl px-6 py-5 font-mono text-xs text-ink-faint">
            © {t("home.footerLicense")}
          </p>
        </div>
      </footer>
    </div>
  );
}
