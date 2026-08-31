"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function QuestionCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { field: string; prompt: string; input_type: string };
  const [value, setValue] = useState("");
  return (
    <div className="ad-card ad-rise p-4">
      {/* font-sans: this card is on the panel home for any child profile
          without a birth date, where the greeting is the ONE serif headline. */}
      <label className="mb-2 block font-sans font-semibold text-ink" htmlFor={`q-${card.id}`}>
        {p.prompt}
      </label>
      <div className="flex gap-2">
        <input id={`q-${card.id}`} type={p.input_type} value={value}
               onChange={(e) => setValue(e.target.value)}
               className="ad-field min-h-[44px] flex-1 px-3" />
        <button className="ad-btn ad-btn-primary min-h-[44px]" disabled={!value}
                onClick={() => onAction("answer", card, value)}>{t("save")}</button>
      </div>
    </div>
  );
}
