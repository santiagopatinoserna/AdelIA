"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { streamAgent, getSuggestions } from "@/lib/agent-client-browser";
import type { AgentCard } from "@/lib/agent-types";
import { CardRenderer, type CardActionHandler } from "./cards/card-renderer";
import { AgentInput } from "./agent-input";
import { ProfileSwitcher } from "./profile-switcher";
import { CapabilityShowcase } from "@/components/capability-showcase";
import { GrowthMark, useGrowthMarkLabel } from "./growth-mark";
import { useActiveProfile } from "@/lib/profile-context";
import { useRouter } from "@/lib/navigation";

type Msg = { role: "user" | "assistant"; content: string };

// Must track routers/agent.py (HISTORY_MAX_MESSAGES / HISTORY_MAX_CHARS_PER_MESSAGE).
// The transcript was sent whole, growing by two entries per turn, so it used
// to cross the API's cap on the 13th exchange and every later request failed.
// The router trims now instead of refusing, but sending 12 turns rather than
// the whole session also stops paying for bandwidth nobody reads: the model
// never sees more than this either way.
const HISTORY_MAX_MESSAGES = 12;
const HISTORY_MAX_CHARS_PER_MESSAGE = 2000;

// Telegram-first daily diary: the bot lives outside the app on purpose.
const TELEGRAM_BOT_URL = `https://t.me/${process.env.NEXT_PUBLIC_TELEGRAM_BOT ?? "Adelia_godiai_bot"}`;

export function AgentCanvas({ locale, userId }: { locale: string; userId: string }) {
  const t = useTranslations("agent");
  const router = useRouter();
  const { activeId } = useActiveProfile();
  const growthMark = useGrowthMarkLabel();
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
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    const history = body.message
      ? messages
          .filter((m) => !(m.role === "assistant" && m.content === ""))
          .slice(-HISTORY_MAX_MESSAGES)
          .map((m) => ({
            role: m.role,
            content: m.content.slice(0, HISTORY_MAX_CHARS_PER_MESSAGE),
          }))
      : undefined;
    if (body.message) setMessages((p) => [...p, { role: "user", content: body.message! }, { role: "assistant", content: "" }]);
    try {
      for await (const ev of streamAgent(
        { ...body, profile_id: activeId, locale, ...(history ? { history } : {}) },
        controller.signal,
      )) {
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
    } catch (err) {
      // Only a real abort is silent. Swallowing everything is what turned the
      // API's 422 into an empty assistant bubble with no error, no toast and
      // no way to tell the session had died; same shape chat-page-client.tsx
      // already uses.
      const aborted =
        controller.signal.aborted ||
        (err instanceof DOMException && err.name === "AbortError");
      if (!stale() && !aborted) {
        setMessages((p) => { const n = [...p]; const last = n[n.length - 1];
          if (last?.role === "assistant" && !last.content) n[n.length - 1] = { ...last, content: t("errorAnswer") }; return n; });
      }
    } finally { if (!stale()) setBusy(false); }
  }

  const onCardAction: CardActionHandler = (intent, card, value) => {
    if (intent === "cancel") { setCards((p) => p.filter((c) => c.id !== card.id)); return; }
    if (intent === "confirm") {
      const pl = card.payload as { tool_name: string; tool_args: object };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: pl.tool_name, tool_args: pl.tool_args } });
      getSuggestions(activeId, locale).then(setCards).catch(() => {});
      return;
    }
    if (intent === "answer") {
      const pl = card.payload as { field: string };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: "completar_perfil", tool_args: { field: pl.field, value } } });
      getSuggestions(activeId, locale).then(setCards).catch(() => {});
      return;
    }
    // navigation intents from action cards — no dead LLM messages
    if (intent === "open_briefing" || intent === "share_briefing") {
      const pl = card.payload as { briefing_id?: string };
      router.push(`/dashboard/briefings/${pl.briefing_id ?? ""}`);
      return;
    }
    if (intent === "process_docs") { router.push("/dashboard/overview"); return; }
    if (intent === "daily_diary") { window.open(TELEGRAM_BOT_URL, "_blank", "noopener"); return; }
    if (intent === "link_telegram") { router.push("/dashboard/ingestion/telegram"); return; }
    if (intent === "regen_briefing") { router.push("/dashboard/briefings"); return; }
    // unknown intent: no-op (avoid sending dead "[intent]" messages to the LLM)
  };

  const cardRail = (
    <div className="flex flex-col gap-3 overflow-y-auto p-3">
      {cards.map((c) => <CardRenderer key={c.id} card={c} onAction={onCardAction} />)}
    </div>
  );

  return (
    <div
      data-testid="agent-canvas"
      className="ad-agent-canvas flex h-[calc(100dvh-7rem)] flex-col md:h-[calc(100dvh-3.5rem)] md:flex-row"
    >
      {/* Chat column — the page's main landmark */}
      <main className="flex min-h-0 flex-1 flex-col">
        <ProfileSwitcher />
        {/* Empty state on md+: the greeting, the mark and the showcase are
            the only children, so `justify-content` centres the block instead
            of leaving 44 % of the column blank under it with nothing to
            scroll. `safe center` and not `center`: once the content DOES
            overflow (a short viewport), plain centring pushes the top of the
            block out of reach, while `safe` falls back to flex-start.
            The phone keeps the top alignment it already had. */}
        <div
          className={`min-h-0 flex-1 overflow-y-auto p-3 ${
            messages.length === 0
              ? "md:flex md:flex-col md:[justify-content:safe_center]"
              : ""
          }`}
        >
          {/* The one headline of this screen. Everything below it (the
              showcase section title included) is mono, small caps and amber:
              two serif headlines competing was the reason nothing led. */}
          {messages.length === 0 && (
            <h1 className="ad-rise font-display text-[1.375rem] leading-[1.25] text-ink">{t("greeting")}</h1>
          )}
          {/* The height mark: the only warm signal of the panel, a real name
              and a real age, so it cannot read as stock. It is a mark beside
              the label, NOT a section rule (the full-width hairline it used to
              draw doubled the header's own rule and separated the greeting
              from the content it introduces). Nothing to render when the
              profile has no date of birth. */}
          {messages.length === 0 && growthMark && <GrowthMark label={growthMark} />}
          {/* Capability showcase: an empty canvas tells a new mom nothing.
              Seven concrete doors into the product with three visual weights
              (three first-day rows, four second-week chips; "Ajustes" stays a
              tab of the bottom bar instead of being repeated here), shown on
              every login; "hide for now" lasts one session for this user on
              this tab. The "ask" row opens /dashboard/chat (the path that
              answers with citations), not this canvas. */}
          {messages.length === 0 && <CapabilityShowcase locale={locale} userId={userId} />}
          {messages.map((m, i) => (
            <div key={i} data-testid="agent-message" data-role={m.role} className={`my-2 ${m.role === "user" ? "text-right" : ""}`}>
              <span className={`inline-block rounded-lg px-3 py-2 ${m.role === "user" ? "bg-primary-tint" : "bg-surface-2"}`}>
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
      </main>
      {/* Desktop: card rail beside the chat. It is rendered unconditionally on
          purpose: gating it on `cards.length` moves 320 px of layout the
          moment getSuggestions resolves (measured: the same card 373 px wide
          before the answer, 266 px after), and the API always returns at least
          one card, so the gate would only ever be a flicker. */}
      <aside
        aria-label={t("suggestionsTitle")}
        className="hidden w-80 border-l border-line md:flex md:flex-col"
      >
        {cardRail}
      </aside>
    </div>
  );
}
