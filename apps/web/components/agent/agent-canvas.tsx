"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { streamAgent, getSuggestions } from "@/lib/agent-client-browser";
import type { AgentCard } from "@/lib/agent-types";
import { CardRenderer, type CardActionHandler } from "./cards/card-renderer";
import { AgentInput } from "./agent-input";
import { ProfileSwitcher } from "./profile-switcher";
import { useActiveProfile } from "@/lib/profile-context";

type Msg = { role: "user" | "assistant"; content: string };

export function AgentCanvas({ locale }: { locale: string }) {
  const t = useTranslations("agent");
  const { activeId } = useActiveProfile();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [cards, setCards] = useState<AgentCard[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);

  useEffect(() => {
    let alive = true;
    getSuggestions(activeId, locale).then((c) => { if (alive) setCards(c); }).catch(() => {});
    return () => { alive = false; };
  }, [activeId, locale]);

  async function drive(body: { message?: string; card_action?: object }) {
    const epoch = ++epochRef.current;
    const stale = () => epochRef.current !== epoch;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    if (body.message) setMessages((p) => [...p, { role: "user", content: body.message! }, { role: "assistant", content: "" }]);
    try {
      for await (const ev of streamAgent({ ...body, profile_id: activeId, locale }, controller.signal)) {
        if (stale()) break;
        if (ev.type === "token") {
          setMessages((p) => { const n = [...p]; const last = n[n.length - 1];
            if (last?.role === "assistant") n[n.length - 1] = { ...last, content: last.content + ev.content }; return n; });
        } else if (ev.type === "card") {
          setCards((p) => [ev.card, ...p]);
        } else if (ev.type === "error") {
          setMessages((p) => { const n = [...p]; const last = n[n.length - 1];
            if (last?.role === "assistant") n[n.length - 1] = { ...last, content: t("errorAnswer") }; return n; });
        }
      }
    } catch { /* aborted */ } finally { if (!stale()) setBusy(false); }
  }

  const onCardAction: CardActionHandler = (intent, card, value) => {
    if (intent === "cancel") { setCards((p) => p.filter((c) => c.id !== card.id)); return; }
    if (intent === "confirm") {
      const pl = card.payload as { tool_name: string; tool_args: object };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: pl.tool_name, tool_args: pl.tool_args } });
      return;
    }
    if (intent === "answer") {
      const pl = card.payload as { field: string };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: "completar_perfil", tool_args: { field: pl.field, value } } });
      return;
    }
    // action intents (process_docs, open_briefing, ...) → send as a natural-language message
    void drive({ message: `[${intent}]` });
  };

  const cardRail = (
    <div className="flex flex-col gap-3 overflow-y-auto p-3" aria-label={t("suggestionsTitle")}>
      {cards.map((c) => <CardRenderer key={c.id} card={c} onAction={onCardAction} />)}
    </div>
  );

  return (
    <div data-testid="agent-canvas" className="flex h-[calc(100dvh-3.5rem)] flex-col md:flex-row">
      {/* Chat column */}
      <section className="flex min-h-0 flex-1 flex-col">
        <ProfileSwitcher />
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {messages.length === 0 && <p className="ad-rise font-display text-lg text-ink-soft">{t("greeting")}</p>}
          {messages.map((m, i) => (
            <div key={i} className={`my-2 ${m.role === "user" ? "text-right" : ""}`}>
              <span className={`inline-block rounded-lg px-3 py-2 ${m.role === "user" ? "bg-pine-100" : "bg-surface-2"}`}>
                {m.content || (busy && m.role === "assistant" ? t("thinking") : "")}
              </span>
            </div>
          ))}
          {/* Mobile: cards render inline in the thread */}
          <div className="mt-3 flex flex-col gap-3 md:hidden">
            {cards.map((c) => <CardRenderer key={c.id} card={c} onAction={onCardAction} />)}
          </div>
        </div>
        <AgentInput locale={locale} disabled={busy} onStop={() => abortRef.current?.abort()}
                    onSubmit={(text) => void drive({ message: text })} />
      </section>
      {/* Desktop: card rail beside the chat */}
      <aside className="hidden w-80 border-l border-line md:flex md:flex-col">{cardRail}</aside>
    </div>
  );
}
