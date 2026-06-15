"use client";

import { Link, usePathname } from "@/lib/navigation";
import { locales } from "@/lib/i18n";

const LABELS: Record<string, string> = { es: "ES", en: "EN", fr: "FR" };

export function LocaleSwitcher({ current }: { current: string }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Idioma"
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5 text-xs"
    >
      {locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          aria-current={l === current ? "true" : undefined}
          className={
            l === current
              ? "rounded-md bg-pine-600 px-2 py-1 font-semibold text-white"
              : "rounded-md px-2 py-1 font-medium text-ink-soft transition-colors hover:bg-pine-50 hover:text-pine-700"
          }
        >
          {LABELS[l]}
        </Link>
      ))}
    </nav>
  );
}
