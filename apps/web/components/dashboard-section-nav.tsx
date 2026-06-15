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
// section shows its label; the rest stay compact icons. Desktop only — on
// mobile the dashboard hub is the nav.
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
    <nav aria-label="Secciones" className="hidden items-center gap-0.5 md:flex">
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
                ? "flex items-center gap-1.5 rounded-lg bg-pine-50 px-2.5 py-1.5 text-pine-700 ring-1 ring-pine-100"
                : "rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-pine-50 hover:text-pine-600"
            }
          >
            <it.icon className="h-4 w-4 shrink-0" strokeWidth={2} />
            {active && <span className="text-xs font-medium">{it.label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}
