"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

export function AccountSettingsView({ email }: { email: string }) {
  const t = useTranslations("settings");
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const armed = confirmText.trim().toLowerCase() === email.toLowerCase();

  async function deleteAccount() {
    if (!armed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/backend/users/me", { method: "DELETE" });
      if (res.status !== 204) throw new Error(`HTTP ${res.status}`);
      await signOut({ callbackUrl: "/" });
    } catch (e) {
      setError(String(e));
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

      <section className="mt-8 rounded-2xl border border-clay-100 bg-clay-50 p-5">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-clay-700">
          <AlertTriangle className="h-4 w-4" strokeWidth={2.2} />
          {t("dangerTitle")}
        </h2>
        <p className="mt-2 text-sm text-clay-700">{t("dangerBody")}</p>
        <label htmlFor="confirm-delete" className="mt-4 block text-xs font-medium text-clay-700">
          {t("confirmLabel", { email })}
          <input
            id="confirm-delete"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="mt-1.5 w-full rounded-lg border border-clay-100 bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-clay-500 focus:outline-none focus:ring-2 focus:ring-clay-100"
            placeholder={email}
          />
        </label>
        {error && <p className="mt-2 text-sm font-medium text-clay-700">{error}</p>}
        <button
          type="button"
          onClick={deleteAccount}
          disabled={!armed || busy}
          className="ad-btn ad-btn-danger mt-4 px-4 py-2 text-sm font-medium"
        >
          {busy ? t("deleting") : t("deleteButton")}
        </button>
      </section>
    </main>
  );
}
