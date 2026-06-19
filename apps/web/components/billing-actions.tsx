"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, CreditCard, Settings2, AlertCircle } from "lucide-react";

// Hits the authed proxy (which signs with the session JWT server-side), then
// hands off to Stripe's hosted page. We never touch card data ourselves.
async function redirectToStripe(path: "checkout" | "portal") {
  const res = await fetch(`/api/backend/billing/${path}`, { method: "POST" });
  if (!res.ok) throw new Error(String(res.status));
  const data = (await res.json()) as { url?: string };
  if (!data.url) throw new Error("no url");
  window.location.href = data.url;
}

export function StartTrialButton() {
  const t = useTranslations("billing");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);

  return (
    <div>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setErr(false);
          try {
            await redirectToStripe("checkout");
          } catch {
            setErr(true);
            setBusy(false);
          }
        }}
        className="ad-btn ad-btn-primary w-full py-3.5 text-base disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" strokeWidth={2.2} />
        ) : (
          <CreditCard className="h-5 w-5" strokeWidth={2.2} />
        )}
        {t("startCta")}
      </button>
      {err && (
        <p role="alert" className="mt-3 flex items-center justify-center gap-1.5 text-sm text-clay-600">
          <AlertCircle className="h-4 w-4 shrink-0" strokeWidth={2.2} />
          {t("errorMsg")}
        </p>
      )}
    </div>
  );
}

export function ManageButton() {
  const t = useTranslations("billing");
  const [busy, setBusy] = useState(false);

  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await redirectToStripe("portal");
        } catch {
          setBusy(false);
        }
      }}
      className="ad-btn ad-btn-ghost px-5 py-2.5 text-sm disabled:opacity-60"
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
      ) : (
        <Settings2 className="h-4 w-4" strokeWidth={2} />
      )}
      {t("manageCta")}
    </button>
  );
}
