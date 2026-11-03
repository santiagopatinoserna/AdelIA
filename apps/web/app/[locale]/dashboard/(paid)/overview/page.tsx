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
  const tb = await getTranslations("briefing");
  let docs: DocumentDTO[] = [];
  try {
    docs = await listDocuments();
  } catch {
    // Backend unreachable or 401 — treat as empty list.
    docs = [];
  }

  // What she can do WITH her records. Upload and Modo Consulta used to head
  // this list too, as big cards, but the tab bar (phone) and the header
  // (desktop) already carry both: the menu filled the first screen and pushed
  // "Mis documentos" below the fold (redesign audit, screens 13 to 17). These
  // five have no other door on the phone, so they stay, one tap away, as a
  // quiet row under the title.
  const tools = [
    { href: "/dashboard/chat", icon: MessagesSquare, label: "Chat" },
    { href: "/dashboard/questionnaire", icon: Baby, label: tq("navLabel") },
    { href: "/dashboard/briefings", icon: ClipboardList, label: tb("navLabel") },
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

  // Returning user (has documents): the list first, the tools one row above it.
  return (
    <main className="mx-auto max-w-5xl px-5 py-8 sm:px-6 sm:py-10">
        <InstallPrompt />
        {checkinIndex !== null && <CheckInPrompt initialIndex={checkinIndex} />}

        <div className="flex min-w-0 items-baseline justify-between gap-3">
          <h1 className="min-w-0 text-title text-ink">{t("title")}</h1>
          <span className="shrink-0 text-sm text-ink-soft">
            {t("documentsCount", { count: docs.length })}
          </span>
        </div>

        {/* One row: wrapped, the five pills took three rows (300 px) of a
            390 px phone. It scrolls sideways under the gutter, so the cut
            pill at the edge says there is more; from sm up it wraps. From
            lg up the header's section nav names the same five, labelled,
            so the row only repeated it (rule 18); between md and lg that
            nav shows bare icons and the row stays. */}
        <nav
          aria-label={t("toolsLabel")}
          className="-mx-5 mt-4 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 lg:hidden [&::-webkit-scrollbar]:hidden"
        >
          {tools.map((item) => (
            <Link key={item.href} href={item.href} className="ad-pill shrink-0">
              <item.icon className="h-4 w-4 shrink-0 text-primary-text" strokeWidth={2} aria-hidden />
              {item.label}
            </Link>
          ))}
        </nav>

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
