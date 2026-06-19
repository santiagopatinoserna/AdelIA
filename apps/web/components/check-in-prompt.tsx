"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles, X } from "lucide-react";

import { Link } from "@/lib/navigation";

// A proactive "panel that asks you things": when a mom comes back after a
// while, surface one rotating check-in so her baby's record stays current.
// Time-gated + rotating via localStorage so it never nags on every visit.
const KEY = "adelia:checkin:v1";
const INTERVAL_MS = 3 * 24 * 60 * 60 * 1000; // ask again at most every 3 days

// Three high-intent rotations only: each pairs one clear action with its
// destination. More than three reads as a nag and dilutes the ask.
const PROMPTS = [
  { key: "upload", href: "/dashboard/upload" },
  { key: "weight", href: "/dashboard/questionnaire" },
  { key: "doubt", href: "/dashboard/chat" },
] as const;

export function CheckInPrompt() {
  const t = useTranslations("checkin");
  const [idx, setIdx] = useState<number | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      const st = raw ? (JSON.parse(raw) as { last?: number; i?: number }) : { last: 0, i: 0 };
      if (Date.now() - (st.last ?? 0) > INTERVAL_MS) {
        setIdx((st.i ?? 0) % PROMPTS.length);
      }
    } catch {
      /* no storage (private mode) — just don't show it */
    }
  }, []);

  if (idx === null) return null;
  const prompt = PROMPTS[idx];

  function ack() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ last: Date.now(), i: idx! + 1 }));
    } catch {
      /* ignore */
    }
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
