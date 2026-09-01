"use client";

import { useEffect, useRef } from "react";

import { Link } from "@/lib/navigation";

/**
 * The two client-side halves of the funnel (audit 4.8).
 *
 * The product had no measurement at all, and the obvious way to add some is
 * the one thing /privacidad promises never to do ("no hay analítica ni
 * publicidad en AdelIA"). So this is not analytics: it POSTs to our own
 * server, which adds 1 to an integer in a table of (date, event, count) and
 * keeps nothing else. Three deliberate properties:
 *
 *   credentials: "omit"  the session cookie is not sent, so the request that
 *                        counts a visit cannot be tied to an account even by
 *                        a server that wanted to;
 *   keepalive: true      the "Empezar" press survives the navigation it
 *                        triggers, without delaying it;
 *   catch(() => {})      a counter is never worth a broken page.
 *
 * No storage of any kind: no cookie, no localStorage "already counted" flag.
 * A reload is a second visit and that is the intended meaning.
 */
async function beacon(event: "visit" | "start"): Promise<void> {
  try {
    await fetch(`/api/funnel/${event}`, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      keepalive: true,
    });
  } catch {
    // Offline, blocked by an extension, navigating away. All fine.
  }
}

/** Counts one view of a public page. Renders nothing. */
export function FunnelVisit() {
  const sent = useRef(false);
  useEffect(() => {
    // React 18 mounts effects twice in dev StrictMode; the ref keeps one
    // page view from being counted as two while developing.
    if (sent.current) return;
    sent.current = true;
    void beacon("visit");
  }, []);
  return null;
}

/**
 * The landing's "Empezar" link, which counts the press on its way out.
 *
 * Same markup and same navigation as the plain <Link> it replaces: the click
 * is not intercepted, preventDefault is never called, and the beacon rides
 * along with keepalive so a slow counter can never delay a mother reaching
 * the product.
 */
export function StartLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={className} onClick={() => void beacon("start")}>
      {children}
    </Link>
  );
}
