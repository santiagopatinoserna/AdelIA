"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

const TONE_CLASS: Record<string, string> = {
  positive: "text-pine-600", warn: "text-clay-600",
};

export function InsightCard({ card }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { title: string; body: string; tone: string };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">{t("cardInsightTitle")}</div>
      <p className={`font-display text-lg ${TONE_CLASS[p.tone] ?? ""}`}>{p.title}</p>
      <p className="text-ink-soft text-sm">{p.body}</p>
    </div>
  );
}
