"use client";

import { Link, usePathname } from "@/lib/navigation";
import { locales } from "@/lib/i18n";
import { useTranslations } from "next-intl";
import { Globe } from "lucide-react";

const LABELS: Record<string, string> = { es: "ES", en: "EN", fr: "FR" };

export function LocaleSwitcher({ current }: { current: string }) {
  const pathname = usePathname();
  const t = useTranslations("common");
  return (
    <nav
      aria-label={t("language")}
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5 text-xs"
    >
      <Globe className="ml-1 mr-0.5 h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} aria-hidden="true" />
      {locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          aria-current={l === current ? "true" : undefined}
          aria-label={t(`lang_${l}`)}
          title={t(`lang_${l}`)}
          className={
            l === current
              ? "inline-flex min-h-[40px] items-center rounded-md bg-pine-600 px-3 py-2 font-semibold text-white"
              : "inline-flex min-h-[40px] items-center rounded-md px-3 py-2 font-medium text-ink-soft transition-colors hover:bg-pine-50 hover:text-pine-700"
          }
        >
          {LABELS[l]}
        </Link>
      ))}
    </nav>
  );
}
