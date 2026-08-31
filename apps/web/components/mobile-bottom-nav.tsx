"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { MessagesSquare, Stethoscope, UploadCloud, FolderOpen, Settings } from "lucide-react";

import { Link, usePathname } from "@/lib/navigation";
import { useRecordingGuard } from "@/lib/recording-guard";

// A text field with focus is where the on-screen keyboard shows up. With
// `interactive-widget=resizes-content` the viewport shrinks to the keyboard's
// top edge, so a fixed bottom bar would sit right over the field.
function isTextField(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA") return true;
  if (el.tagName !== "INPUT") return false;
  return !["checkbox", "radio", "file", "button", "submit", "reset", "range", "color"].includes(
    (el as HTMLInputElement).type,
  );
}

// Mobile-only bottom tab bar. The horizontal section nav in the header is
// desktop-only (on a 390px viewport it gets squeezed to zero width between
// the logo and the right-side controls), which left phones with no way to
// reach any section. Thumb-reachable tabs are the fix, not a hamburger: the
// primary device for this product is a phone held one-handed.
export function MobileBottomNav() {
  const pathname = usePathname();
  const t = useTranslations("dashboard");
  const { active: recording } = useRecordingGuard();
  const [keyboard, setKeyboard] = useState(false);

  // Keyboard = a text field has focus AND the visual viewport actually
  // shrank. Focus alone is not it: a physical/Bluetooth keyboard never
  // shrinks the viewport, and Android's Back key closes the keyboard while
  // the field keeps focus (no focusout), which left the bar hidden and the
  // shell's bottom padding gone until a tap outside. `full` is the tallest
  // height seen with no field focused; a rotation or pinch-zoom (new width)
  // starts a new baseline. Without visualViewport: the focus heuristic.
  useEffect(() => {
    const vv = window.visualViewport;
    const size = () => ({ w: vv?.width ?? window.innerWidth, h: vv?.height ?? window.innerHeight });
    let { w: width, h: full } = size();
    const update = () => {
      const { w, h } = size();
      if (w !== width) {
        width = w;
        full = h;
      }
      const focused = isTextField(document.activeElement);
      if (!focused) full = Math.max(full, h);
      // 120px: a browser toolbar collapsing on scroll moves the viewport by
      // 50-100px; the smallest on-screen keyboard is well over 200px.
      setKeyboard(focused && (vv ? full - h > 120 : true));
    };
    // focusout fires with activeElement already on <body>; the next frame
    // shows whether focus moved to another field (no flicker) or left.
    const onFocusOut = () => requestAnimationFrame(update);
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", onFocusOut);
    vv?.addEventListener("resize", update);
    window.addEventListener("resize", update);
    update();
    return () => {
      document.removeEventListener("focusin", update);
      document.removeEventListener("focusout", onFocusOut);
      vv?.removeEventListener("resize", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  // html.kb-open: the layout's bottom padding and the chat canvases drop the
  // space reserved for this bar (globals.css) while it is hidden.
  useEffect(() => {
    document.documentElement.classList.toggle("kb-open", keyboard);
    return () => document.documentElement.classList.remove("kb-open");
  }, [keyboard]);

  const items = [
    { href: "/dashboard", icon: MessagesSquare, label: t("navHome"), exact: true },
    { href: "/dashboard/consulta", icon: Stethoscope, label: t("navConsulta") },
    { href: "/dashboard/upload", icon: UploadCloud, label: t("navUploadShort") },
    { href: "/dashboard/overview", icon: FolderOpen, label: t("navHistory") },
    { href: "/dashboard/settings", icon: Settings, label: t("navSettings") },
  ];

  return (
    <nav
      aria-label={t("navHome")}
      data-nav-lock
      data-locked={recording ? "" : undefined}
      hidden={keyboard}
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface-3/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
    >
      <div className="flex h-14 items-stretch justify-around">
        {items.map((it) => {
          const active = it.exact ? pathname === it.href : pathname.startsWith(it.href);
          return (
            <Link
              key={it.href}
              href={it.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 ${
                active ? "text-primary-text" : "text-ink-faint"
              }`}
            >
              <it.icon className="h-5 w-5" strokeWidth={active ? 2.2 : 2} />
              <span className="truncate text-[10px] font-medium leading-none">{it.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
