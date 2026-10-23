"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

type Option = { value: string; label: string };

// One question, the values as buttons and a way out that still answers
// (AGENT_GRAPH step 3). Buttons are at least 44 px: she is holding a baby
// with the other hand. Labels come from the API, in her language.
export function ClarifyCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { question: string; options: Option[]; skip: Option };
  const titleId = `clarify-${card.id}`;
  return (
    <section data-testid="clarify-card" aria-labelledby={titleId} className="ad-card ad-rise p-4">
      <h3 id={titleId} className="mb-3 font-sans text-lg font-semibold text-ink">{p.question}</h3>
      <div className="flex flex-col gap-2" role="group" aria-labelledby={titleId}>
        {p.options.map((option) => (
          <button key={option.value} type="button" data-testid="clarify-option"
                  onClick={() => onAction("clarify", card, option.value)}
                  className="ad-btn ad-btn-ghost min-h-11 w-full justify-start text-base">
            {option.label}
          </button>
        ))}
      </div>
      <button type="button" data-testid="clarify-skip"
              onClick={() => onAction("clarify", card, p.skip.value)}
              className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-primary-text underline underline-offset-4">
        {p.skip.label}
      </button>
    </section>
  );
}
