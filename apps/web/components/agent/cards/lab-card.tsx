"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

const FLAG_CLASS: Record<string, string> = {
  low: "text-clay-600", high: "text-clay-600", normal: "text-pine-600",
};

export function LabCard({ card }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { name: string; value: string; unit: string; flag: string; range: string; interpretation: string };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">Laboratorio</div>
      <div className="flex items-baseline justify-between">
        <span className="font-display text-lg">{p.name}</span>
        <span className={`font-mono text-lg ${FLAG_CLASS[p.flag] ?? ""}`}>{p.value} {p.unit}</span>
      </div>
      <p className="text-ink-soft text-sm">{p.interpretation} · rango {p.range}</p>
    </div>
  );
}
