"use client";

import { Link, usePathname } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import {
  MessagesSquare,
  ClipboardList,
  Baby,
  Stethoscope,
  Download,
  Sparkles,
} from "lucide-react";

// Persistent cross-section nav in the top bar: jump between sections from any
// page (before, you had to go back to the dashboard hub first). The active
// section shows its label; the rest stay compact icons. Desktop only: on
// mobile this bar has no room (it was getting squeezed to zero width), so
// phones navigate with MobileBottomNav instead.
export function DashboardSectionNav() {
  const pathname = usePathname();
  const t = useTranslations();
  const items = [
    { href: "/dashboard/chat", icon: MessagesSquare, label: "Chat" },
    { href: "/dashboard/briefings", icon: ClipboardList, label: "Briefings" },
    { href: "/dashboard/questionnaire", icon: Baby, label: t("questionnaire.navLabel") },
    { href: "/dashboard/consulta", icon: Stethoscope, label: t("consulta.navLabel") },
    { href: "/dashboard/ingestion", icon: Download, label: t("dashboard.navImport") },
    { href: "/dashboard/enrichment", icon: Sparkles, label: t("dashboard.navInsights") },
  ];

  return (
    <nav
      aria-label="Secciones"
      className="-mx-1 hidden items-center gap-0.5 overflow-x-auto px-1 [scrollbar-width:none] md:flex [&::-webkit-scrollbar]:hidden"
    >
      {items.map((it) => {
        const active = pathname.startsWith(it.href);
        return (
          <Link
            key={it.href}
            href={it.href}
            aria-label={it.label}
            aria-current={active ? "page" : undefined}
            title={it.label}
            className={
              active
                ? "flex shrink-0 items-center gap-1.5 rounded-lg bg-pine-50 px-2.5 py-1.5 text-pine-700 ring-1 ring-pine-100"
                : "flex shrink-0 items-center gap-1.5 rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-pine-50 hover:text-pine-600 lg:px-2.5 lg:py-1.5"
            }
          >
            <it.icon className="h-4 w-4 shrink-0" strokeWidth={2} />
            {/* Labels for everyone at lg+ — seven bare icons were a guessing
                game; below lg the active one keeps its label as before. */}
            <span className={`text-xs font-medium ${active ? "" : "hidden lg:inline"}`}>
              {it.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
