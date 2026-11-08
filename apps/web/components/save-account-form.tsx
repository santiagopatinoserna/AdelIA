"use client";

import { useActionState, useEffect } from "react";
import { useTranslations } from "next-intl";

import { sendSaveLink, type SaveState } from "@/app/[locale]/dashboard/guardar/actions";
import { track } from "@/lib/analytics";

export function SaveAccountForm({ locale }: { locale: string }) {
  const t = useTranslations("guestSpace");
  const [state, action, pending] = useActionState<SaveState, FormData>(sendSaveLink, {
    status: "idle",
  });
  // Funnel step when the link has gone out (no-op without consent). Never
  // the address she typed.
  useEffect(() => {
    if (state.status === "sent") track("save_requested");
  }, [state.status]);
  if (state.status === "sent") {
    return <p data-testid="save-sent" role="status" className="mt-5 text-base text-ink">{t("saveSent")}</p>;
  }
  return (
    <form action={action} className="mt-5 flex flex-col gap-3">
      <input type="hidden" name="locale" value={locale} />
      <label htmlFor="save-email" className="text-sm font-medium text-ink">{t("saveEmailLabel")}</label>
      <input
        id="save-email"
        name="email"
        type="email"
        required
        autoComplete="email"
        defaultValue={state.email ?? ""}
        className="ad-field min-h-[44px] text-base"
      />
      {state.status === "error" && (
        <p role="alert" className="text-sm text-error-text">{t("saveError")}</p>
      )}
      <button type="submit" disabled={pending} aria-busy={pending} className="ad-btn ad-btn-primary ad-btn-lg">
        {t("saveCta")}
      </button>
    </form>
  );
}
