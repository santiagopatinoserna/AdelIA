"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/lib/navigation";
import { AlertTriangle, RotateCcw, Home } from "lucide-react";

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
      {/* No ad-rise on the root: content starting at opacity 0 never reports FCP. */}
      <div className="ad-card max-w-md p-8 text-center md:p-10">
        <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-error-tint text-error-text ring-1 ring-error-tint-line">
          <AlertTriangle className="h-7 w-7" strokeWidth={1.8} />
        </span>
        <h1 className="mt-5 text-2xl text-ink">{t("errorTitle")}</h1>
        <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">{t("errorBody")}</p>
        <div className="mt-6 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
          <button
            type="button"
            onClick={reset}
            className="ad-btn ad-btn-primary min-h-[44px] w-full px-5 py-2.5 text-sm sm:w-auto"
          >
            <RotateCcw className="h-4 w-4" strokeWidth={2.2} />
            {t("retry")}
          </button>
          <Link href="/" className="ad-btn ad-btn-ghost min-h-[44px] w-full px-5 py-2.5 text-sm sm:w-auto">
            <Home className="h-4 w-4" strokeWidth={2.2} />
            {t("backHome")}
          </Link>
        </div>
        {error.digest && (
          <p className="mt-5 text-xs text-ink-faint">
            {t("errorId", { id: error.digest.slice(0, 8) })}
          </p>
        )}
      </div>
    </main>
  );
}
