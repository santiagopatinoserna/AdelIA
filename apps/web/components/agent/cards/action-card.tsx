"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function ActionCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { title: string; body: string };
  return (
    <div className="ad-card ad-rise p-4">
      <p className="font-display text-lg">{p.title}</p>
      <p className="text-ink-soft text-sm">{p.body}</p>
      <div className="mt-3 flex gap-2">
        {card.actions.map((a) => (
          <button key={a.intent} className="ad-btn ad-btn-primary min-h-[44px]" onClick={() => onAction(a.intent, card)}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
