"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, CreditCard, Download, LogOut } from "lucide-react";

import { ManageButton } from "@/components/billing-actions";
import { InstallSettingsEntry } from "@/components/install-prompt";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link } from "@/lib/navigation";
import type { BillingStatus } from "@/lib/api-endpoints";
import { formatInstant } from "@/lib/dates";
import { clearShowcaseHidden } from "@/lib/showcase-storage";

export function AccountSettingsView({
  email,
  billing = null,
}: {
  email: string;
  billing?: BillingStatus | null;
}) {
  const t = useTranslations("settings");
  const tg = useTranslations("guestSpace");
  const locale = useLocale();
  // A guest of the landing (2026-11-06) has no email to type, no
  // subscription and no way back in once signed out: she confirms the
  // erasure with her baby's name and saves the account instead of paying.
  const isGuest = billing?.is_guest === true;
  const confirmWord = isGuest ? "Lucía" : email;
  const [confirmText, setConfirmText] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Two safeguards before we arm the button: an explicit "I understand"
  // acknowledgement AND typing the full account email. Both must pass.
  const armed =
    acknowledged &&
    confirmText.trim().toLowerCase().normalize("NFD").replace(/\p{M}/gu, "") ===
      confirmWord.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");

  async function deleteAccount() {
    if (!armed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/backend/users/me", { method: "DELETE" });
      if (res.status !== 204) throw new Error(`HTTP ${res.status}`);
      // Leave nothing of this account behind in the tab, not even a UI flag.
      clearShowcaseHidden();
      // Her language, not the bare root: "/" lands on the browser's locale.
      await signOut({ callbackUrl: `/${locale}` });
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
      ? formatInstant(billing.trial_end, locale, "long")
      : null;
  const subscriptionBody = !billing
    ? t("subscriptionUnknownBody")
    : billing.status === "trialing" && trialDate
      ? t("subscriptionTrialBody", { date: trialDate })
      : billing.active
        ? t("subscriptionActiveBody")
        : t("subscriptionNoneBody");

  return (
    // One list instead of five cards: the email is the page's subtitle and
    // each setting a section under a rule, so the screen reads top to bottom
    // without a box per line (redesign direction A, "espacio antes que
    // cajas"). The danger zone keeps its tinted box: that one is a warning.
    <main className="mx-auto max-w-2xl px-5 py-8 sm:px-6 sm:py-12">
      <h1 className="text-title text-ink">{t("title")}</h1>
      {isGuest ? (
        <p className="mt-1 mb-6 text-ink-soft">{tg("settingsGuestBody")}</p>
      ) : (
        <p className="mt-1 mb-6 break-all text-ink-soft">
          <span className="sr-only">{t("emailLabel")}: </span>
          {email}
        </p>
      )}

      {/* GDPR art. 20 portability: a plain <a download> — the browser
          handles the stream, no JS blob juggling, and the endpoint sets
          Content-Disposition so it saves as adelia-export.json. */}
      <section className="border-t border-line py-6">
        <h2 className="font-sans text-lg font-semibold text-ink">{t("exportTitle")}</h2>
        <p className="mt-1.5 text-ink-soft">{t("exportBody")}</p>
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
      {isGuest ? (
      <section className="border-t border-line py-6">
        <h2 className="font-sans text-lg font-semibold text-ink">{tg("saveTitle")}</h2>
        <p className="mt-1.5 text-ink-soft">{tg("saveBody")}</p>
        <Link href="/dashboard/guardar" className="ad-btn ad-btn-primary mt-3 min-h-[44px] px-3.5 py-2 text-sm">
          {tg("saveLink")}
        </Link>
      </section>
      ) : (
      <section className="border-t border-line py-6">
        <h2 className="font-sans text-lg font-semibold text-ink">{t("subscriptionTitle")}</h2>
        <p className="mt-1.5 text-ink-soft">{subscriptionBody}</p>
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
      )}

      {/* On phones the header has no language pill (it ate 174px of a
          390px bar): this is where the language lives on mobile. */}
      <section className="border-t border-line py-6">
        <h2 className="font-sans text-lg font-semibold text-ink">{t("languageTitle")}</h2>
        <p className="mt-1.5 text-ink-soft">{t("languageBody")}</p>
        <div className="mt-3">
          <LocaleSwitcher current={locale} variant="group" />
        </div>
      </section>

      {/* Permanent way to install the PWA: the browser's own prompt shows
          once and iOS never shows one, so Settings always offers the path. */}
      <InstallSettingsEntry />

      {/* The only way out used to be deleting the account: nothing in the app
          called signOut otherwise, so on a shared or lost phone her baby's
          records stayed open (RECORRIDO_POC.md). A full navigation, so no
          in-memory state of this account survives in the tab. */}
      {!isGuest && (
      <section className="border-t border-line py-6">
        <h2 className="font-sans text-lg font-semibold text-ink">{t("signOutTitle")}</h2>
        <p className="mt-1.5 text-ink-soft">{t("signOutBody")}</p>
        <button
          type="button"
          onClick={() => {
            clearShowcaseHidden();
            void signOut({ callbackUrl: `/${locale}` });
          }}
          className="ad-btn ad-btn-ghost mt-3 min-h-[44px] px-3.5 py-2 text-sm"
        >
          <LogOut className="h-4 w-4" strokeWidth={2} />
          {t("signOutCta")}
        </button>
      </section>
      )}

      <section className="mt-6 rounded-2xl border border-error-tint-line bg-error-tint p-5">
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
            className="mt-0.5 h-5 w-5 shrink-0 rounded accent-error"
          />
          <span>{t("ackIrreversible")}</span>
        </label>
        <label htmlFor="confirm-delete" className="mt-3 block text-sm font-medium text-error-text">
          {isGuest ? tg("deleteConfirmLabel") : t("confirmLabel", { email })}
          <input
            id="confirm-delete"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="mt-1.5 min-h-[44px] w-full rounded-lg border border-error-tint-line bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-error"
            placeholder={confirmWord}
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
