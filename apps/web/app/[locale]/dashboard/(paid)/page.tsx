import { getLocale, getTranslations } from "next-intl/server";
import { auth } from "@/lib/auth";
import { Link } from "@/lib/navigation";
import { AgentCanvas } from "@/components/agent/agent-canvas";
import { TrackStep } from "@/components/analytics";
import { TodayFollowsChild, TodaySlot } from "@/components/today-follows-child";
import { agentThread, billingStatus, today } from "@/lib/api-client";

export default async function DashboardHome({
  searchParams,
}: {
  searchParams: Promise<{ ask?: string; cuenta?: string }>;
}) {
  // `ask`: the key of the question she typed on the landing (components/
  // demo-ask). The text itself waits in this tab's sessionStorage, not in the
  // URL, so a health question never lands in a server log or the history bar.
  // `cuenta=guardada`: "Guardar mi cuenta" has just adopted her guest space
  // (dashboard/guardar), a step of the consented funnel.
  const { ask, cuenta } = await searchParams;
  const locale = await getLocale();
  const t = await getTranslations("agent");
  // The layout already redirects when there is no session; the id only
  // scopes the showcase's "hide for now" flag to this user.
  const session = await auth();
  const userId = (session?.user as { id?: string } | undefined)?.id ?? "";
  // "Hoy con <nombre>" (vision note 2026-10-22): fetched here, next to the
  // other server-side reads, for the DEFAULT child, which is the same child
  // the ProfileProvider starts on. Fail-open to nothing: a transient API
  // error must not stand between a mother and the greeting. When she picks
  // another child, TodayFollowsChild asks for that child's day in the browser.
  //
  // The conversation she was in (stored since 2026-11-06, GET /agent/thread),
  // so a reload picks it up, and whether she is a guest, for "Guardar mi
  // cuenta". Both fail open to nothing, like "Hoy".
  const [due, thread, billing] = await Promise.all([
    today(locale).catch(() => null),
    agentThread().catch(() => null),
    billingStatus().catch(() => null),
  ]);
  // No ProfileProvider here any more: it moved up to (paid)/layout.tsx so the
  // recorder, the upload zone, the chat and the briefing form share this
  // page's active child instead of each falling back to an empty context
  // (audit 4.2). Nesting a second one here would give the canvas its own
  // switcher again, unheard by every other surface.
  return (
      <div className="relative">
        {cuenta === "guardada" && <TrackStep step="account_saved" />}
        <TodayFollowsChild initial={due} locale={locale}>
          <AgentCanvas
            locale={locale}
            userId={userId}
            today={<TodaySlot />}
            initialThread={thread}
            askKey={ask ?? null}
            isGuest={billing?.is_guest === true}
          />
        </TodayFollowsChild>
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
