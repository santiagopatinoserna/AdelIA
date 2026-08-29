"use client";

import { useEffect, useState } from "react";

// Install state shared by every surface that offers "install the app":
// the card on /dashboard/overview and the permanent entry in Settings.
//
// Chrome fires `beforeinstallprompt` ONCE, early, on whichever page the user
// landed on. A component mounted later (Settings, reached by navigation)
// would never see it, so the event is captured here at module level and
// exposed through a tiny store; ServiceWorkerRegister (in the locale layout,
// present on every page) arms the capture as soon as the app hydrates.

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export type InstallState = {
  // false until the first client effect ran (SSR + first paint render nothing)
  ready: boolean;
  // Chrome/Edge/Samsung Internet: a native prompt is available
  canPrompt: boolean;
  // running as an installed app (display-mode standalone / iOS navigator.standalone)
  installed: boolean;
  // iPhone / iPad: no prompt API, only the Share -> Add to Home Screen path
  ios: boolean;
};

let deferred: BeforeInstallPromptEvent | null = null;
let installedThisSession = false;
let capturing = false;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function captureInstallPrompt() {
  if (capturing || typeof window === "undefined") return;
  capturing = true;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    emit();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    installedThisSession = true;
    emit();
  });
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
  return (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) return true;
  // iPadOS 13+ reports itself as a Mac; the touch points give it away.
  return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
}

export async function promptInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const ev = deferred;
  if (!ev) return "unavailable";
  await ev.prompt();
  const { outcome } = await ev.userChoice;
  deferred = null;
  emit();
  return outcome;
}

function snapshot(): InstallState {
  return {
    ready: true,
    canPrompt: deferred !== null,
    installed: installedThisSession || isStandalone(),
    ios: isIos(),
  };
}

export function useInstallState(): InstallState {
  const [state, setState] = useState<InstallState>({
    ready: false,
    canPrompt: false,
    installed: false,
    ios: false,
  });
  useEffect(() => {
    const read = () => setState(snapshot());
    read();
    listeners.add(read);
    return () => {
      listeners.delete(read);
    };
  }, []);
  return state;
}
