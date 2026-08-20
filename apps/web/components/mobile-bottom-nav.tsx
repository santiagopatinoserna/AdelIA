"use client";

import { useTranslations } from "next-intl";
import { MessagesSquare, Stethoscope, UploadCloud, FolderOpen, Settings } from "lucide-react";

import { Link, usePathname } from "@/lib/navigation";

// Mobile-only bottom tab bar. The horizontal section nav in the header is
// desktop-only (on a 390px viewport it gets squeezed to zero width between
// the logo and the right-side controls), which left phones with no way to
// reach any section. Thumb-reachable tabs are the fix, not a hamburger: the
// primary device for this product is a phone held one-handed.
export function MobileBottomNav() {
  const pathname = usePathname();
  const t = useTranslations("dashboard");

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
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line/70 bg-canvas/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
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
                active ? "text-pine-700" : "text-ink-faint"
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
