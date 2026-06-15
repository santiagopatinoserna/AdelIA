import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Settings, UploadCloud } from "lucide-react";

import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { DashboardSectionNav } from "@/components/dashboard-section-nav";

// Persistent chrome for every authenticated page: wordmark (→ dashboard),
// language, settings, upload. Sub-pages used to render bare, with no way to
// navigate, switch locale, or get home — this gives the app a consistent shell.
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);
  const t = await getTranslations("dashboard");

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line/70 bg-canvas/80 px-4 backdrop-blur-md md:px-6">
        <div className="flex min-w-0 items-center gap-4">
          <Link
            href="/dashboard"
            className="font-display text-xl font-semibold tracking-tight text-pine-900"
          >
            Adel<span className="text-honey-500">IA</span>
          </Link>
          <DashboardSectionNav />
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <LocaleSwitcher current={locale} />
          <Link
            href="/dashboard/settings"
            aria-label={t("settingsLink")}
            className="ad-btn ad-btn-ghost h-9 w-9 p-0"
          >
            <Settings className="h-4 w-4" strokeWidth={2} />
          </Link>
          <Link href="/dashboard/upload" className="ad-btn ad-btn-primary px-3.5 py-2 text-sm">
            <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
            <span className="hidden sm:inline">{t("uploadCta")}</span>
          </Link>
        </div>
      </header>
      <div className="flex-1">{children}</div>
    </div>
  );
}
