"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function ConfirmCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { title: string };
  return (
    <div className="ad-card ad-rise p-4">
      <p className="mb-3 font-display">{p.title}</p>
      <div className="flex gap-2">
        <button className="ad-btn ad-btn-primary min-h-[44px]" onClick={() => onAction("confirm", card)}>{t("confirmYes")}</button>
        <button className="ad-btn ad-btn-ghost min-h-[44px]" onClick={() => onAction("cancel", card)}>{t("confirmNo")}</button>
      </div>
    </div>
  );
}
