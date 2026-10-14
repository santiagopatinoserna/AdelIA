"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * The landing's "Ver más": on a phone, everything that is not the pitch, the
 * proof or the way in is folded behind one button. From `md` up it renders as
 * nothing, so the desktop page is the long page it always was.
 *
 * Measured 2026-10-14 at 390 px on this branch: 11,936 CSS px of scroll, about
 * 14 screens, for a mother who often has the phone in one hand and a baby in
 * the other. (The 24,098 px read against production that day is almost exactly
 * twice that, which points at a device-pixel reading; production was not
 * re-measured from here.) The folded sections are not removed: a closed panel
 * is `display: none` below `md`, the same text is in the HTML, and one tap
 * opens all of it.
 *
 * Why a client component and not <details>: `details` cannot be forced open
 * from `md` up with CSS alone on every engine the app supports, and the
 * desktop page must never show a "Ver más". The button is the same node in
 * both states (the WAI-ARIA disclosure pattern): `aria-expanded` flips and the
 * label changes, focus stays where it was.
 *
 * Why the hash effect: /es#pricing and /es#how are links the product (and the
 * wild) may carry. A closed panel is `display: none`, so the browser has nothing
 * to scroll to and the link would land on the top of the page. When the hash
 * names an element inside the panel, the panel opens and the element is
 * scrolled into view once it exists.
 */
export function LandingFold({
  children,
  hint,
  moreLabel,
  lessLabel,
}: {
  children: ReactNode;
  /** One line saying what is behind the button, so "Ver más" is not a leap of faith. */
  hint: string;
  moreLabel: string;
  lessLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<HTMLElement | null>(null);

  useEffect(() => {
    function revealHashTarget() {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (!id) return;
      const target = document.getElementById(id);
      if (!target || !panel.current?.contains(target)) return;
      pendingScroll.current = target;
      setOpen(true);
    }
    revealHashTarget();
    window.addEventListener("hashchange", revealHashTarget);
    return () => window.removeEventListener("hashchange", revealHashTarget);
  }, []);

  // Runs after the panel is displayed: scrolling a `display: none` element is a
  // no-op, which is exactly what the browser did on the first paint.
  useEffect(() => {
    if (open && pendingScroll.current) {
      pendingScroll.current.scrollIntoView();
      pendingScroll.current = null;
    }
  }, [open]);

  return (
    <>
      <div className="mt-12 flex flex-col items-center gap-3 text-center md:hidden">
        <p className="text-sm leading-snug text-ink-soft">{hint}</p>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
          className="ad-btn ad-btn-ghost w-full px-5 py-3 text-base"
          data-testid="landing-fold-toggle"
        >
          {open ? lessLabel : moreLabel}
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
            strokeWidth={2.4}
          />
        </button>
      </div>
      <div id={panelId} ref={panel} className={open ? undefined : "max-md:hidden"}>
        {children}
      </div>
    </>
  );
}
