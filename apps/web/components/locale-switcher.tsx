"use client";

import { useTransition } from "react";
import { useRouter, usePathname } from "@/lib/navigation";
import { locales } from "@/lib/i18n";
import { useTranslations } from "next-intl";
import { Globe, Loader2 } from "lucide-react";

import { useRecordingGuard } from "@/lib/recording-guard";

const LABELS: Record<string, string> = { es: "ES", en: "EN", fr: "FR" };

// `variant="nav"` (header) is a navigation landmark; `variant="group"`
// (Settings) is a plain group so a page never carries two "Idioma" landmarks.
export function LocaleSwitcher({
  current,
  variant = "nav",
  compact = false,
}: {
  current: string;
  variant?: "nav" | "group";
  compact?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("common");
  const [pending, startTransition] = useTransition();
  const guard = useRecordingGuard();

  // Programmatic switch (instead of a bare <Link>) so we can show a spinner
  // while the localized route loads — on a slow phone the reload used to look
  // like the app had frozen.
  function switchTo(l: string) {
    if (l === current || pending) return;
    // Switching locale re-renders the route: mid-recording it goes through
    // the recorder's "¿Terminar la grabación?" like any other exit.
    if (guard.requestLeave({ kind: "locale", locale: l })) return;
    startTransition(() => {
      router.replace(pathname, { locale: l });
    });
  }

  const Tag = variant === "nav" ? "nav" : "div";
  // A native picker keeps all three languages one tap away without giving
  // language selection more visual weight than the question itself.
  if (compact) {
    return (
      <Tag
        role={variant === "group" ? "group" : undefined}
        aria-label={t("language")}
        aria-busy={pending}
        className="home-language"
      >
        {pending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Globe className="h-4 w-4" aria-hidden="true" />
        )}
        <select
          aria-label={t("language")}
          value={current}
          disabled={pending}
          onChange={(event) => switchTo(event.target.value)}
        >
          {locales.map((l) => (
            <option key={l} value={l} aria-label={`${LABELS[l]}, ${t(`lang_${l}`)}`}>
              {LABELS[l]}
            </option>
          ))}
        </select>
      </Tag>
    );
  }
  return (
    <Tag
      role={variant === "group" ? "group" : undefined}
      aria-label={t("language")}
      aria-busy={pending}
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5 text-xs"
    >
      {pending ? (
        <Loader2 className="ml-1 mr-0.5 h-4 w-4 shrink-0 animate-spin text-primary-text" strokeWidth={2} aria-hidden="true" />
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
          /* The accessible name starts with the visible "EN" so speech users
             can say what they see (WCAG 2.5.3, axe label-content-name-mismatch),
             then the full language name. */
          aria-label={`${LABELS[l]}, ${t(`lang_${l}`)}`}
          title={t(`lang_${l}`)}
          className={
            l === current
              ? "inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md bg-primary px-3 py-2 font-semibold text-on-primary"
              : "inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md px-3 py-2 font-medium text-ink-soft transition-colors hover:bg-primary-tint hover:text-primary-text-hover disabled:opacity-60"
          }
        >
          {LABELS[l]}
        </button>
      ))}
    </Tag>
  );
}
