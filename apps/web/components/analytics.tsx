"use client";

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { Link } from "@/lib/navigation";
import {
  PRIVATE_PAGES,
  type ConsentState,
  type FunnelStep,
  consentServerSnapshot,
  consentSnapshot,
  flush,
  pageview,
  setConsent,
  subscribeConsent,
  track,
  trackClick,
  trackInteraction,
  trackScroll,
} from "@/lib/analytics";

/** Her answer to the banner, read without an effect (see lib/analytics.ts). */
export function useConsent(): ConsentState | "pending" {
  return useSyncExternalStore(subscribeConsent, consentSnapshot, consentServerSnapshot);
}

// Below the layout's children, beside ServiceWorkerRegister, and not a
// provider: nothing above a Suspense boundary changes when she answers.
//
// The banner is asked on the public pages only (the landing, the legal pages,
// sign-in, billing). Inside her space (/dashboard, /onboarding) she is reading
// about her baby's health with one hand: no sheet over the chat, the record
// button or the first screen of the panel (e2e/showcase.spec.ts measures that
// screen). There, without an answer nothing is measured, and Settings holds
// the same choice.
export function Analytics() {
  const consent = useConsent();
  const pathname = usePathname();
  return (
    <>
      {consent === "accepted" && <JourneyTracker />}
      {consent === "unknown" && !PRIVATE_PAGES.test(pathname) && <ConsentBanner />}
    </>
  );
}

function isTextField(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA") return true;
  if (el.tagName !== "INPUT") return false;
  return !["checkbox", "radio", "file", "button", "submit", "reset", "range", "color"].includes(
    (el as HTMLInputElement).type,
  );
}

// After a text field lets go of the focus, the banner waits this long before
// it comes back. Tapping "Preguntar" while typing blurs the field on the way
// down; a banner back at once would land under the finger and swallow the
// tap that sends her question (it swallowed "Eliminar mi cuenta" in
// e2e/guest-journey.spec.ts before this delay).
const RETURN_AFTER_TYPING_MS = 600;

/**
 * Pages, taps and scroll depth, mounted only while she has accepted. Every
 * listener is passive and only pushes to an in-memory queue.
 */
function JourneyTracker() {
  const pathname = usePathname();
  const scrolled = useRef(new Set<number>());

  useEffect(() => {
    scrolled.current = new Set();
    pageview(pathname);
  }, [pathname]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.target instanceof Element) trackClick(event.target);
    };
    const onFirst = () => trackInteraction();
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const doc = document.documentElement;
        const seen = (window.scrollY + window.innerHeight) / Math.max(doc.scrollHeight, 1);
        for (const band of [25, 50, 75, 100] as const) {
          // 100 is "reached the end", with a few pixels of rounding.
          const reached = band === 100 ? seen >= 0.98 : seen * 100 >= band;
          if (reached && !scrolled.current.has(band) && doc.scrollHeight > window.innerHeight) {
            scrolled.current.add(band);
            trackScroll(band);
          }
        }
      });
    };
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("click", onClick, { capture: true, passive: true });
    document.addEventListener("pointerdown", onFirst, { capture: true, passive: true });
    document.addEventListener("keydown", onFirst, { capture: true, passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("click", onClick, { capture: true });
      document.removeEventListener("pointerdown", onFirst, { capture: true });
      document.removeEventListener("keydown", onFirst, { capture: true });
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", flush);
      if (frame) cancelAnimationFrame(frame);
      flush();
    };
  }, []);

  return null;
}

/**
 * First layer of the AEPD cookie guide: who measures, what for, that nothing
 * goes to third parties, a link to the second layer, and "Rechazar" and
 * "Aceptar" with the same size, colour and weight. Nothing is measured until
 * one is pressed, and continuing to browse is not an answer.
 *
 * A small sheet at the bottom: two lines and two thumb-sized buttons, under
 * the landing's question box and record button, never over them (e2e/
 * analytics-consent.spec.ts). While it is open it publishes its height as
 * --ad-consent-h on <html>: the page gains that room at the bottom and the
 * "new version" toast rises above it (globals.css).
 */
function ConsentBanner() {
  const t = useTranslations("consent");
  const ref = useRef<HTMLDivElement>(null);
  const [typing, setTyping] = useState(false);

  // Typing: the keyboard and the field are hers, the banner steps aside.
  // State changes only in these event handlers, never on mount.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onFocusIn = (event: FocusEvent) => {
      if (!isTextField(event.target as Element)) return;
      clearTimeout(timer);
      setTyping(true);
    };
    const onFocusOut = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!isTextField(document.activeElement)) setTyping(false);
      }, RETURN_AFTER_TYPING_MS);
    };
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = document.documentElement;
    const publish = () => root.style.setProperty("--ad-consent-h", `${el.offsetHeight}px`);
    publish();
    root.classList.add("ad-consent-open");
    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => {
      observer.disconnect();
      root.classList.remove("ad-consent-open");
      root.style.removeProperty("--ad-consent-h");
    };
  }, []);

  return (
    <div
      ref={ref}
      role="region"
      aria-label={t("bannerLabel")}
      data-testid="consent-banner"
      data-track-private
      hidden={typing}
      className="ad-consent"
    >
      <p className="text-[0.9375rem] leading-snug text-ink">
        {t("bannerText")}{" "}
        <Link href="/privacidad#cookies" className="ad-tap-inline font-medium underline underline-offset-4">
          <span>{t("bannerMore")}</span>
        </Link>
      </p>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <button
          type="button"
          data-testid="consent-reject"
          onClick={() => setConsent("rejected", "banner")}
          className="ad-btn ad-btn-ghost w-full"
        >
          {t("reject")}
        </button>
        <button
          type="button"
          data-testid="consent-accept"
          onClick={() => setConsent("accepted", "banner")}
          className="ad-btn ad-btn-ghost w-full"
        >
          {t("accept")}
        </button>
      </div>
    </div>
  );
}

/**
 * Change or withdraw the answer at any time: on /privacidad#cookies and in
 * Settings. Withdrawing also deletes what this browser sent (the API deletes
 * the visitor's journeys with the withdrawal).
 */
export function ConsentControl({ source }: { source: "settings" | "privacy" }) {
  const t = useTranslations("consent");
  const consent = useConsent();
  const state =
    consent === "pending" ? null :
    consent === "gpc" ? t("stateGpc") :
    consent === "accepted" ? t("stateAccepted") :
    consent === "rejected" ? t("stateRejected") : t("stateUnknown");
  return (
    <div data-testid="consent-control" data-track-private>
      <p className="text-[15px] leading-relaxed text-ink" aria-live="polite">
        {state ?? " "}
      </p>
      {consent !== "gpc" && consent !== "pending" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {consent !== "accepted" && (
            <button
              type="button"
              data-testid="consent-control-accept"
              onClick={() => setConsent("accepted", source)}
              className="ad-btn ad-btn-ghost"
            >
              {t("accept")}
            </button>
          )}
          {consent !== "rejected" && (
            <button
              type="button"
              data-testid="consent-control-reject"
              onClick={() => setConsent("rejected", source)}
              className="ad-btn ad-btn-ghost"
            >
              {consent === "accepted" ? t("withdraw") : t("reject")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * One funnel step when the page that means it is shown (the landing, the
 * signup screen, a paid checkout). Renders nothing and sets no state; with no
 * consent, track() does nothing.
 */
export function TrackStep({ step }: { step: FunnelStep }) {
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    // After this commit's other effects, so the page view the tracker
    // records for the same page comes first in her timeline.
    queueMicrotask(() => track(step));
  }, [step]);
  return null;
}
