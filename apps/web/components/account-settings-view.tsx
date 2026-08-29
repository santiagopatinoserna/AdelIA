"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Download } from "lucide-react";

import { clearShowcaseHidden } from "@/lib/showcase-storage";

export function AccountSettingsView({ email }: { email: string }) {
  const t = useTranslations("settings");
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

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl text-pine-900">{t("title")}</h1>
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
          className="ad-btn ad-btn-ghost mt-3 px-3.5 py-2 text-sm"
        >
          <Download className="h-4 w-4" strokeWidth={2} />
          {t("exportCta")}
        </a>
      </section>

      <section className="mt-8 rounded-2xl border border-clay-100 bg-clay-50 p-5">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-clay-700">
          <AlertTriangle className="h-4 w-4" strokeWidth={2.2} />
          {t("dangerTitle")}
        </h2>
        <p className="mt-2 text-sm text-clay-700">{t("dangerBody")}</p>
        <label className="mt-4 flex min-h-[44px] cursor-pointer items-start gap-2.5 text-sm text-clay-700">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-clay-100 text-clay-500 focus:ring-2 focus:ring-clay-100"
          />
          <span>{t("ackIrreversible")}</span>
        </label>
        <label htmlFor="confirm-delete" className="mt-3 block text-xs font-medium text-clay-700">
          {t("confirmLabel", { email })}
          <input
            id="confirm-delete"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="mt-1.5 min-h-[44px] w-full rounded-lg border border-clay-100 bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-clay-500 focus:outline-none focus:ring-2 focus:ring-clay-100"
            placeholder={email}
          />
        </label>
        {error && (
          <p className="mt-2 text-sm font-medium text-clay-700" role="alert">
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
