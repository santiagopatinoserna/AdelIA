import { redirect } from "next/navigation";
import { getLocale } from "next-intl/server";

import { billingStatus } from "@/lib/api-client";

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
    // Status unreadable: let her through and let the API decide.
  }

  return <>{children}</>;
}
