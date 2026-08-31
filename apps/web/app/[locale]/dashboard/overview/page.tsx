import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Link } from "@/lib/navigation";
import { getTranslations } from "next-intl/server";
import { listDocuments, type DocumentDTO } from "@/lib/api-client";
import { DocumentCard } from "@/components/document-card";
import { InstallPrompt } from "@/components/install-prompt";
import { CheckInPrompt } from "@/components/check-in-prompt";
import { CHECKIN_COOKIE, checkinIndexFromCookie } from "@/lib/checkin";
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

export default async function DashboardOverview({
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
  const tb = await getTranslations("briefing");
  let docs: DocumentDTO[] = [];
  try {
    docs = await listDocuments();
  } catch {
    // Backend unreachable or 401 — treat as empty list.
    docs = [];
  }

  // Progressive disclosure: surface the 3 core actions prominently, tuck the
  // more advanced ones under a visually lighter "Más opciones" group. Nothing
  // is removed — every feature stays one tap away.
  const primaryNav = [
    { href: "/dashboard/chat", icon: MessagesSquare, label: "Chat" },
    { href: "/dashboard/upload", icon: UploadCloud, label: t("navUpload") },
    { href: "/dashboard/questionnaire", icon: Baby, label: tq("navLabel") },
  ];

  const moreNav = [
    { href: "/dashboard/briefings", icon: ClipboardList, label: tb("navLabel") },
    { href: "/dashboard/consulta", icon: Stethoscope, label: tcons("navLabel") },
    { href: "/dashboard/enrichment", icon: Sparkles, label: t("navInsights") },
    { href: "/dashboard/ingestion", icon: Download, label: t("navImport") },
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
          <span className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
            <Baby className="h-8 w-8" strokeWidth={1.8} />
          </span>
          <h1 className="mt-5 text-balance font-display text-3xl text-ink">
            {t("welcomeTitle")}
          </h1>
          <p className="mx-auto mt-3 max-w-md text-ink-soft">{t("welcomeSubtitle")}</p>
        </div>

        {/* grid-cols-1 = minmax(0,1fr): a bare `grid` makes an `auto` track
            that grows past the viewport when an item's min-content does. */}
        <ol className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {steps.map((s, i) => (
            <li
              key={s.title}
              className="ad-card ad-rise flex min-w-0 flex-col p-5"
              style={{ animationDelay: `${120 + i * 90}ms` }}
            >
              <div className="flex items-center gap-2">
                <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary font-mono text-xs font-semibold text-on-primary">
                  {i + 1}
                </span>
                <s.icon className="h-4.5 w-4.5 text-primary-text" strokeWidth={2} />
              </div>
              <h2 className="mt-3 text-base text-ink">{s.title}</h2>
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
            className="text-sm text-primary-text underline decoration-primary-tint-line underline-offset-2 hover:text-primary-text-hover"
          >
            {t("orQuestionnaire")}
          </Link>
        </div>
      </main>
    );
  }

  // Check-in card: decided here from the cookie (lib/checkin) so it is in
  // the server HTML; a client-side decision inserted it after hydration and
  // shifted the whole page (CLS 0.138 on a phone).
  const checkinIndex = checkinIndexFromCookie((await cookies()).get(CHECKIN_COOKIE)?.value);

  // Returning user (has documents): full quick-access nav + document list.
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
        <InstallPrompt />
        {checkinIndex !== null && <CheckInPrompt initialIndex={checkinIndex} />}

        {/* Core actions — big and obvious for a first-time mom. */}
        <nav aria-label={t("navPrimaryLabel")} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {primaryNav.map((item, i) => (
            <Link
              key={item.href}
              href={item.href}
              className="ad-card ad-card-hover ad-rise flex min-w-0 items-center gap-3 px-5 py-4"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                <item.icon className="h-5 w-5" strokeWidth={2} />
              </span>
              <span className="min-w-0 truncate text-base font-medium text-ink">{item.label}</span>
            </Link>
          ))}
        </nav>

        {/* Advanced features — lighter, grouped, never in the way. */}
        <div className="mt-7">
          <p className="ad-eyebrow text-ink-faint">{t("navMoreLabel")}</p>
          <nav
            aria-label={t("navMoreLabel")}
            className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4"
          >
            {moreNav.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                className="ad-card ad-card-hover ad-rise flex min-w-0 items-center gap-2.5 bg-surface-2/40 px-3.5 py-3"
                style={{ animationDelay: `${(primaryNav.length + i) * 60}ms` }}
              >
                <item.icon className="h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} />
                <span className="min-w-0 text-sm leading-snug text-ink-soft">{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>

        <div className="mt-12 flex min-w-0 items-baseline justify-between gap-3">
          <h1 className="min-w-0 text-2xl text-ink">{t("title")}</h1>
          <span className="shrink-0 font-mono text-xs text-ink-faint">
            {t("documentsCount", { count: docs.length })}
          </span>
        </div>

        {/* Same minmax(0,1fr) rule: this list was 404px wide on a 390px
            phone (a long file name's min-content) and pushed the tab bar. */}
        <ul className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {docs.map((d) => (
            <li key={d.id} className="min-w-0">
              <DocumentCard doc={d} locale={locale} />
            </li>
          ))}
        </ul>
    </main>
  );
}
