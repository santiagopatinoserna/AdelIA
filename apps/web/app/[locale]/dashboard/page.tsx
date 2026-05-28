import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { listDocuments, type DocumentDTO } from "@/lib/api-client";
import { DocumentCard } from "@/components/document-card";

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations("dashboard");
  let docs: DocumentDTO[] = [];
  try {
    docs = await listDocuments();
  } catch {
    // Backend unreachable or 401 — treat as empty list. T13/v0.1.1 can
    // surface a proper error UI.
    docs = [];
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/${locale}/dashboard/chat`}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
          >
            💬 Chat
          </Link>
          <Link
            href={`/${locale}/dashboard/briefings`}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
          >
            📋 Briefings
          </Link>
          <Link
            href={`/${locale}/dashboard/ingestion`}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
          >
            📥 Importar
          </Link>
          <Link
            href={`/${locale}/dashboard/enrichment`}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
          >
            ✨ Insights
          </Link>
          <Link
            href={`/${locale}/dashboard/upload`}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800"
          >
            {t("uploadCta")}
          </Link>
        </div>
      </div>
      {docs.length === 0 ? (
        <p className="mt-12 text-center text-slate-500">{t("empty")}</p>
      ) : (
        <ul className="mt-8 space-y-3">
          {docs.map((d) => (
            <li key={d.id}>
              <DocumentCard doc={d} locale={locale} />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
