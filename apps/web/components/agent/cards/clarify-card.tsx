"use client";
import { useState } from "react";
import type { AgentCard } from "@/lib/agent-types";
import type { ClarifyAnswer, CardActionHandler } from "./card-renderer";

type Option = { value: string; label: string };
type Question = { field: string; question: string; options: Option[]; skip: Option };

// One question, the values as buttons and a way out that still answers
// (AGENT_GRAPH step 3). Buttons are at least 44 px: she is holding a baby
// with the other hand. Labels come from the API, in her language.
//
// Two questions when the API sends `questions` (2026-11-09: a worry about how
// the baby is at the nursery is asked how long and how he is at home before
// any answer). A tap marks the answer; the turn goes when both have one, so
// two taps and nothing else. She may also answer in her words in the field
// below (`free`): the canvas then drops this card.
export function ClarifyCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as {
    question: string; options: Option[]; skip: Option; questions?: Question[]; free?: string;
  };
  if (p.questions && p.questions.length > 1) {
    return <ClarifyRound card={card} questions={p.questions} free={p.free} onAction={onAction} />;
  }
  const titleId = `clarify-${card.id}`;
  return (
    <section data-testid="clarify-card" aria-labelledby={titleId} className="ad-card ad-rise p-4">
      <h2 id={titleId} className="mb-3 font-sans text-lg font-semibold text-ink">{p.question}</h2>
      <div className="flex flex-col gap-2" role="group" aria-labelledby={titleId}>
        {p.options.map((option) => (
          <button key={option.value} type="button" data-testid="clarify-option"
                  onClick={() => onAction("clarify", card, option.value)}
                  className="ad-btn ad-btn-ghost ad-btn-lg w-full justify-start">
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

function ClarifyRound({ card, questions, free, onAction }: {
  card: AgentCard; questions: Question[]; free?: string; onAction: CardActionHandler;
}) {
  // Local to the card and set only by her taps: nothing runs on mount.
  const [chosen, setChosen] = useState<Record<string, string>>({});
  function choose(field: string, value: string) {
    const next = { ...chosen, [field]: value };
    setChosen(next);
    if (questions.every((q) => next[q.field] !== undefined)) {
      const answers: ClarifyAnswer[] = questions.map((q) => ({ field: q.field, value: next[q.field] }));
      onAction("clarify", card, undefined, answers);
    }
  }
  const titleId = `clarify-${card.id}`;
  return (
    <section data-testid="clarify-card" aria-labelledby={`${titleId}-0`} className="ad-card ad-rise p-4">
      {questions.map((q, i) => {
        const qid = `${titleId}-${i}`;
        return (
          <div key={q.field} className={i > 0 ? "mt-5" : undefined}>
            <h2 id={qid} className="mb-2 font-sans text-base font-semibold text-ink">{q.question}</h2>
            <div className="flex flex-col gap-2" role="group" aria-labelledby={qid}>
              {[...q.options, q.skip].map((option) => {
                const pressed = chosen[q.field] === option.value;
                const skip = option === q.skip;
                return (
                  <button key={option.value} type="button" aria-pressed={pressed}
                          data-testid={skip ? "clarify-skip" : "clarify-option"}
                          onClick={() => choose(q.field, option.value)}
                          className={skip
                            ? `inline-flex min-h-11 items-center self-start text-sm font-medium text-primary-text underline underline-offset-4 ${pressed ? "font-semibold" : ""}`
                            : `ad-btn min-h-11 w-full justify-start ${pressed ? "ad-btn-primary" : "ad-btn-ghost"}`}>
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {free && <p className="mt-4 text-sm text-ink-soft">{free}</p>}
    </section>
  );
}
