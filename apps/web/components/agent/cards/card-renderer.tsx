"use client";
import type { AgentCard } from "@/lib/agent-types";
import { LabCard } from "./lab-card";
import { ConfirmCard } from "./confirm-card";
import { QuestionCard } from "./question-card";
import { ActionCard } from "./action-card";
import { InsightCard } from "./insight-card";
import { BriefingCard } from "./briefing-card";
import { DocumentCard } from "./document-card";
import { ProfileCard } from "./profile-card";
import { ClarifyCard } from "./clarify-card";

export type CardActionHandler = (intent: string, card: AgentCard, value?: string) => void;

export function CardRenderer({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const common = { card, onAction } as const;
  switch (card.type) {
    case "lab": return <LabCard {...common} />;
    case "confirm": return <ConfirmCard {...common} />;
    case "question": return <QuestionCard {...common} />;
    case "action": return <ActionCard {...common} />;
    case "insight": return <InsightCard {...common} />;
    case "briefing": return <BriefingCard {...common} />;
    case "document": return <DocumentCard {...common} />;
    case "profile": return <ProfileCard {...common} />;
    case "clarify": return <ClarifyCard {...common} />;
    default: return null;
  }
}
