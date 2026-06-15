"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, RotateCcw } from "lucide-react";

// Locale-scoped error boundary. Rendered inside the locale layout, so the
// NextIntlClientProvider is present and useTranslations works.
export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("common");

  useEffect(() => {
    console.error("[adelia] route error:", error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="ad-card ad-rise max-w-md p-8 text-center md:p-10">
        <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-clay-50 text-clay-600 ring-1 ring-clay-100">
          <AlertTriangle className="h-7 w-7" strokeWidth={1.8} />
        </span>
        <h1 className="mt-5 text-2xl text-pine-900">{t("errorTitle")}</h1>
        <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">{t("errorBody")}</p>
        <button type="button" onClick={reset} className="ad-btn ad-btn-primary mt-6 px-5 py-2.5 text-sm">
          <RotateCcw className="h-4 w-4" strokeWidth={2.2} />
          {t("retry")}
        </button>
      </div>
    </main>
  );
}
