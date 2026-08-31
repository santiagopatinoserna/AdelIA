"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

const TONE_CLASS: Record<string, string> = {
  positive: "text-primary-text", warn: "text-error-text",
};

export function InsightCard({ card }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { title: string; body: string; tone: string };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">{t("cardInsightTitle")}</div>
      {/* font-sans: same screen, same rule as action-card. This is the card
          the panel home shows when there is nothing to suggest. */}
      <p className={`font-sans text-lg font-semibold ${TONE_CLASS[p.tone] ?? "text-ink"}`}>
        {p.title}
      </p>
      <p className="text-ink-soft text-sm">{p.body}</p>
    </div>
  );
}
