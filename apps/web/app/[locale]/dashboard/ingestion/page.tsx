import { Link } from "@/lib/navigation";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { auth } from "@/lib/auth";
import { ingestion } from "@/lib/api-client";
import type { GDPRTemplateSummary, GuideSummary } from "@/lib/enrichment-types";

interface Props {
  params: Promise<{ locale: string }>;
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

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{t("ingestion.title")}</h1>
      <p className="mt-1 text-sm text-slate-600">{t("ingestion.subtitle")}</p>

      <section className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Link
          href="/dashboard/ingestion/apple-health"
          className="rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
        >
          <div className="text-3xl">📱</div>
          <h3 className="mt-2 font-medium">Apple Health</h3>
          <p className="text-xs text-slate-600">export.zip → biométricos</p>
        </Link>
        <Link
          href="/dashboard/ingestion/ccd"
          className="rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
        >
          <div className="text-3xl">🏥</div>
          <h3 className="mt-2 font-medium">MyChart / CCD</h3>
          <p className="text-xs text-slate-600">XML del portal paciente</p>
        </Link>
        <Link
          href="/dashboard/ingestion/telegram"
          className="rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
        >
          <div className="text-3xl">💬</div>
          <h3 className="mt-2 font-medium">Telegram</h3>
          <p className="text-xs text-slate-600">Reenvía docs al bot</p>
        </Link>
        <Link
          href="/dashboard/ingestion/email"
          className="rounded-lg border border-slate-200 bg-white p-4 hover:bg-slate-50"
        >
          <div className="text-3xl">📧</div>
          <h3 className="mt-2 font-medium">Email</h3>
          <p className="text-xs text-slate-600">Forward a tu alias</p>
        </Link>
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">{t("ingestion.guidesTab")}</h2>
        <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
          {guides.map((g) => (
            <li key={g.slug}>
              <Link
                href={`/dashboard/ingestion/guides/${g.slug}`}
                className="block rounded border border-slate-200 bg-white p-3 hover:bg-slate-50"
              >
                <div className="font-medium">{g.title}</div>
                <div className="mt-1 text-xs text-slate-600">{g.description}</div>
                {g.estimated_time && (
                  <div className="mt-1 text-xs text-slate-500">
                    {t("ingestion.estimatedTime")} {g.estimated_time}
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">{t("ingestion.gdprTab")}</h2>
        <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
          {templates.map((t) => (
            <li key={t.country}>
              <Link
                href={`/dashboard/ingestion/gdpr/${t.country}`}
                className="block rounded border border-slate-200 bg-white p-3 hover:bg-slate-50"
              >
                <div className="font-medium">{t.country}</div>
                <div className="mt-1 text-xs text-slate-600">{t.authority}</div>
                <div className="mt-1 text-[10px] text-slate-500">{t.legal_basis}</div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
