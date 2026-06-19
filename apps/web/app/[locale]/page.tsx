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
  FileText,
  Check,
  X,
  BookMarked,
  Sparkles,
  Baby,
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
  const briefingRows = [
    { label: t("home.modeBDemoS1Label"), body: t("home.modeBDemoS1") },
    { label: t("home.modeBDemoS2Label"), body: t("home.modeBDemoS2") },
    { label: t("home.modeBDemoS3Label"), body: t("home.modeBDemoS3") },
  ];
  const ossChips = [
    { icon: ScrollText, label: t("home.ossChip1") },
    { icon: Server, label: t("home.ossChip2") },
    { icon: KeyRound, label: t("home.ossChip3") },
  ];
  const timeline = [
    { age: t("home.mixT1Age"), event: t("home.mixT1") },
    { age: t("home.mixT2Age"), event: t("home.mixT2") },
    { age: t("home.mixT3Age"), event: t("home.mixT3") },
    { age: t("home.mixT4Age"), event: t("home.mixT4") },
    { age: t("home.mixT5Age"), event: t("home.mixT5") },
  ];
  const evStats = [
    { value: t("home.evStat1V"), label: t("home.evStat1L") },
    { value: t("home.evStat2V"), label: t("home.evStat2L") },
    { value: t("home.evStat3V"), label: t("home.evStat3L") },
    { value: t("home.evStat4V"), label: t("home.evStat4L") },
  ];
  // Real organizations present in the evidence corpus (verifiable in DB).
  const evOrgs = ["NASPGHAN-ESPGHAN", "NICE", "CDC", "AHA", "ADA", "ESC", "GINA", "USPSTF"];
  const vsRows = [
    { l: t("home.vsR1L"), g: t("home.vsR1G"), a: t("home.vsR1A") },
    { l: t("home.vsR2L"), g: t("home.vsR2G"), a: t("home.vsR2A") },
    { l: t("home.vsR3L"), g: t("home.vsR3G"), a: t("home.vsR3A") },
    { l: t("home.vsR4L"), g: t("home.vsR4G"), a: t("home.vsR4A") },
    { l: t("home.vsR5L"), g: t("home.vsR5G"), a: t("home.vsR5A") },
  ];
  const tiers = [
    {
      name: t("home.prT1Name"), price: t("home.prT1Price"), cadence: t("home.prT1Cad"),
      desc: t("home.prT1Desc"), cta: t("home.prT1Cta"), href: GITHUB_URL, external: true,
      highlight: false, devTag: t("home.prT1DevTag"),
      features: [t("home.prT1F1"), t("home.prT1F2"), t("home.prT1F3"), t("home.prT1F4")],
    },
    {
      name: t("home.prT2Name"), price: t("home.prT2Price"), cadence: t("home.prT2Cad"),
      desc: t("home.prT2Desc"), cta: t("home.prT2Cta"), href: "/billing", external: false,
      highlight: true, badge: t("home.prT2Badge"),
      trialNote: t("home.prT2Trial"),
      features: [t("home.prT2F1"), t("home.prT2F2"), t("home.prT2F3"), t("home.prT2F4")],
    },
    {
      name: t("home.prT3Name"), price: t("home.prT3Price"), cadence: t("home.prT3Cad"),
      desc: t("home.prT3Desc"), cta: t("home.prT3Cta"), href: "/dashboard", external: false,
      highlight: false,
      features: [t("home.prT3F1"), t("home.prT3F2"), t("home.prT3F3"), t("home.prT3F4")],
    },
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
              <span
                aria-hidden
                className="absolute right-6 top-6 font-display text-5xl font-semibold text-pine-50 select-none"
              >
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
              {/* Realistic chat preview — mirrors the actual product UI */}
              <div className="mt-5 flex flex-col gap-2.5">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-b from-pine-600 to-pine-700 px-3.5 py-2 text-sm leading-relaxed text-[#eef3ee]">
                    {t("home.modeADemoQ")}
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-ink shadow-soft">
                    {t("home.modeADemoA")} <span className="ad-ev-tag align-middle">ev_1</span>
                    <span className="mt-2 block font-mono text-[11px] text-ink-faint">
                      {t("home.modeADemoSource")}
                    </span>
                  </div>
                </div>
              </div>
            </article>

            {/* Mode B — briefing (honey) */}
            <article className="ad-card relative overflow-hidden p-7 md:p-8">
              <span
                aria-hidden
                className="absolute right-6 top-6 font-display text-5xl font-semibold text-honey-100 select-none"
              >
                B
              </span>
              <p className="ad-eyebrow !text-honey-700">{t("home.modeBLabel")}</p>
              <div className="mt-3 flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-honey-100 text-honey-600 ring-1 ring-honey-200">
                  <Stethoscope className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="font-display text-xl text-pine-900">{t("home.modeBTitle")}</h3>
              </div>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.modeBBody")}</p>
              {/* Realistic one-page briefing preview */}
              <div className="mt-5 rounded-xl border border-line bg-surface-2 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="ad-eyebrow !text-honey-700">{t("home.modeBDemoTitle")}</span>
                  <FileText className="h-4 w-4 text-honey-500" strokeWidth={2} />
                </div>
                <p className="mt-1 font-mono text-[11px] text-ink-faint">{t("home.modeBDemoMeta")}</p>
                <dl className="mt-3 flex flex-col gap-2.5">
                  {briefingRows.map((row, i) => (
                    <div key={row.label} className="border-t border-line pt-2.5 first:border-t-0 first:pt-0">
                      <dt className="text-[11px] font-semibold uppercase tracking-wide text-pine-600">
                        {row.label}
                      </dt>
                      <dd className="mt-0.5 text-sm leading-snug text-ink">
                        {row.body}
                        {i === 1 && <span className="ad-ev-tag ml-1 align-middle">ev_1</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </article>
          </div>
        </section>

        {/* Fusion — the baby's full history (from birth) × the science */}
        <section id="story" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <Baby className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.mixEyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-pine-900 md:text-4xl">
              {t("home.mixTitle")}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.mixBody")}</p>
          </div>

          <div className="mt-10 grid gap-5 md:grid-cols-2 md:items-stretch">
            {/* Left: the baby's history from birth */}
            <div className="ad-card flex flex-col p-6 md:p-7">
              <div className="ad-eyebrow flex items-center gap-2">
                <Baby className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.mixTimelineLabel")}
              </div>
              <ol className="relative mt-5 flex flex-col gap-4 border-l border-line-strong pl-5">
                {timeline.map((item) => (
                  <li key={item.age} className="relative">
                    <span
                      aria-hidden
                      className="absolute -left-[1.43rem] top-1 h-2.5 w-2.5 rounded-full bg-pine-400 ring-2 ring-surface"
                    />
                    <div className="font-mono text-xs font-semibold text-pine-700">{item.age}</div>
                    <div className="text-sm leading-snug text-ink">{item.event}</div>
                  </li>
                ))}
              </ol>
            </div>

            {/* Right: history × science = personalized, cited answer */}
            <div className="ad-card flex flex-col p-6 ring-1 ring-pine-200 md:p-7">
              <div className="ad-eyebrow flex items-center gap-2 !text-honey-700">
                <Sparkles className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.mixAnswerLabel")}
              </div>
              <div className="mt-5 rounded-2xl rounded-bl-md border border-line bg-surface px-4 py-3.5 text-sm leading-relaxed text-ink shadow-soft">
                {t("home.mixAnswer")}
              </div>
              <div className="mt-auto flex flex-wrap gap-x-5 gap-y-2 pt-5 text-xs text-ink-faint">
                <span className="inline-flex items-center gap-1.5">
                  <span className="rounded-[0.4rem] border border-pine-100 bg-pine-50 px-1.5 font-mono text-[0.7rem] font-semibold text-pine-600">
                    [N]
                  </span>
                  {t("home.mixLegendData")}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="ad-ev-tag">ev_N</span>
                  {t("home.mixLegendEv")}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Evidence guarantee — where every answer comes from */}
        <section id="evidence" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <BookMarked className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.evEyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-pine-900 md:text-4xl">
              {t("home.evTitle")}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.evBody")}</p>
          </div>
          <div className="mt-10 grid grid-cols-2 gap-4 sm:gap-3 md:grid-cols-4">
            {evStats.map((s) => (
              <div key={s.label} className="ad-card px-4 py-5 text-center sm:px-5">
                <div className="font-display text-2xl font-semibold text-pine-700 sm:text-3xl">{s.value}</div>
                <div className="mt-1.5 text-xs leading-snug text-ink-soft">{s.label}</div>
              </div>
            ))}
          </div>
          <div className="mt-8 flex flex-col items-center gap-3">
            <span className="ad-eyebrow">{t("home.evSourcesLabel")}</span>
            <div className="flex max-w-3xl flex-wrap items-center justify-center gap-2">
              {evOrgs.map((o) => (
                <span
                  key={o}
                  className="rounded-full border border-line-strong bg-surface px-3 py-1 font-mono text-xs text-ink-soft"
                >
                  {o}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Classic GPT vs AdelIA — honest, structural comparison */}
        <section className="mt-28">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow">{t("home.vsEyebrow")}</p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-pine-900 md:text-4xl">
              {t("home.vsTitle")}
            </h2>
            <p className="mt-4 text-lg font-medium italic text-ink-soft">{t("home.vsQuestion")}</p>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-2">
            <div className="ad-card p-6">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-clay-50 text-clay-500 ring-1 ring-clay-100">
                  <X className="h-4 w-4" strokeWidth={2.4} />
                </span>
                <span className="text-sm font-semibold text-ink">{t("home.vsGptLabel")}</span>
              </div>
              <p className="mt-4 rounded-2xl rounded-bl-md border border-line bg-surface-2 px-3.5 py-2.5 text-sm leading-relaxed text-ink-soft">
                {t("home.vsGptAnswer")}
              </p>
              <p className="mt-3 flex items-start gap-1.5 text-xs text-clay-600">
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.4} />
                {t("home.vsGptNote")}
              </p>
            </div>
            <div className="ad-card p-6 ring-1 ring-pine-200">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                  <Check className="h-4 w-4" strokeWidth={2.4} />
                </span>
                <span className="text-sm font-semibold text-pine-900">{t("home.vsColAdelia")}</span>
              </div>
              <div className="mt-4 rounded-2xl rounded-bl-md border border-line bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-ink shadow-soft">
                {t("home.vsAdeliaAnswer")} <span className="ad-ev-tag align-middle">ev_1</span>
                <span className="mt-2 block font-mono text-[11px] text-ink-faint">{t("home.vsAdeliaSource")}</span>
              </div>
              <p className="mt-3 flex items-start gap-1.5 text-xs text-pine-600">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.4} />
                {t("home.vsAdeliaNote")}
              </p>
            </div>
          </div>
          <div className="ad-card mt-5 overflow-hidden">
            {/* Table header — hidden on phones, where each row becomes a stacked card */}
            <div className="hidden grid-cols-[1.4fr_1fr_1fr] border-b border-line bg-surface-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint sm:grid">
              <div className="px-4 py-2.5" />
              <div className="px-4 py-2.5 text-center">{t("home.vsColGpt")}</div>
              <div className="px-4 py-2.5 text-center text-pine-700">{t("home.vsColAdelia")}</div>
            </div>
            {vsRows.map((r) => (
              <div
                key={r.l}
                className="flex flex-col gap-2 border-b border-line p-4 text-sm last:border-b-0 sm:grid sm:grid-cols-[1.4fr_1fr_1fr] sm:gap-0 sm:p-0"
              >
                <div className="font-medium text-ink sm:px-4 sm:py-2.5">{r.l}</div>
                <div className="flex items-baseline justify-between gap-3 text-ink-soft sm:block sm:px-4 sm:py-2.5 sm:text-center">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint sm:hidden">
                    {t("home.vsColGpt")}
                  </span>
                  <span>{r.g}</span>
                </div>
                <div className="flex items-baseline justify-between gap-3 font-medium text-pine-700 sm:block sm:px-4 sm:py-2.5 sm:text-center">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-pine-700 sm:hidden">
                    {t("home.vsColAdelia")}
                  </span>
                  <span>{r.a}</span>
                </div>
              </div>
            ))}
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
        {/* Pricing — how you use it */}
        <section id="pricing" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.prEyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-pine-900 md:text-4xl">
              {t("home.prTitle")}
            </h2>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3 md:items-start">
            {tiers.map((tier) => (
              <div
                key={tier.name}
                className={`ad-card relative flex flex-col p-7 ${
                  tier.highlight ? "ring-2 ring-pine-500 md:-mt-3 md:mb-3" : ""
                }`}
              >
                {tier.badge && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-pine-600 px-3 py-1 text-[11px] font-semibold text-[#f3f7f3]">
                    {tier.badge}
                  </span>
                )}
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <h3 className="font-display text-xl text-pine-900">{tier.name}</h3>
                  {tier.devTag && (
                    <span className="rounded-full border border-line-strong bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-ink-soft">
                      {tier.devTag}
                    </span>
                  )}
                </div>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-4xl font-semibold text-pine-900">{tier.price}</span>
                  <span className="text-sm text-ink-faint">{tier.cadence}</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-ink-soft">{tier.desc}</p>
                <ul className="mt-5 flex flex-1 flex-col gap-2.5">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-ink">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-pine-500" strokeWidth={2.4} />
                      {f}
                    </li>
                  ))}
                </ul>
                {tier.external ? (
                  <a
                    href={tier.href}
                    target="_blank"
                    rel="noreferrer"
                    className={`ad-btn mt-7 px-5 py-2.5 text-sm ${
                      tier.highlight ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <Link
                    href={tier.href}
                    className={`ad-btn mt-7 px-5 py-2.5 text-sm ${
                      tier.highlight ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </Link>
                )}
                {tier.trialNote && (
                  <p className="mt-3 text-center text-xs text-ink-soft">{tier.trialNote}</p>
                )}
              </div>
            ))}
          </div>
          <p className="mx-auto mt-6 max-w-2xl text-center text-xs text-ink-faint">
            {t("home.prFootnote")}
          </p>
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
              className="inline-flex items-center gap-1.5 py-1.5 text-ink-soft transition-colors hover:text-pine-700"
            >
              <Code2 className="h-4 w-4" strokeWidth={2} />
              {t("home.footerGithub")}
            </a>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-1.5 py-1.5 text-ink-soft transition-colors hover:text-pine-700"
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
