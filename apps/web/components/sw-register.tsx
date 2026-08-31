"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw, X } from "lucide-react";

import { captureInstallPrompt } from "@/lib/pwa-install";

// Baked in at build time (next.config.ts): Next's BUILD_ID, this constant and
// GET /api/version all carry the same value.
const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";
// A tab asks the server which build is live when it comes back to the
// foreground (at most every 5 min) and every 30 min while visible.
const PROBE_MIN_INTERVAL_MS = 5 * 60 * 1000;
const PROBE_INTERVAL_MS = 30 * 60 * 1000;
// If the waiting worker never takes over (should not happen), reload anyway.
const TAKEOVER_FALLBACK_MS = 4000;

function swUrl(version: string) {
  return `/sw.js?v=${encodeURIComponent(version)}`;
}

function versionOf(worker: ServiceWorker): string | null {
  try {
    return new URL(worker.scriptURL).searchParams.get("v");
  } catch {
    return null;
  }
}

type Pending =
  // a worker for another build is installed and waits for the go-ahead
  | { kind: "worker"; worker: ServiceWorker }
  // no service worker support here, but /api/version reports a newer build
  | { kind: "reload" };

// Registers public/sw.js under the current build id and shows a small
// "new version" notice when a worker for a different build is waiting: the
// user decides when to reload (never in the middle of a recording).
export function ServiceWorkerRegister() {
  const t = useTranslations("appUpdate");
  const [pending, setPending] = useState<Pending | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const userRequested = useRef(false);

  useEffect(() => {
    // Arm the beforeinstallprompt capture on every page (see lib/pwa-install).
    captureInstallPrompt();
    if (process.env.NODE_ENV !== "production") return;

    const swSupported = "serviceWorker" in navigator;
    let watched: ServiceWorkerRegistration | null = null;
    let lastProbe = Date.now();

    // Reload only when the user pressed "Actualizar": the silent activation
    // below must never reload a page on its own.
    const onControllerChange = () => {
      if (!userRequested.current) return;
      userRequested.current = false;
      window.location.reload();
    };

    const onInstalled = (worker: ServiceWorker) => {
      // The page already runs this build (first load right after a deploy,
      // while the previous worker is still active): activate quietly.
      if (versionOf(worker) === BUILD_ID) {
        worker.postMessage({ type: "SKIP_WAITING" });
        return;
      }
      setPending({ kind: "worker", worker });
      setDismissed(false);
    };

    const watch = (reg: ServiceWorkerRegistration) => {
      // register() resolves the same registration for the scope: listen once.
      if (watched === reg) return;
      watched = reg;
      if (reg.waiting && navigator.serviceWorker.controller) onInstalled(reg.waiting);
      reg.addEventListener("updatefound", () => {
        const worker = reg.installing;
        if (!worker) return;
        worker.addEventListener("statechange", () => {
          // "installed" while another worker controls the page = waiting.
          if (worker.state === "installed" && navigator.serviceWorker.controller) {
            onInstalled(worker);
          }
        });
      });
    };

    const register = (version: string) =>
      navigator.serviceWorker
        .register(swUrl(version))
        .then(watch)
        .catch(() => {
          // registration failure is non-fatal: the app works without the SW
        });

    // Long-lived tabs (an installed app stays open for days) never fetch new
    // HTML, so they cannot see a deploy by themselves: ask the server, and
    // when the build changed register its worker, which surfaces the notice.
    const probe = async () => {
      lastProbe = Date.now();
      try {
        const res = await fetch("/api/version", { cache: "no-store" });
        if (!res.ok) return;
        const { buildId } = (await res.json()) as { buildId?: string };
        if (!buildId || buildId === BUILD_ID) return;
        if (swSupported) {
          await register(buildId);
        } else {
          setPending({ kind: "reload" });
          setDismissed(false);
        }
      } catch {
        // offline or transient: the next visibility change tries again
      }
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastProbe >= PROBE_MIN_INTERVAL_MS) void probe();
    };

    if (swSupported) {
      navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
      void register(BUILD_ID);
    }
    document.addEventListener("visibilitychange", onVisibility);
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void probe();
    }, PROBE_INTERVAL_MS);

    return () => {
      if (swSupported) {
        navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
      }
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(interval);
    };
  }, []);

  function update() {
    if (!pending) return;
    if (pending.kind === "reload" || pending.worker.state === "activated") {
      window.location.reload();
      return;
    }
    userRequested.current = true;
    pending.worker.postMessage({ type: "SKIP_WAITING" });
    window.setTimeout(() => {
      if (userRequested.current) window.location.reload();
    }, TAKEOVER_FALLBACK_MS);
  }

  if (!pending || dismissed) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="app-update"
      className="ad-update-toast fixed inset-x-3 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-40 mx-auto flex max-w-md items-center gap-2 rounded-2xl border border-line-strong bg-surface-3 p-2 pl-3.5 shadow-lift md:inset-x-auto md:bottom-6 md:right-6"
    >
      <RefreshCw className="h-4 w-4 shrink-0 text-primary-text" strokeWidth={2} />
      <p className="min-w-0 flex-1 text-sm text-ink">{t("available")}</p>
      <button
        type="button"
        onClick={update}
        className="ad-btn ad-btn-primary min-h-[44px] shrink-0 px-3.5 py-2 text-sm"
      >
        {t("cta")}
      </button>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label={t("later")}
        className="ad-btn ad-btn-ghost ad-btn-icon shrink-0"
      >
        <X className="h-4 w-4" strokeWidth={2} />
      </button>
    </div>
  );
}
