"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function ActionCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { title: string; body: string };
  return (
    <div className="ad-card ad-rise p-4">
      {/* font-sans, not the display serif: this card is on the panel home for
          every account that has not linked Telegram yet, and the greeting is
          the ONE Fraunces headline of that screen (spec 7.1). */}
      <p className="font-sans text-lg font-semibold text-ink">{p.title}</p>
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
