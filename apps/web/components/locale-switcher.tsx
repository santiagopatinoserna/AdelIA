"use client";

import { Link, usePathname } from "@/lib/navigation";
import { locales } from "@/lib/i18n";

const LABELS: Record<string, string> = { es: "ES", en: "EN", fr: "FR" };

export function LocaleSwitcher({ current }: { current: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Idioma" className="flex gap-1 text-xs">
      {locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          className={
            l === current
              ? "rounded bg-slate-900 px-2 py-1 font-semibold text-white"
              : "rounded px-2 py-1 text-slate-500 hover:bg-slate-100"
          }
        >
          {LABELS[l]}
        </Link>
      ))}
    </nav>
  );
}
