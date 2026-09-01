import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { auth } from "@/lib/auth";
import { onboarding } from "@/lib/api-client";
import { BabyOnboardingForm } from "@/components/baby-onboarding";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "onboarding" });
  // Never indexed: it is a one-off account screen, not a public page.
  return { title: t("title"), robots: { index: false, follow: false } };
}

function isRedirect(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "digest" in err &&
    typeof (err as { digest?: unknown }).digest === "string" &&
    (err as { digest: string }).digest.startsWith("NEXT_REDIRECT")
  );
}

// Deliberately OUTSIDE the /dashboard tree. The gate that sends a new account
// here lives in dashboard/layout.tsx, and a screen rendered under that same
// layout would redirect to itself for ever.
export default async function OnboardingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  // Asked once. Someone who already answered (or skipped, or told the agent
  // her baby's date of birth) and lands here by typing the URL goes on to the
  // panel instead of being asked again.
  try {
    const status = await onboarding.status();
    if (!status.needed) redirect(`/${locale}/dashboard`);
  } catch (err) {
    if (isRedirect(err)) throw err;
    // Status unreadable: show the screen. It is skippable, so the worst case
    // is one extra tap, never a locked door.
  }

  const t = await getTranslations("onboarding");

  return (
    <main className="mx-auto flex min-h-[100dvh] max-w-lg flex-col justify-center px-6 py-10">
      <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
        {t("title")}
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-ink-soft">{t("subtitle")}</p>
      <div className="mt-6">
        <BabyOnboardingForm locale={locale} />
      </div>
    </main>
  );
}
