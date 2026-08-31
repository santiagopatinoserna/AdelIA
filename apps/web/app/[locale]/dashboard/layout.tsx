import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Settings, UploadCloud } from "lucide-react";

import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { DashboardSectionNav } from "@/components/dashboard-section-nav";
import { MobileBottomNav } from "@/components/mobile-bottom-nav";
import { CommandPalette } from "@/components/command-palette";
import { OnlineStatus } from "@/components/online-status";
import { RecordingGuardProvider } from "@/lib/recording-guard";

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

  // The paywall gate moved to dashboard/(paid)/layout.tsx, one level down.
  // It has to skip /dashboard/settings: that screen holds "export my data"
  // and "delete my account", and a mother who cancels must keep both (GDPR
  // art. 17 and 20). Redirecting from here sent her to /billing from settings
  // too, and /billing links nowhere back. Session and chrome stay here, so
  // settings keeps its header and navigation.

  const t = await getTranslations("dashboard");

  // RecordingGuardProvider: while a consult is being recorded every link,
  // tab and switch in this shell asks before leaving (see lib/recording-guard).
  return (
    <RecordingGuardProvider>
    <div className="flex min-h-[100dvh] flex-col">
      <OnlineStatus />
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line/70 bg-canvas/80 px-4 backdrop-blur-md md:px-6">
        <div data-nav-lock className="flex min-w-0 items-center gap-4">
          {/* min-h 44px: a touch target like every other control of the shell. */}
          <Link
            href="/dashboard"
            className="inline-flex min-h-[44px] items-center font-display text-xl font-semibold tracking-tight text-ink"
          >
            Adel<span className="text-accent-text">IA</span>
          </Link>
          <DashboardSectionNav />
        </div>
        <div data-nav-lock className="flex shrink-0 items-center gap-2.5">
          {/* Search, language and settings live in the bottom nav / Settings
              on mobile; keeping them here squeezed the section nav (and even
              the logo) to zero width on a 390px viewport, and the language
              pill alone took 174px of it. */}
          <div className="hidden sm:block">
            <CommandPalette />
          </div>
          <div className="hidden md:block">
            <LocaleSwitcher current={locale} />
          </div>
          <Link
            href="/dashboard/settings"
            aria-label={t("settingsLink")}
            className="ad-btn ad-btn-ghost ad-btn-icon hidden md:inline-flex"
          >
            <Settings className="h-4 w-4" strokeWidth={2} />
          </Link>
          {/* Icon-only below sm: the aria-label is its accessible name, and
              the 44px box is the minimum touch target. */}
          <Link
            href="/dashboard/upload"
            aria-label={t("uploadCta")}
            className="ad-btn ad-btn-primary min-h-[44px] min-w-[44px] px-3.5 py-2 text-sm"
          >
            <UploadCloud className="h-4 w-4" strokeWidth={2.2} />
            <span className="hidden sm:inline">{t("uploadCta")}</span>
          </Link>
        </div>
      </header>
      {/* Matches the tab bar's h-14 PLUS its safe-area padding — plain pb-14
          left the last element hidden behind the bar on notched iPhones.
          `ad-mobile-shell`: the padding drops while the on-screen keyboard
          has a text field focused (html.kb-open, set by MobileBottomNav). */}
      <div className="ad-mobile-shell flex-1 pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0">{children}</div>
      <MobileBottomNav />
    </div>
    </RecordingGuardProvider>
  );
}
