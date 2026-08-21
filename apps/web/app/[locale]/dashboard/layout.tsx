import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Settings, UploadCloud } from "lucide-react";

import { billingStatus } from "@/lib/api-client";
import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { DashboardSectionNav } from "@/components/dashboard-section-nav";
import { MobileBottomNav } from "@/components/mobile-bottom-nav";
import { CommandPalette } from "@/components/command-palette";
import { OnlineStatus } from "@/components/online-status";

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

  // Paywall: a mom needs an active trial or subscription to use the product.
  // Fail-open on a transient API error so a hiccup never locks out a paying
  // user; Stripe webhooks remain the source of truth for the status itself.
  try {
    const billing = await billingStatus();
    if (!billing.active) redirect(`/${locale}/billing`);
  } catch (err) {
    // Next's redirect() throws a NEXT_REDIRECT signal — never swallow it.
    if (
      typeof err === "object" &&
      err !== null &&
      "digest" in err &&
      typeof (err as { digest?: unknown }).digest === "string" &&
      (err as { digest: string }).digest.startsWith("NEXT_REDIRECT")
    ) {
      throw err;
    }
    // genuine fetch error → allow access (fail open)
  }

  const t = await getTranslations("dashboard");

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <OnlineStatus />
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
          {/* Search and settings live in the bottom nav / its screens on
              mobile; keeping them here squeezed the section nav (and even the
              logo) to zero width on a 390px viewport. */}
          <div className="hidden sm:block">
            <CommandPalette />
          </div>
          <LocaleSwitcher current={locale} />
          <Link
            href="/dashboard/settings"
            aria-label={t("settingsLink")}
            className="ad-btn ad-btn-ghost hidden h-9 w-9 p-0 md:inline-flex"
          >
            <Settings className="h-4 w-4" strokeWidth={2} />
          </Link>
          <Link href="/dashboard/upload" className="ad-btn ad-btn-primary px-3.5 py-2 text-sm">
            <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
            <span className="hidden sm:inline">{t("uploadCta")}</span>
          </Link>
        </div>
      </header>
      {/* Matches the tab bar's h-14 PLUS its safe-area padding — plain pb-14
          left the last element hidden behind the bar on notched iPhones. */}
      <div className="flex-1 pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0">{children}</div>
      <MobileBottomNav />
    </div>
  );
}
