import { getLocale, getTranslations } from "next-intl/server";
import { auth } from "@/lib/auth";
import { Link } from "@/lib/navigation";
import { AgentCanvas } from "@/components/agent/agent-canvas";

export default async function DashboardHome() {
  const locale = await getLocale();
  const t = await getTranslations("agent");
  // The layout already redirects when there is no session; the id only
  // scopes the showcase's "hide for now" flag to this user.
  const session = await auth();
  const userId = (session?.user as { id?: string } | undefined)?.id ?? "";
  // No ProfileProvider here any more: it moved up to (paid)/layout.tsx so the
  // recorder, the upload zone, the chat and the briefing form share this
  // page's active child instead of each falling back to an empty context
  // (audit 4.2). Nesting a second one here would give the canvas its own
  // switcher again, unheard by every other surface.
  return (
      <div className="relative">
        <AgentCanvas locale={locale} userId={userId} />
        {/* Desktop only: on mobile it overlapped the greeting, and the
            bottom nav's "Historial" tab covers the same destination. */}
        <nav
          aria-label={t("seeAll")}
          className="absolute right-3 top-2 hidden md:block"
        >
          <Link href="/dashboard/overview" className="text-sm text-ink-faint underline">
            {t("seeAll")}
          </Link>
        </nav>
      </div>
  );
}
