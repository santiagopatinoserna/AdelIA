"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, X } from "lucide-react";

import type { AgentCard } from "@/lib/agent-types";
import { Link } from "@/lib/navigation";
import type { CardActionHandler } from "./cards/card-renderer";

// "Hay demasiadas cosas, no sé dónde leer" (a mother, 2026-11-09). The panel
// used to stack a three-row showcase, four chips, a Telegram card in the
// thread and a desktop rail of the same cards under the greeting. Everything
// that is not the conversation now lives here, once, folded behind one line:
//   * the cards the API suggests (agent/suggestions.py): a birth date to fill
//     in, the Telegram diary, documents waiting. Each can be closed for good;
//     the server remembers it per account (services/dismissals), so it does
//     not come back after a reload or on another phone;
//   * the doors that have no tab of their own. Upload, consult, history and
//     settings are tabs of the bottom bar and are not repeated here
//     (UX_PRINCIPLES 18).
// A guest is trying AdelIA with Lucía: she gets the one door that keeps what
// she did ("Guardar mi cuenta") and the visit summary, which works on Lucía's
// record; never the diary bot, an import or a questionnaire about a sample
// child. "Todo al día" is not shown: it repeats the greeting's invitation.
// Plain rows, no icons and no boxes: separation by space and hairlines.
type Door = { href: string; label: string; testId?: string };

export function PanelMore({
  cards,
  isGuest,
  onAction,
  onDismiss,
}: {
  cards: AgentCard[];
  isGuest: boolean;
  onAction: CardActionHandler;
  onDismiss: (card: AgentCard) => void;
}) {
  const t = useTranslations("panel");
  const tg = useTranslations("guestSpace");
  const offers = cards.filter((c) => c.type === "action" || c.type === "question");
  const doors: Door[] = isGuest
    ? [
        { href: "/dashboard/guardar", label: tg("saveLink"), testId: "save-account" },
        { href: "/dashboard/briefings/new", label: t("briefing") },
      ]
    : [
        { href: "/dashboard/briefings/new", label: t("briefing") },
        { href: "/dashboard/questionnaire", label: t("questionnaire") },
        { href: "/dashboard/ingestion", label: t("import") },
      ];
  return (
    <details data-testid="panel-more" className="group/more mt-8 border-t border-line">
      <summary className="flex min-h-[48px] cursor-pointer list-none items-center justify-between gap-3 text-base font-medium text-ink-soft [&::-webkit-details-marker]:hidden">
        {t("more")}
        <ChevronDown className="h-4 w-4 shrink-0 group-open/more:rotate-180" strokeWidth={2} aria-hidden />
      </summary>
      <ul className="divide-y divide-line border-t border-line">
        {offers.map((card) => (
          <li key={card.id} data-testid="panel-suggestion" className="flex items-start gap-2 py-3">
            <div className="min-w-0 flex-1">
              <Offer card={card} onAction={onAction} />
            </div>
            {typeof card.payload.dismiss_key === "string" && (
              <button
                type="button"
                onClick={() => onDismiss(card)}
                aria-label={`${t("dismiss")}: ${offerTitle(card)}`}
                className="-mr-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink-soft hover:text-ink"
              >
                <X className="h-4 w-4" strokeWidth={2} aria-hidden />
              </button>
            )}
          </li>
        ))}
        {doors.map((door) => (
          <li key={door.href}>
            <Link
              href={door.href}
              data-testid={door.testId}
              className="flex min-h-[48px] items-center text-base text-ink underline-offset-4 hover:underline"
            >
              {door.label}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

function offerTitle(card: AgentCard): string {
  const p = card.payload as { title?: string; prompt?: string };
  return p.title ?? p.prompt ?? "";
}

// A suggestion as a plain row: what it is, one sentence, one button.
function Offer({ card, onAction }: { card: AgentCard; onAction: CardActionHandler }) {
  const t = useTranslations("agent");
  const [value, setValue] = useState("");
  if (card.type === "question") {
    const p = card.payload as { prompt: string; input_type: string };
    return (
      <div>
        <label htmlFor={`more-${card.id}`} className="block text-base font-medium text-ink">
          {p.prompt}
        </label>
        <div className="mt-2 flex gap-2">
          <input
            id={`more-${card.id}`}
            type={p.input_type}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="ad-field min-h-[44px] min-w-0 flex-1 px-3"
          />
          <button
            type="button"
            className="ad-btn ad-btn-ghost min-h-[44px] px-4"
            disabled={!value}
            onClick={() => onAction("answer", card, value)}
          >
            {t("save")}
          </button>
        </div>
      </div>
    );
  }
  const p = card.payload as { title: string; body: string };
  return (
    <div>
      <p className="text-base font-medium text-ink">{p.title}</p>
      <p className="mt-0.5 text-sm leading-relaxed text-ink-soft">{p.body}</p>
      {card.actions.map((a) => (
        <button
          key={a.intent}
          type="button"
          className="ad-btn ad-btn-ghost mt-2 min-h-[44px] px-4 text-sm"
          onClick={() => onAction(a.intent, card)}
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}
