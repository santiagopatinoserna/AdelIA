"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function DocumentCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { filename: string; status: string; entities: number };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">Documento</div>
      <p className="font-display text-lg">{p.filename}</p>
      <p className="text-ink-soft text-sm">{p.status} · {p.entities} datos extraídos</p>
      <div className="mt-3 flex gap-2">
        {card.actions.map((a) => (
          <button key={a.intent} className="ad-btn ad-btn-ghost min-h-[44px]" onClick={() => onAction(a.intent, card)}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
