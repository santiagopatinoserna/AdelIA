import { Link } from "@/lib/navigation";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { Users, Pill, FlaskConical, TestTube, Dna, ClipboardList } from "lucide-react";

import { auth } from "@/lib/auth";
import { enrichment } from "@/lib/api-client";
import type { CoverageStats } from "@/lib/enrichment-types";

interface Props {
  params: Promise<{ locale: string }>;
}

export default async function EnrichmentDashboardPage({ params }: Props) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations();
  let stats: CoverageStats | null = null;
  try {
    stats = await enrichment.coverage();
  } catch {
    stats = null;
  }

  const tabs = [
    { slug: "profiles", Icon: Users },
    { slug: "drugs", Icon: Pill },
    { slug: "labs", Icon: FlaskConical },
    { slug: "trials", Icon: TestTube },
    { slug: "genomics", Icon: Dna },
    { slug: "codes", Icon: ClipboardList },
  ];

  const coverage = stats
    ? [
        { value: stats.normalization.total, label: t("enrichment.coverage.concepts") },
        { value: stats.lab_ranges_count, label: t("enrichment.coverage.labs") },
        { value: stats.drugs.drugs_known, label: t("enrichment.coverage.drugs") },
        { value: stats.drugs.interactions_total, label: t("enrichment.coverage.interactions") },
        { value: stats.variants.variants_total, label: t("enrichment.coverage.variants") },
      ]
    : [];

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl text-pine-900">{t("enrichment.title")}</h1>
      <p className="mt-1 text-sm text-ink-soft">{t("enrichment.subtitle")}</p>

      {coverage.length > 0 && (
        <section className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-5">
          {coverage.map((c) => (
            <div key={c.label} className="ad-card p-4">
              <div className="font-display text-2xl font-semibold text-pine-700">{c.value}</div>
              <div className="mt-0.5 text-xs text-ink-soft">{c.label}</div>
            </div>
          ))}
        </section>
      )}

      <section className="mt-8 grid grid-cols-1 gap-3 md:grid-cols-3">
        {tabs.map((tab) => (
          <Link
            key={tab.slug}
            href={`/dashboard/enrichment/${tab.slug}`}
            className="ad-card ad-card-hover flex items-center gap-3 p-4"
          >
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
              <tab.Icon className="h-5 w-5" strokeWidth={2} />
            </span>
            <h2 className="text-base text-pine-900">{t(`enrichment.tabs.${tab.slug}`)}</h2>
          </Link>
        ))}
      </section>
    </main>
  );
}
