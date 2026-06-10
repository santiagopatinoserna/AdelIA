"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";
import { useTranslations } from "next-intl";

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
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500">
          {t("emailLabel")}
        </div>
        <div className="mt-1 font-mono text-sm">{email}</div>
      </section>

      <section className="mt-8 rounded-lg border border-rose-300 bg-rose-50 p-4">
        <h2 className="font-semibold text-rose-900">{t("dangerTitle")}</h2>
        <p className="mt-2 text-sm text-rose-800">{t("dangerBody")}</p>
        <label className="mt-4 block text-xs text-rose-900">
          {t("confirmLabel", { email })}
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="mt-1 w-full rounded border border-rose-300 px-3 py-2 font-mono text-sm"
            placeholder={email}
          />
        </label>
        {error && <p className="mt-2 text-sm text-rose-900">{error}</p>}
        <button
          type="button"
          onClick={deleteAccount}
          disabled={!armed || busy}
          className="mt-4 rounded bg-rose-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? t("deleting") : t("deleteButton")}
        </button>
      </section>
    </main>
  );
}
