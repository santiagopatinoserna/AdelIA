import { redirect } from "next/navigation";
import { getLocale } from "next-intl/server";

import { billingStatus, enrichment, onboarding } from "@/lib/api-client";
import type { Profile } from "@/lib/enrichment-types";
import { ProfileProvider } from "@/lib/profile-context";

// The paywall gate, and nothing else. It lives in a route group so it covers
// the product screens WITHOUT covering /dashboard/settings, which holds
// "export my data" and "delete my account" (GDPR art. 17 and 20). While this
// block sat in dashboard/layout.tsx, a mother who cancelled was redirected to
// /billing from every dashboard URL, settings included, and /billing has no
// link back to it: the only door left to her own data was the raw API.
//
// Route groups do not change URLs, so every /dashboard/* path is exactly what
// it was.
//
// Fail-OPEN on a genuine fetch error, deliberately. This used to redirect on
// any exception, which turned a transient API blip into an eviction for a
// paying user, sent to a /billing page that could not sell her anything
// either. The real gate is the API, which answers 402 per route
// (adelia/auth.require_active_subscription); this redirect is a courtesy that
// spares her a screen full of failed requests, not a security boundary, and a
// courtesy must not lock the door when it cannot read the lock.
function isRedirect(err: unknown): boolean {
  // Next's redirect() throws a NEXT_REDIRECT signal — never swallow it.
  return (
    typeof err === "object" &&
    err !== null &&
    "digest" in err &&
    typeof (err as { digest?: unknown }).digest === "string" &&
    (err as { digest: string }).digest.startsWith("NEXT_REDIRECT")
  );
}

export default async function PaidDashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();
  try {
    const billing = await billingStatus();
    if (!billing.active) redirect(`/${locale}/billing`);
  } catch (err) {
    if (isRedirect(err)) throw err;
    // Status unreadable: let her through and let the API decide.
  }

  // The baby screen, once, before the panel (audit 4.3). It sits in the same
  // pass-through layout as the paywall, and NOT in dashboard/layout.tsx, for
  // two reasons. The product one: /dashboard/settings holds "export my data"
  // and "delete my account", and no question stands between a parent and
  // those. The mechanical one: dashboard/layout.tsx renders the whole shell,
  // and adding either an await or a client provider to THAT layout makes Next
  // stream the shell and its children separately, so for a few milliseconds
  // after every navigation the page exists twice in the DOM. Harmless to a
  // human, fatal to any test that asserts on a unique element, and measured:
  // diary.spec.ts failed 3 runs out of 3 with the gate up there and passes 3
  // out of 3 with it here. This layout renders no markup of its own, so it
  // has neither effect.
  //
  // The screen itself lives at /{locale}/onboarding, outside every dashboard
  // layout: a page under this one would redirect to itself for ever.
  //
  // Fail-OPEN, like the paywall above: a transient API error must not stand
  // between a mother and her baby's records.
  //
  // The profile list for ProfileProvider, in flight while the onboarding
  // status is awaited (fail-open to an empty list, as the browser fetch it
  // replaces did). It is fetched HERE and handed to the provider as its first
  // render, not fetched by the provider after mount: see lib/profile-context.
  const profilesPromise = enrichment.listProfiles().catch((): Profile[] => []);
  try {
    const status = await onboarding.status();
    if (status.needed) redirect(`/${locale}/onboarding`);
  } catch (err) {
    if (isRedirect(err)) throw err;
  }
  const initialProfiles = await profilesPromise;

  // ProfileProvider: ONE active child for every paid surface — the consult
  // recorder, the upload zone, the chat, the briefing form and the agent
  // canvas all read it (audit 4.2). It used to wrap only the agent home, so
  // the recorder, which renders a profile selector from this very context,
  // read the empty default: no profiles, activeId null, and an appointment
  // recording filed under no child at all.
  return <ProfileProvider initialProfiles={initialProfiles}>{children}</ProfileProvider>;
}
