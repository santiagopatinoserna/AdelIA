"use client";

import { useTransition } from "react";
import { useRouter, usePathname } from "@/lib/navigation";
import { locales } from "@/lib/i18n";
import { useTranslations } from "next-intl";
import { Globe, Loader2 } from "lucide-react";

const LABELS: Record<string, string> = { es: "ES", en: "EN", fr: "FR" };

export function LocaleSwitcher({ current }: { current: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("common");
  const [pending, startTransition] = useTransition();

  // Programmatic switch (instead of a bare <Link>) so we can show a spinner
  // while the localized route loads — on a slow phone the reload used to look
  // like the app had frozen.
  function switchTo(l: string) {
    if (l === current || pending) return;
    startTransition(() => {
      router.replace(pathname, { locale: l });
    });
  }

  return (
    <nav
      aria-label={t("language")}
      aria-busy={pending}
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5 text-xs"
    >
      {pending ? (
        <Loader2 className="ml-1 mr-0.5 h-4 w-4 shrink-0 animate-spin text-pine-500" strokeWidth={2} aria-hidden="true" />
      ) : (
        <Globe className="ml-1 mr-0.5 h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} aria-hidden="true" />
      )}
      {locales.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => switchTo(l)}
          disabled={pending}
          aria-current={l === current ? "true" : undefined}
          aria-label={t(`lang_${l}`)}
          title={t(`lang_${l}`)}
          className={
            l === current
              ? "inline-flex min-h-[40px] items-center rounded-md bg-pine-600 px-3 py-2 font-semibold text-white"
              : "inline-flex min-h-[40px] items-center rounded-md px-3 py-2 font-medium text-ink-soft transition-colors hover:bg-pine-50 hover:text-pine-700 disabled:opacity-60"
          }
        >
          {LABELS[l]}
        </button>
      ))}
    </nav>
  );
}
