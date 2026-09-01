import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AccountSettingsView } from "@/components/account-settings-view";
import { billingStatus } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import type { BillingStatus } from "@/lib/api-endpoints";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "settings" });
  return { title: t("title") };
}

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  // "Suscripción" in Settings (audit 4.7). Until 2026-09-01 there was no exit
  // towards billing anywhere in the app: a mother who wanted to change her
  // card or cancel had /billing, which nothing linked to, so every
  // cancellation arrived as a support email or a chargeback.
  //
  // Read here, on the server, and never allowed to fail the page: this screen
  // also holds "export my data" and "delete my account" (GDPR art. 17 and
  // 20), and neither may depend on the billing API answering. A null status
  // renders the section with the honest "we could not read it" line.
  let billing: BillingStatus | null = null;
  try {
    billing = await billingStatus();
  } catch {
    billing = null;
  }

  return <AccountSettingsView email={session.user?.email ?? ""} billing={billing} />;
}
