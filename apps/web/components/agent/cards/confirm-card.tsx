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
    // The question is small and the entry is what she reads: it is exactly
    // what will be saved. "Sí" takes two thirds of the row, under the thumb.
    <div data-testid="confirm-card" className="ad-card ad-rise p-4">
      <p className="text-sm text-ink-soft">{p.title}</p>
      {p.body && <p data-testid="confirm-body" className="mt-1 text-lead font-medium text-ink">{p.body}</p>}
      <div className="mt-4 grid grid-cols-[2fr_1fr] gap-2">
        <button className="ad-btn ad-btn-primary ad-btn-lg" onClick={() => onAction("confirm", card)}>{t("confirmYes")}</button>
        <button className="ad-btn ad-btn-ghost ad-btn-lg" onClick={() => onAction("cancel", card)}>{t("confirmNo")}</button>
      </div>
    </div>
  );
}
