import { useTranslations, useLocale } from "next-intl";
import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import {
  ArrowRight,
  ShieldCheck,
  Quote,
  MessagesSquare,
  Stethoscope,
} from "lucide-react";

export default function HomePage() {
  const t = useTranslations();
  const locale = useLocale();
  const features = [
    { icon: ShieldCheck, title: t("home.feature1Title"), body: t("home.feature1Body") },
    { icon: Quote, title: t("home.feature2Title"), body: t("home.feature2Body") },
    { icon: MessagesSquare, title: t("home.feature3Title"), body: t("home.feature3Body") },
  ];

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Top bar */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <span className="font-display text-2xl font-semibold tracking-tight text-pine-900">
          Adel<span className="text-honey-500">IA</span>
        </span>
        <div className="flex items-center gap-4">
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
              <a href="#features" className="ad-btn ad-btn-ghost px-5 py-3 text-base">
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
      </main>
    </div>
  );
}
