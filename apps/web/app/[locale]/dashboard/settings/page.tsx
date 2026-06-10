import { redirect } from "next/navigation";

import { AccountSettingsView } from "@/components/account-settings-view";
import { auth } from "@/lib/auth";

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  return <AccountSettingsView email={session.user?.email ?? ""} />;
}
