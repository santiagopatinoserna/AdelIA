import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { ArrowLeft, ArrowRight, ChevronDown, FileText, FlaskConical, Mic, NotebookPen } from "lucide-react";

import { DemoAsk } from "@/components/demo-ask";
import { FunnelVisit, StartLink } from "@/components/funnel";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link } from "@/lib/navigation";
import { publicPageAlternates } from "@/lib/seo";

// Rendered per request, never prerendered at build time: the demo baby comes
// from the API (adelia/demo/fixture.py), which is not running during
// `next build`, and a page frozen with the "could not load" fallback would be
// the version every visitor got.
export const dynamic = "force-dynamic";

const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

type DemoItem = {
  kind: "report" | "lab" | "consulta" | "diary";
  title: string;
  meta: string;
  date: string;
  lines: string[];
};

type DemoProfile = {
  is_demo: boolean;
  baby_name: string;
  age_label: string;
  banner: string;
  record_title: string;
  record_note: string;
  suggested: string[];
  items: DemoItem[];
};

const ICONS = {
  report: FileText,
  lab: FlaskConical,
  consulta: Mic,
  diary: NotebookPen,
} as const;

// The fictional baby lives in ONE place, the API, and both the card below and
// the context the model is given are built from it (adelia/demo/fixture.py).
// A second copy in the message catalogues would drift, and the first thing to
// drift would be the numbers the answer cites back at the visitor.
async function loadProfile(locale: string): Promise<DemoProfile | null> {
  try {
    const res = await fetch(`${API_URL}/demo/profile?locale=${encodeURIComponent(locale)}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as DemoProfile;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "demo" });
  return {
    title: t("metaTitle"),
    description: t("metaDescription"),
    alternates: publicPageAlternates(locale, "/demo"),
  };
}

export default async function DemoPage() {
  const locale = await getLocale();
  const t = await getTranslations("demo");
  const profile = await loadProfile(locale);
  const suggested = profile?.suggested ?? [];

  return (
    <div className="min-h-screen">
      <FunnelVisit />
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Link href="/" className="font-display text-2xl font-semibold tracking-tight text-ink">
          Adel<span className="text-accent-text">IA</span>
        </Link>
        <div className="flex items-center gap-4">
          <LocaleSwitcher current={locale} />
          <Link
            href="/"
            className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2 text-sm text-ink-soft transition-colors hover:text-primary-text-hover"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} />
            <span className="sr-only sm:not-sr-only">{t("back")}</span>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-6 md:py-14">
        <div className="max-w-2xl">
          <h1 className="text-balance font-display text-4xl leading-tight tracking-tight text-ink md:text-5xl">
            {t("title")}
          </h1>
          <p className="mt-4 max-w-[48ch] text-base leading-relaxed text-ink-soft md:text-lg">{t("subtitle")}</p>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">
            {t("noStore")}
          </p>
        </div>

        <div className="mt-8 grid gap-8 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
          {/* The action comes first in DOM and focus order. On a phone the
              parent can ask before reading all four sample documents. */}
          <section className="lg:col-start-2 lg:row-start-1">
            <DemoAsk suggested={suggested} />
          </section>
          {/* The fictional record, labelled as such three times over: the
              badge on the card, the note under the title, and the banner the
              API itself writes. A demo of a health product that looks like a
              real child's file is a liability, not a demo. */}
          <details className="group border-t border-line pt-5 lg:col-start-1 lg:row-start-1" data-testid="demo-record">
            {profile ? (
              <>
                <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden">
                  <div className="min-w-0">
                    <h2 className="font-display text-xl text-ink">
                      {profile.baby_name}, {profile.age_label}
                    </h2>
                    <p className="text-sm text-ink-soft">{profile.record_note}</p>
                  </div>
                  <span className="ml-auto shrink-0 rounded-full border border-accent-tint-line bg-accent-tint px-2 py-0.5 text-[11px] font-semibold text-accent-text">
                    {t("badge")}
                  </span>
                  <ChevronDown
                    className="h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180"
                    strokeWidth={2}
                    aria-hidden
                  />
                </summary>
                <p className="mt-4 text-sm leading-relaxed text-ink-soft">{profile.banner}</p>
                <p className="ad-eyebrow mt-6">{profile.record_title}</p>
                <ul className="mt-3 flex flex-col divide-y divide-line">
                  {profile.items.map((item) => {
                    const Icon = ICONS[item.kind] ?? FileText;
                    return (
                      <li key={item.title} className="py-3">
                        <div className="flex items-start gap-2.5">
                          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary-text" strokeWidth={2} />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-ink">{item.title}</p>
                            <p className="mt-0.5 text-xs leading-relaxed text-ink-soft">
                              {item.meta} · {item.date}
                            </p>
                          </div>
                        </div>
                        <ul className="mt-2 flex flex-col gap-1 pl-7">
                          {item.lines.map((line) => (
                            <li key={line} className="text-sm leading-relaxed text-ink-soft">
                              {line}
                            </li>
                          ))}
                        </ul>
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="text-sm leading-relaxed text-ink-soft">{t("recordUnavailable")}</p>
            )}
          </details>

        </div>

        <section className="mt-14 flex flex-col items-start gap-3 border-t border-line pt-8">
          <h2 className="text-balance font-display text-2xl text-ink">{t("signupTitle")}</h2>
          <p className="max-w-xl text-sm leading-relaxed text-ink-soft">{t("signupBody")}</p>
          <StartLink href="/dashboard" className="ad-btn ad-btn-primary mt-1 px-6 py-3 text-base">
            {t("signupCta")}
            <ArrowRight className="h-4 w-4" strokeWidth={2.4} />
          </StartLink>
          <p className="text-xs text-ink-soft">{t("signupNote")}</p>
        </section>
      </main>
    </div>
  );
}
