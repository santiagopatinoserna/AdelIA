import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Link } from "@/lib/navigation";
import { getTranslations } from "next-intl/server";
import { listDocuments, type DocumentDTO } from "@/lib/api-client";
import { DocumentCard } from "@/components/document-card";
import { LocaleSwitcher } from "@/components/locale-switcher";
import {
  MessagesSquare,
  ClipboardList,
  Download,
  Sparkles,
  Settings,
  UploadCloud,
  FolderOpen,
  Baby,
} from "lucide-react";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "dashboard" });
  return { title: t("title") };
}

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations("dashboard");
  const tq = await getTranslations("questionnaire");
  let docs: DocumentDTO[] = [];
  try {
    docs = await listDocuments();
  } catch {
    // Backend unreachable or 401 — treat as empty list.
    docs = [];
  }

  const nav = [
    { href: "/dashboard/chat", icon: MessagesSquare, label: "Chat" },
    { href: "/dashboard/briefings", icon: ClipboardList, label: "Briefings" },
    { href: "/dashboard/questionnaire", icon: Baby, label: tq("navLabel") },
    { href: "/dashboard/ingestion", icon: Download, label: t("navImport") },
    { href: "/dashboard/enrichment", icon: Sparkles, label: t("navInsights") },
  ];

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <header className="sticky top-0 z-20 border-b border-line/70 bg-canvas/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
          <Link href="/dashboard" className="font-display text-xl font-semibold tracking-tight text-pine-900">
            Adel<span className="text-honey-500">IA</span>
          </Link>
          <div className="flex items-center gap-2.5">
            <LocaleSwitcher current={locale} />
            <Link
              href="/dashboard/settings"
              aria-label={t("settingsLink")}
              className="ad-btn ad-btn-ghost h-9 w-9 p-0"
            >
              <Settings className="h-4 w-4" strokeWidth={2} />
            </Link>
            <Link href="/dashboard/upload" className="ad-btn ad-btn-primary px-4 py-2 text-sm">
              <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
              {t("uploadCta")}
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        {/* Quick-access nav */}
        <nav className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {nav.map((item, i) => (
            <Link
              key={item.href}
              href={item.href}
              className="ad-card ad-card-hover ad-rise flex items-center gap-3 px-4 py-3.5"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                <item.icon className="h-4.5 w-4.5" strokeWidth={2} />
              </span>
              <span className="text-sm font-medium text-ink">{item.label}</span>
            </Link>
          ))}
        </nav>

        {/* Documents */}
        <div className="mt-12 flex items-baseline justify-between">
          <h1 className="text-2xl text-pine-900">{t("title")}</h1>
          {docs.length > 0 && (
            <span className="font-mono text-xs text-ink-faint">
              {docs.length} {docs.length === 1 ? "documento" : "documentos"}
            </span>
          )}
        </div>

        {docs.length === 0 ? (
          <div className="ad-card ad-rise mt-6 flex flex-col items-center justify-center px-6 py-16 text-center">
            <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-50 text-pine-400 ring-1 ring-pine-100">
              <FolderOpen className="h-7 w-7" strokeWidth={1.8} />
            </span>
            <p className="mt-5 max-w-sm text-ink-soft">{t("empty")}</p>
            <Link href="/dashboard/upload" className="ad-btn ad-btn-primary mt-6 px-5 py-2.5 text-sm">
              <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
              {t("uploadCta")}
            </Link>
          </div>
        ) : (
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {docs.map((d) => (
              <li key={d.id}>
                <DocumentCard doc={d} locale={locale} />
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
