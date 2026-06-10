import { Link } from "@/lib/navigation";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

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
    { slug: "profiles", emoji: "👨‍👩‍👧" },
    { slug: "drugs", emoji: "💊" },
    { slug: "labs", emoji: "🔬" },
    { slug: "trials", emoji: "🧪" },
    { slug: "genomics", emoji: "🧬" },
    { slug: "codes", emoji: "📋" },
  ];

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{t("enrichment.title")}</h1>
      <p className="mt-1 text-sm text-slate-600">{t("enrichment.subtitle")}</p>

      {stats && (
        <section className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-5">
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-2xl font-semibold">{stats.normalization.total}</div>
            <div className="text-xs text-slate-600">{t("enrichment.coverage.concepts")}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-2xl font-semibold">{stats.lab_ranges_count}</div>
            <div className="text-xs text-slate-600">{t("enrichment.coverage.labs")}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-2xl font-semibold">{stats.drugs.drugs_known}</div>
            <div className="text-xs text-slate-600">{t("enrichment.coverage.drugs")}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-2xl font-semibold">{stats.drugs.interactions_total}</div>
            <div className="text-xs text-slate-600">{t("enrichment.coverage.interactions")}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-2xl font-semibold">{stats.variants.variants_total}</div>
            <div className="text-xs text-slate-600">{t("enrichment.coverage.variants")}</div>
          </div>
        </section>
      )}

      <section className="mt-8 grid grid-cols-1 gap-3 md:grid-cols-3">
        {tabs.map((tab) => (
          <Link
            key={tab.slug}
            href={`/dashboard/enrichment/${tab.slug}`}
            className="rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
          >
            <div className="text-3xl">{tab.emoji}</div>
            <h3 className="mt-2 font-medium">{t(`enrichment.tabs.${tab.slug}`)}</h3>
          </Link>
        ))}
      </section>
    </main>
  );
}
