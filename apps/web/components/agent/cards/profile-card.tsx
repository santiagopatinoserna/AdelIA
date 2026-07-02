"use client";
import { useTranslations } from "next-intl";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

export function ProfileCard({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const p = card.payload as { profiles: { id: string; display_name: string }[]; active_id: string | null };
  return (
    <div className="ad-card ad-rise p-4">
      <div className="ad-eyebrow">{t("profileSwitch")}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {p.profiles.map((profile) => (
          <button
            key={profile.id}
            className={`ad-btn min-h-[44px] ${profile.id === p.active_id ? "ad-btn-primary" : "ad-btn-ghost"}`}
            onClick={() => onAction("switch_profile", card, profile.id)}
          >
            {profile.display_name}
          </button>
        ))}
      </div>
    </div>
  );
}
