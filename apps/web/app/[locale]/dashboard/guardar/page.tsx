import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { SaveAccountForm } from "@/components/save-account-form";
import { adoptGuest } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import { Link } from "@/lib/navigation";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "guestSpace" });
  return { title: t("saveTitle") };
}

// Outside the (paid) group on purpose: the account a magic link has just
// created has no child yet, and the paid layout would send it to the
// onboarding screen before it could adopt Lucía here.
export default async function SaveAccountPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ token?: string }>;
}) {
  const { locale } = await params;
  const { token } = await searchParams;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);
  const t = await getTranslations("guestSpace");

  if (token) {
    const adopted = await adoptGuest(token).catch(() => false);
    if (adopted) redirect(`/${locale}/dashboard`);
    return (
      <main className="mx-auto max-w-lg px-5 py-10">
        <h1 className="text-title text-ink">{t("saveTitle")}</h1>
        <p role="alert" className="mt-3 text-ink-soft">{t("saveFailed")}</p>
        <Link href="/dashboard" className="ad-btn ad-btn-ghost mt-5 min-h-[44px] px-4">
          {t("backToPanel")}
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-lg px-5 py-10">
      <h1 className="text-title text-ink">{t("saveTitle")}</h1>
      <p className="mt-3 text-ink-soft">{t("saveBody")}</p>
      <SaveAccountForm locale={locale} />
    </main>
  );
}
