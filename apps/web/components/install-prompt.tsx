"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Smartphone, Download, X } from "lucide-react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const DISMISS_KEY = "adelia:install-dismissed";

// AdelIA is a PWA (manifest + icons + service worker). On supported browsers
// the beforeinstallprompt event lets us offer a one-tap "install to home
// screen" — handy for a tool parents reach for repeatedly. Inert (renders
// nothing) where unsupported, already installed, or previously dismissed.
export function InstallPrompt() {
  const t = useTranslations("install");
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      if (localStorage.getItem(DISMISS_KEY) === "1") return;
    } catch {
      /* ignore */
    }
    if (window.matchMedia?.("(display-mode: standalone)").matches) return;

    const onPrompt = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      setDismissed(false);
    };
    const onInstalled = () => {
      setDeferred(null);
      setDismissed(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice;
    setDeferred(null);
  }

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
  }

  if (!deferred || dismissed) return null;

  return (
    <div className="ad-card ad-rise mb-6 flex items-center gap-3 p-4">
      <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
        <Smartphone className="h-5 w-5" strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{t("title")}</p>
        <p className="text-sm text-ink-soft">{t("body")}</p>
      </div>
      <button type="button" onClick={install} className="ad-btn ad-btn-primary shrink-0 px-4 py-2 text-sm">
        <Download className="h-4 w-4" strokeWidth={2.2} />
        {t("cta")}
      </button>
      <button
        type="button"
        onClick={dismiss}
        aria-label={t("dismiss")}
        className="ad-btn ad-btn-ghost h-8 w-8 shrink-0 p-0"
      >
        <X className="h-4 w-4" strokeWidth={2} />
      </button>
    </div>
  );
}
