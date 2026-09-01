"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, CreditCard, Download } from "lucide-react";

import { ManageButton } from "@/components/billing-actions";
import { InstallSettingsEntry } from "@/components/install-prompt";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link } from "@/lib/navigation";
import type { BillingStatus } from "@/lib/api-endpoints";
import { clearShowcaseHidden } from "@/lib/showcase-storage";

export function AccountSettingsView({
  email,
  billing = null,
}: {
  email: string;
  billing?: BillingStatus | null;
}) {
  const t = useTranslations("settings");
  const locale = useLocale();
  const [confirmText, setConfirmText] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Two safeguards before we arm the button: an explicit "I understand"
  // acknowledgement AND typing the full account email. Both must pass.
  const armed =
    acknowledged && confirmText.trim().toLowerCase() === email.toLowerCase();

  async function deleteAccount() {
    if (!armed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/backend/users/me", { method: "DELETE" });
      if (res.status !== 204) throw new Error(`HTTP ${res.status}`);
      // Leave nothing of this account behind in the tab, not even a UI flag.
      clearShowcaseHidden();
      await signOut({ callbackUrl: "/" });
    } catch (e) {
      setError(t("actionError"));
      setBusy(false);
    }
  }

  // One sentence describing where the account stands. The card-free trial is
  // reported by the API through the same keys as a Stripe one (status
  // "trialing" plus trial_end), so this needs no second concept.
  const trialDate =
    billing?.trial_end
      ? new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(
          new Date(billing.trial_end),
        )
      : null;
  const subscriptionBody = !billing
    ? t("subscriptionUnknownBody")
    : billing.status === "trialing" && trialDate
      ? t("subscriptionTrialBody", { date: trialDate })
      : billing.active
        ? t("subscriptionActiveBody")
        : t("subscriptionNoneBody");

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl text-ink">{t("title")}</h1>
      <section className="ad-card mt-6 p-4">
        <div className="ad-eyebrow">{t("emailLabel")}</div>
        <div className="mt-1.5 font-mono text-sm text-ink">{email}</div>
      </section>

      {/* GDPR art. 20 portability: a plain <a download> — the browser
          handles the stream, no JS blob juggling, and the endpoint sets
          Content-Disposition so it saves as adelia-export.json. */}
      <section className="ad-card mt-6 p-4">
        <div className="ad-eyebrow">{t("exportTitle")}</div>
        <p className="mt-1.5 text-sm text-ink-soft">{t("exportBody")}</p>
        <a
          href="/api/backend/users/me/export"
          download="adelia-export.json"
          className="ad-btn ad-btn-ghost mt-3 min-h-[44px] px-3.5 py-2 text-sm"
        >
          <Download className="h-4 w-4" strokeWidth={2} />
          {t("exportCta")}
        </a>
      </section>

      {/* Subscription (audit 4.7). The product had no exit towards billing
          from anywhere inside it: /billing existed and nothing linked to it,
          so changing a card or cancelling meant an email to support, which is
          also the opposite of the European rule that unsubscribing be as easy
          as subscribing.

          Two states, one click each. With a Stripe customer behind the
          account the button opens the Stripe portal (card, invoices, cancel);
          without one there is nothing for the portal to show, so the link
          goes to /billing instead of a button that would answer 400. */}
      <section className="ad-card mt-6 p-4">
        <div className="ad-eyebrow">{t("subscriptionTitle")}</div>
        <p className="mt-1.5 text-sm text-ink-soft">{subscriptionBody}</p>
        <div className="mt-3">
          {billing?.can_manage ? (
            <ManageButton />
          ) : (
            <Link
              href="/billing"
              className="ad-btn ad-btn-ghost min-h-[44px] px-3.5 py-2 text-sm"
            >
              <CreditCard className="h-4 w-4" strokeWidth={2} />
              {t("subscriptionSubscribeCta")}
            </Link>
          )}
        </div>
      </section>

      {/* On phones the header has no language pill (it ate 174px of a
          390px bar): this is where the language lives on mobile. */}
      <section className="ad-card mt-6 p-4">
        <div className="ad-eyebrow">{t("languageTitle")}</div>
        <p className="mt-1.5 text-sm text-ink-soft">{t("languageBody")}</p>
        <div className="mt-3">
          <LocaleSwitcher current={locale} variant="group" />
        </div>
      </section>

      {/* Permanent way to install the PWA: the browser's own prompt shows
          once and iOS never shows one, so Settings always offers the path. */}
      <InstallSettingsEntry />

      <section className="mt-8 rounded-2xl border border-error-tint-line bg-error-tint p-5">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-error-text">
          <AlertTriangle className="h-4 w-4" strokeWidth={2.2} />
          {t("dangerTitle")}
        </h2>
        <p className="mt-2 text-sm text-error-text">{t("dangerBody")}</p>
        <label className="mt-4 flex min-h-[44px] cursor-pointer items-start gap-2.5 text-sm text-error-text">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded"
          />
          <span>{t("ackIrreversible")}</span>
        </label>
        <label htmlFor="confirm-delete" className="mt-3 block text-xs font-medium text-error-text">
          {t("confirmLabel", { email })}
          <input
            id="confirm-delete"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="mt-1.5 min-h-[44px] w-full rounded-lg border border-error-tint-line bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-error"
            placeholder={email}
          />
        </label>
        {error && (
          <p className="mt-2 text-sm font-medium text-error-text" role="alert">
            {error}
          </p>
        )}
        <button
          type="button"
          onClick={deleteAccount}
          disabled={!armed || busy}
          className="ad-btn ad-btn-danger mt-4 min-h-[44px] px-4 py-2 text-sm font-medium"
          aria-busy={busy}
        >
          {busy ? t("deleting") : t("deleteButton")}
        </button>
      </section>
    </main>
  );
}
