"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

const FLAG_CLASS: Record<string, string> = {
  low: "text-error-text", high: "text-error-text", normal: "text-primary-text",
};

export function LabCard({ card }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { name: string; value: string; unit: string; flag: string; range: string; interpretation: string };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">{t("cardLabTitle")}</div>
      <div className="flex items-baseline justify-between">
        <span className="font-display text-lg">{p.name}</span>
        <span className={`font-mono text-lg ${FLAG_CLASS[p.flag] ?? ""}`}>{p.value} {p.unit}</span>
      </div>
      <p className="text-ink-soft text-sm">{p.interpretation} · {t("cardLabRange").toLowerCase()} {p.range}</p>
    </div>
  );
}
