"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles, X } from "lucide-react";

import { CHECKIN_PROMPTS, checkinCookie } from "@/lib/checkin";
import { Link } from "@/lib/navigation";

// A proactive "panel that asks you things": when a mom comes back after a
// while, surface one rotating check-in so her baby's record stays current.
// The page decides `initialIndex` on the server from the cookie (lib/checkin),
// so the card is already in the HTML: no post-hydration insertion, no layout
// shift. Acknowledging writes the cookie for the next visit.
export function CheckInPrompt({ initialIndex }: { initialIndex: number }) {
  const t = useTranslations("checkin");
  const [idx, setIdx] = useState<number | null>(initialIndex);

  if (idx === null) return null;
  const prompt = CHECKIN_PROMPTS[idx % CHECKIN_PROMPTS.length];

  function ack() {
    document.cookie = checkinCookie(idx! + 1);
    setIdx(null);
  }

  return (
    <div className="ad-card ad-rise mb-6 flex items-center gap-3 border-honey-200 bg-honey-100/40 p-4">
      <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-honey-100 text-honey-600 ring-1 ring-honey-200">
        <Sparkles className="h-4.5 w-4.5" strokeWidth={2} />
      </span>
      <p className="flex-1 text-sm leading-relaxed text-ink">{t(prompt.key)}</p>
      <Link
        href={prompt.href}
        onClick={ack}
        className="ad-btn ad-btn-primary min-h-[44px] shrink-0 px-4 py-2 text-xs"
      >
        {t(`${prompt.key}Cta`)}
      </Link>
      <button
        type="button"
        onClick={ack}
        aria-label={t("dismiss")}
        className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg p-1.5 text-ink-faint transition-colors hover:text-ink"
      >
        <X className="h-4 w-4" strokeWidth={2} />
      </button>
    </div>
  );
}
