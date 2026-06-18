import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Link } from "@/lib/navigation";
import { getTranslations } from "next-intl/server";
import { listDocuments, type DocumentDTO } from "@/lib/api-client";
import { DocumentCard } from "@/components/document-card";
import { InstallPrompt } from "@/components/install-prompt";
import {
  MessagesSquare,
  ClipboardList,
  Download,
  Sparkles,
  UploadCloud,
  Baby,
  Stethoscope,
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
  const tcons = await getTranslations("consulta");
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
    { href: "/dashboard/consulta", icon: Stethoscope, label: tcons("navLabel") },
    { href: "/dashboard/ingestion", icon: Download, label: t("navImport") },
    { href: "/dashboard/enrichment", icon: Sparkles, label: t("navInsights") },
  ];

  const steps = [
    { icon: UploadCloud, title: t("step1Title"), body: t("step1Body") },
    { icon: MessagesSquare, title: t("step2Title"), body: t("step2Body") },
    { icon: ClipboardList, title: t("step3Title"), body: t("step3Body") },
  ];

  // First run (no documents): a calm, guided welcome — one clear path, no
  // jargon nav. A mom who has never done this should know exactly what to do.
  if (docs.length === 0) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <InstallPrompt />
        <div className="ad-rise text-center">
          <span className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
            <Baby className="h-8 w-8" strokeWidth={1.8} />
          </span>
          <h1 className="mt-5 text-balance font-display text-3xl text-pine-900">
            {t("welcomeTitle")}
          </h1>
          <p className="mx-auto mt-3 max-w-md text-ink-soft">{t("welcomeSubtitle")}</p>
        </div>

        <ol className="mt-10 grid gap-3 sm:grid-cols-3">
          {steps.map((s, i) => (
            <li
              key={s.title}
              className="ad-card ad-rise flex flex-col p-5"
              style={{ animationDelay: `${120 + i * 90}ms` }}
            >
              <div className="flex items-center gap-2">
                <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-pine-600 font-mono text-xs font-semibold text-[#f3f7f3]">
                  {i + 1}
                </span>
                <s.icon className="h-4.5 w-4.5 text-pine-500" strokeWidth={2} />
              </div>
              <h2 className="mt-3 text-base text-pine-900">{s.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-ink-soft">{s.body}</p>
            </li>
          ))}
        </ol>

        <div className="mt-9 flex flex-col items-center gap-3">
          <Link href="/dashboard/upload" className="ad-btn ad-btn-primary px-6 py-3 text-base">
            <UploadCloud className="h-4.5 w-4.5" strokeWidth={2.2} />
            {t("firstUploadCta")}
          </Link>
          <Link
            href="/dashboard/questionnaire"
            className="text-sm text-pine-600 underline decoration-pine-200 underline-offset-2 hover:text-pine-700"
          >
            {t("orQuestionnaire")}
          </Link>
        </div>
      </main>
    );
  }

  // Returning user (has documents): full quick-access nav + document list.
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
        <InstallPrompt />
        <nav className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
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

        <div className="mt-12 flex items-baseline justify-between">
          <h1 className="text-2xl text-pine-900">{t("title")}</h1>
          <span className="font-mono text-xs text-ink-faint">
            {t("documentsCount", { count: docs.length })}
          </span>
        </div>

        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {docs.map((d) => (
            <li key={d.id}>
              <DocumentCard doc={d} locale={locale} />
            </li>
          ))}
        </ul>
    </main>
  );
}
