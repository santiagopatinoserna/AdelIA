"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

// Navigation lock for the consult recorder. While a recording runs (or its
// audio is still uploading) every way out of the page is intercepted and
// handed to the recorder as a "leave request": tab bar and header links,
// the language switch, the command palette, the browser Back button, and
// tab close / reload through `beforeunload`. The recorder then asks
// "¿Terminar la grabación?" instead of the audio being dropped by an
// accidental tap. A phone held one-handed in a clinic taps things.

export type LeaveRequest =
  | { kind: "link"; href: string }
  | { kind: "back" }
  | { kind: "locale"; locale: string };

type Guard = {
  active: boolean;
  setActive: (active: boolean) => void;
  pending: LeaveRequest | null;
  // Returns true when the request was intercepted (the guard is active), so
  // the caller must NOT navigate; false means "go ahead".
  requestLeave: (req: LeaveRequest) => boolean;
  clearPending: () => void;
};

const noop = () => {};
const inactive: Guard = {
  active: false,
  setActive: noop,
  pending: null,
  requestLeave: () => false,
  clearPending: noop,
};

const GuardContext = createContext<Guard>(inactive);

export function useRecordingGuard(): Guard {
  return useContext(GuardContext);
}

export function RecordingGuardProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState(false);
  const [pending, setPending] = useState<LeaveRequest | null>(null);
  const activeRef = useRef(false);
  activeRef.current = active;
  // Back-button sentinel: an extra history entry for the recorder URL so
  // the first Back press pops it (and asks) instead of leaving the page.
  const sentinelRef = useRef<string | null>(null);

  const requestLeave = useCallback((req: LeaveRequest) => {
    if (!activeRef.current) return false;
    setPending(req);
    return true;
  }, []);
  const clearPending = useCallback(() => setPending(null), []);

  useEffect(() => {
    if (!active) {
      setPending(null);
      return;
    }
    const root = document.documentElement;
    root.setAttribute("data-recording", "");

    // Every same-origin anchor in the document (header, tab bar, section nav,
    // cards): capture phase, before React's own handler, so next/link never
    // starts the client transition. Modified clicks, downloads and new-tab
    // links are the user's business; a link to this very page is a no-op.
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const target = e.target as Element | null;
      const anchor = target?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      let url: URL;
      try {
        url = new URL(anchor.href, location.href);
      } catch {
        return;
      }
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setPending({ kind: "link", href: url.pathname + url.search });
    };
    document.addEventListener("click", onClick, true);

    // Tab close, reload, typed URL: the browser's own "leave site?" prompt.
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);

    // Back button. Next's app router restores the same URL/tree from the
    // duplicated state without remounting; only armed when the current
    // entry is one the app router owns (`__NA`), otherwise Back stays native.
    const state = window.history.state as { __NA?: boolean } | null;
    const onPopState = () => {
      if (!activeRef.current || !sentinelRef.current) return;
      window.history.pushState(window.history.state, "", sentinelRef.current);
      setPending({ kind: "back" });
    };
    if (state?.__NA) {
      sentinelRef.current = location.href;
      window.history.pushState(state, "", location.href);
      window.addEventListener("popstate", onPopState);
    }

    return () => {
      root.removeAttribute("data-recording");
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPopState);
      // Drop the sentinel only when still on the recorder page: after a
      // navigation we could not intercept the top entry is the new page.
      if (sentinelRef.current && sentinelRef.current === location.href) {
        window.history.back();
      }
      sentinelRef.current = null;
    };
  }, [active]);

  return (
    <GuardContext.Provider value={{ active, setActive, pending, requestLeave, clearPending }}>
      {children}
    </GuardContext.Provider>
  );
}
