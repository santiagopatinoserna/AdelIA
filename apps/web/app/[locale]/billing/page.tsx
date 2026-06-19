import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { Baby, Check, ShieldCheck, Sparkles } from "lucide-react";

import { billingStatus } from "@/lib/api-client";
import { Link } from "@/lib/navigation";
import { StartTrialButton, ManageButton } from "@/components/billing-actions";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "billing" });
  return { title: t("title") };
}

export default async function BillingPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ checkout?: string }>;
}) {
  const { locale } = await params;
  const { checkout } = await searchParams;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations("billing");

  let active = false;
  let trialEnd: string | null = null;
  try {
    const b = await billingStatus();
    active = b.active;
    trialEnd = b.trial_end;
  } catch {
    // API hiccup — show the offer; the gate fails open elsewhere.
  }

  const fmtDate = (iso: string | null) =>
    iso
      ? new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(iso))
      : "";

  return (
    <main className="flex min-h-[100dvh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md">
        <Link
          href="/dashboard"
          className="font-display text-2xl font-semibold tracking-tight text-pine-900"
        >
          Adel<span className="text-honey-500">IA</span>
        </Link>

        {checkout === "success" && (
          <p className="ad-card ad-rise mt-5 border-pine-200 bg-pine-50/60 p-3 text-sm text-pine-800">
            {t("successNote")}
          </p>
        )}
        {checkout === "cancel" && !active && (
          <p className="ad-card mt-5 border-honey-200 bg-honey-100/40 p-3 text-sm text-ink">
            {t("canceledNote")}
          </p>
        )}

        {active ? (
          <div className="ad-card ad-rise mt-5 p-8">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
              <Sparkles className="h-6 w-6" strokeWidth={1.8} />
            </span>
            <h1 className="mt-4 text-2xl text-pine-900">{t("activeTitle")}</h1>
            <p className="mt-2 text-sm text-ink-soft">
              {trialEnd ? t("trialUntil", { date: fmtDate(trialEnd) }) : t("activeBody")}
            </p>
            <div className="mt-6 flex flex-col gap-3">
              <Link href="/dashboard" className="ad-btn ad-btn-primary py-3 text-sm">
                {t("goDashboard")}
              </Link>
              <ManageButton />
            </div>
          </div>
        ) : (
          <div className="ad-card ad-rise mt-5 p-8">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-honey-100 text-honey-600 ring-1 ring-honey-200">
              <Baby className="h-6 w-6" strokeWidth={1.8} />
            </span>
            <h1 className="mt-4 text-balance font-display text-3xl text-pine-900">
              {t("title")}
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-ink-soft">{t("subtitle")}</p>

            <div className="mt-5 flex items-baseline gap-2">
              <span className="text-lg font-semibold text-pine-700">{t("priceFree")}</span>
              <span className="text-sm text-ink-faint">·</span>
              <span className="text-sm text-ink-soft">{t("priceThen")}</span>
            </div>

            <ul className="mt-5 space-y-2.5">
              {[t("f1"), t("f2"), t("f3"), t("f4")].map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-sm text-ink">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-pine-500" strokeWidth={2.4} />
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            <div className="mt-7">
              <StartTrialButton />
            </div>

            <p className="mt-4 text-xs leading-relaxed text-ink-faint">{t("cardNote")}</p>
            <p className="mt-3 flex items-center gap-1.5 text-xs text-pine-600">
              <ShieldCheck className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
              {t("secure")}
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
