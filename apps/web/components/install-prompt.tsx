"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Smartphone,
  Download,
  X,
  Share,
  SquarePlus,
  Check,
  MoreVertical,
  MonitorDown,
  CheckCircle2,
} from "lucide-react";

import { promptInstall, useInstallState } from "@/lib/pwa-install";
import { useFocusTrap } from "@/lib/use-focus-trap";

const DISMISS_KEY = "adelia:install-dismissed";

// Three-step "add to home screen" guide. iOS has no install API at all
// (Safari, and since 16.4 also Chrome/Firefox on iOS, only offer the Share
// sheet), and Chrome on Android hides the prompt after a dismissal, so the
// manual path must always be reachable: from the overview card and from the
// permanent entry in Settings.
export function InstallGuide({ ios, onClose }: { ios: boolean; onClose: () => void }) {
  const t = useTranslations("install");
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const steps = ios
    ? [
        { icon: Share, text: t("iosStep1") },
        { icon: SquarePlus, text: t("iosStep2") },
        { icon: Check, text: t("iosStep3") },
      ]
    : [
        { icon: MoreVertical, text: t("otherStep1") },
        { icon: MonitorDown, text: t("otherStep2") },
        { icon: Check, text: t("otherStep3") },
      ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-pine-900/50 p-4 backdrop-blur-sm sm:items-center"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="install-guide-title"
        onClick={(e) => e.stopPropagation()}
        className="ad-card w-full max-w-md p-6 shadow-glow"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 id="install-guide-title" className="flex items-center gap-2 text-lg text-pine-900">
            <Smartphone className="h-4 w-4 shrink-0 text-pine-500" strokeWidth={2} />
            {t("guideTitle")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("guideClose")}
            className="ad-btn ad-btn-ghost h-11 w-11 shrink-0 p-0"
          >
            <X className="h-4 w-4" strokeWidth={2} />
          </button>
        </div>
        <p className="text-sm text-ink-soft">{ios ? t("guideIntroIos") : t("guideIntroOther")}</p>
        <ol className="mt-4 space-y-3">
          {steps.map((s, i) => (
            <li key={i} className="flex items-start gap-3">
              <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-pine-600 font-mono text-xs font-semibold text-[#f3f7f3]">
                {i + 1}
              </span>
              <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center text-pine-600">
                <s.icon className="h-4.5 w-4.5" strokeWidth={2} />
              </span>
              <span className="text-sm leading-relaxed text-ink">{s.text}</span>
            </li>
          ))}
        </ol>
        <button
          type="button"
          onClick={onClose}
          className="ad-btn ad-btn-primary mt-5 min-h-[44px] w-full text-sm"
        >
          {t("guideDone")}
        </button>
      </div>
    </div>
  );
}

// Card for /dashboard/overview. Native prompt where the browser offers one
// (Android Chrome and friends), the manual guide on iOS, nothing when
// already installed, unsupported, or previously dismissed.
export function InstallPrompt() {
  const t = useTranslations("install");
  const state = useInstallState();
  const [dismissed, setDismissed] = useState(true);
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      setDismissed(false);
    }
  }, []);

  async function install() {
    if (state.canPrompt) {
      await promptInstall();
      return;
    }
    setGuideOpen(true);
  }

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
  }

  if (!state.ready || state.installed || dismissed) return null;
  if (!state.canPrompt && !state.ios) return null;

  return (
    <>
      <div className="ad-card ad-rise mb-6 flex items-center gap-3 p-4">
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-pine-50 text-pine-600 ring-1 ring-pine-100">
          <Smartphone className="h-5 w-5" strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{t("title")}</p>
          <p className="text-sm text-ink-soft">{t("body")}</p>
        </div>
        <button
          type="button"
          onClick={install}
          className="ad-btn ad-btn-primary min-h-[44px] shrink-0 px-4 py-2 text-sm"
        >
          <Download className="h-4 w-4" strokeWidth={2.2} />
          {state.canPrompt ? t("cta") : t("howCta")}
        </button>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t("dismiss")}
          className="ad-btn ad-btn-ghost h-11 w-11 shrink-0 p-0"
        >
          <X className="h-4 w-4" strokeWidth={2} />
        </button>
      </div>
      {guideOpen && <InstallGuide ios={state.ios} onClose={() => setGuideOpen(false)} />}
    </>
  );
}

// Permanent entry for Settings: always reachable, whatever the browser did
// with its own prompt. Shows the installed state when running standalone.
export function InstallSettingsEntry() {
  const t = useTranslations("settings");
  const state = useInstallState();
  const [guideOpen, setGuideOpen] = useState(false);
  const [justInstalled, setJustInstalled] = useState(false);

  async function onInstall() {
    if (state.canPrompt) {
      const outcome = await promptInstall();
      if (outcome === "accepted") setJustInstalled(true);
      return;
    }
    setGuideOpen(true);
  }

  const installed = state.installed || justInstalled;

  return (
    <section className="ad-card mt-6 p-4">
      <div className="ad-eyebrow">{t("installTitle")}</div>
      <p className="mt-1.5 text-sm text-ink-soft">{t("installBody")}</p>
      {installed ? (
        <p className="mt-3 inline-flex items-center gap-2 text-sm font-medium text-pine-700">
          <CheckCircle2 className="h-4 w-4" strokeWidth={2.2} />
          {t("installed")}
        </p>
      ) : (
        <button
          type="button"
          onClick={onInstall}
          className="ad-btn ad-btn-ghost mt-3 min-h-[44px] px-3.5 py-2 text-sm"
        >
          <Smartphone className="h-4 w-4" strokeWidth={2} />
          {state.canPrompt ? t("installCta") : t("installGuideCta")}
        </button>
      )}
      {guideOpen && <InstallGuide ios={state.ios} onClose={() => setGuideOpen(false)} />}
    </section>
  );
}
