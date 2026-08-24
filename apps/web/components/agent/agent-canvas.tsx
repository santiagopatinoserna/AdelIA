"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Mic, UploadCloud, Sparkles } from "lucide-react";
import { streamAgent, getSuggestions } from "@/lib/agent-client-browser";
import type { AgentCard } from "@/lib/agent-types";
import { CardRenderer, type CardActionHandler } from "./cards/card-renderer";
import { AgentInput } from "./agent-input";
import { ProfileSwitcher } from "./profile-switcher";
import { useActiveProfile } from "@/lib/profile-context";
import { Link, useRouter } from "@/lib/navigation";

type Msg = { role: "user" | "assistant"; content: string };

export function AgentCanvas({ locale }: { locale: string }) {
  const t = useTranslations("agent");
  const router = useRouter();
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
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    const history = body.message
      ? messages
          .filter((m) => !(m.role === "assistant" && m.content === ""))
          .map((m) => ({ role: m.role, content: m.content }))
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
    } catch { /* aborted */ } finally { if (!stale()) setBusy(false); }
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
      className="flex h-[calc(100dvh-7rem)] flex-col md:h-[calc(100dvh-3.5rem)] md:flex-row"
    >
      {/* Chat column — the page's main landmark */}
      <main className="flex min-h-0 flex-1 flex-col">
        <ProfileSwitcher />
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {messages.length === 0 && <h1 className="ad-rise font-display text-lg font-normal text-ink-soft">{t("greeting")}</h1>}
          {/* First-run quick start: an empty canvas tells a new mom nothing.
              Three concrete doors into the product beat a blank screen. */}
          {messages.length === 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Link href="/dashboard/consulta/grabar" className="ad-card ad-card-hover block p-4">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                  <Mic className="h-4 w-4" strokeWidth={2} />
                </span>
                <p className="mt-2.5 text-sm font-semibold text-ink">{t("quickRecordTitle")}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-soft">{t("quickRecordBody")}</p>
              </Link>
              <Link href="/dashboard/upload" className="ad-card ad-card-hover block p-4">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100">
                  <UploadCloud className="h-4 w-4" strokeWidth={2} />
                </span>
                <p className="mt-2.5 text-sm font-semibold text-ink">{t("quickUploadTitle")}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-soft">{t("quickUploadBody")}</p>
              </Link>
              <button
                type="button"
                onClick={() => void drive({ message: t("sampleQuestion") })}
                className="ad-card ad-card-hover block p-4 text-left"
              >
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-honey-100 text-honey-700 ring-1 ring-honey-200">
                  <Sparkles className="h-4 w-4" strokeWidth={2} />
                </span>
                <p className="mt-2.5 text-sm font-semibold text-ink">{t("quickAskTitle")}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-soft">“{t("sampleQuestion")}”</p>
              </button>
            </div>
          )}
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
      </main>
      {/* Desktop: card rail beside the chat */}
      <aside
        aria-label={t("suggestionsTitle")}
        className="hidden w-80 border-l border-line md:flex md:flex-col"
      >
        {cardRail}
      </aside>
    </div>
  );
}
