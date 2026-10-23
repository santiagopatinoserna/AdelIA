"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function ConfirmCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  // `body` is the entry exactly as it will be saved (a diary line, AGENT_GRAPH
  // step 4): she confirms what she reads, not a paraphrase of it.
  const p = card.payload as { title: string; body?: string };
  return (
    <div data-testid="confirm-card" className="ad-card ad-rise p-4">
      <p className="mb-3 font-display">{p.title}</p>
      {p.body && <p data-testid="confirm-body" className="-mt-1 mb-3 text-base text-ink">{p.body}</p>}
      <div className="flex gap-2">
        <button className="ad-btn ad-btn-primary min-h-[44px]" onClick={() => onAction("confirm", card)}>{t("confirmYes")}</button>
        <button className="ad-btn ad-btn-ghost min-h-[44px]" onClick={() => onAction("cancel", card)}>{t("confirmNo")}</button>
      </div>
    </div>
  );
}
