import type { Metadata } from "next";
import { Link } from "@/lib/navigation";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import {
  Activity,
  Building2,
  Send,
  Mail,
  BookOpen,
  FileText,
  Clock,
  UploadCloud,
} from "lucide-react";

import { auth } from "@/lib/auth";
import { ingestion } from "@/lib/api-client";
import type { GDPRTemplateSummary, GuideSummary } from "@/lib/enrichment-types";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "ingestion" });
  return { title: t("title") };
}

export default async function IngestionPage({ params }: Props) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations();
  let guides: GuideSummary[] = [];
  let templates: GDPRTemplateSummary[] = [];
  try {
    [guides, templates] = await Promise.all([
      ingestion.listGuides(),
      ingestion.listGdprTemplates(),
    ]);
  } catch {
    guides = [];
    templates = [];
  }

  // The fastest path for a mom: a photo or a PDF. Surfaced first, badged.
  const photoSource = {
    href: "/dashboard/upload",
    Icon: UploadCloud,
    title: t("ingestion.overview.photoTitle"),
    desc: t("ingestion.overview.photoDesc"),
    fastest: true,
  };

  // Other import channels — still primary, just not the quickest.
  const channelSources = [
    { slug: "apple-health", Icon: Activity, title: "Apple Health", desc: t("ingestion.overview.appleHealthDesc") },
    { slug: "ccd", Icon: Building2, title: "MyChart / CCD", desc: t("ingestion.overview.ccdDesc") },
    { slug: "telegram", Icon: Send, title: "Telegram", desc: t("ingestion.overview.telegramDesc") },
    { slug: "email", Icon: Mail, title: t("ingestion.overview.emailTitle"), desc: t("ingestion.overview.emailDesc") },
  ];

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl text-ink">{t("ingestion.title")}</h1>
      <p className="mt-1 text-sm text-ink-soft">{t("ingestion.subtitle")}</p>

      <section className="mt-8">
        <h2 className="text-base font-medium text-ink">{t("ingestion.startHereTitle")}</h2>
        <p className="mt-0.5 text-xs text-ink-soft">{t("ingestion.startHereHint")}</p>

        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Link
            href={photoSource.href}
            className="ad-card ad-card-hover relative p-4 ring-1 ring-primary-tint-line"
          >
            <span className="ad-eyebrow absolute right-3 top-3 rounded-full bg-accent-tint px-2 py-0.5 text-accent-text">
              {t("ingestion.fastestBadge")}
            </span>
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
              <photoSource.Icon className="h-5 w-5" strokeWidth={2} />
            </span>
            <h3 className="mt-3 text-base text-ink">{photoSource.title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-ink-soft">{photoSource.desc}</p>
          </Link>

          {channelSources.map((s) => (
            <Link
              key={s.slug}
              href={`/dashboard/ingestion/${s.slug}`}
              className="ad-card ad-card-hover p-4"
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                <s.Icon className="h-5 w-5" strokeWidth={2} />
              </span>
              <h3 className="mt-3 text-base text-ink">{s.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-ink-soft">{s.desc}</p>
            </Link>
          ))}
        </div>
      </section>

      <details className="ad-card mt-12 p-5">
        <summary className="cursor-pointer list-none text-base font-medium text-ink marker:hidden">
          {t("ingestion.advancedTitle")}
          <span className="mt-0.5 block text-xs font-normal text-ink-soft">
            {t("ingestion.advancedHint")}
          </span>
        </summary>

        <section className="mt-8">
        <h2 className="flex items-center gap-2 text-lg text-ink">
          <BookOpen className="h-4 w-4 text-primary-text" strokeWidth={2} />
          {t("ingestion.guidesTab")}
        </h2>
        <ul className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {guides.map((g) => (
            <li key={g.slug}>
              <Link
                href={`/dashboard/ingestion/guides/${g.slug}`}
                className="ad-card ad-card-hover block p-4"
              >
                <div className="font-medium text-ink">{g.title}</div>
                <div className="mt-1 text-xs leading-relaxed text-ink-soft">{g.description}</div>
                {g.estimated_time && (
                  <div className="mt-2 flex items-center gap-1 font-mono text-[11px] text-ink-faint">
                    <Clock className="h-3 w-3" strokeWidth={2} />
                    {g.estimated_time}
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <h2 className="flex items-center gap-2 text-lg text-ink">
          <FileText className="h-4 w-4 text-primary-text" strokeWidth={2} />
          {t("ingestion.gdprTab")}
        </h2>
        <ul className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-3">
          {templates.map((tpl) => (
            <li key={tpl.country}>
              <Link
                href={`/dashboard/ingestion/gdpr/${tpl.country}`}
                className="ad-card ad-card-hover block p-4"
              >
                <div className="font-medium text-ink">{tpl.country}</div>
                <div className="mt-1 text-xs text-ink-soft">{tpl.authority}</div>
                <div className="mt-1 text-[10px] text-ink-faint">{tpl.legal_basis}</div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      </details>
    </main>
  );
}
