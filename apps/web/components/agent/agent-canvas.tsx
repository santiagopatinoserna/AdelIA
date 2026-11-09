"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { streamAgent, getSuggestions, dismissSuggestion } from "@/lib/agent-client-browser";
import type { AgentCard, AgentThread } from "@/lib/agent-types";
import type { Citation, EvidenceCitation } from "@/lib/chat-types";
import { AnswerContent } from "@/components/answer-content";
import { Mic, RotateCcw } from "lucide-react";
import { CardRenderer, type CardActionHandler } from "./cards/card-renderer";
import { AgentInput } from "./agent-input";
import { AgentSources } from "./agent-sources";
import { PanelMore } from "./panel-more";
import { track } from "@/lib/analytics";
import { ProfileSwitcher } from "./profile-switcher";
import { GrowthMark, monthsSince, useGrowthMarkLabel } from "./growth-mark";
import { askExampleKey } from "@/lib/ask-example";
import { todayInAppZone } from "@/lib/dates";
import { useActiveProfile } from "@/lib/profile-context";
import { Link, useRouter } from "@/lib/navigation";
import { takeLandingQuestion } from "@/lib/landing-question";

// An assistant turn now carries what it cited (audit 3.7). Empty arrays on a
// user turn and on any answer that cited nothing, which is most of them.
type Msg = {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  evidence_citations: EvidenceCitation[];
  // A turn that failed carries what to send again: "Volver a preguntar"
  // replaces the failed exchange with the same question, sent once.
  retry?: DriveInput;
};

type DriveInput = {
  message?: string; card_action?: object; display?: string;
  clarification?: { field: string; value: string };
};

// The failed turn's placeholder becomes the sentence; only a turn she typed
// (or a clarify press, which re-sends her question) can be asked again. A
// confirmation is not replayed: if the write landed before the stream broke,
// a second one would note the same entry twice.
function failTurn(p: Msg[], content: string, input: DriveInput): Msg[] {
  const n = [...p];
  const last = n[n.length - 1];
  if (input.message && last?.role === "assistant") {
    n[n.length - 1] = { ...last, content, retry: input };
  } else {
    n.push({ role: "assistant", content, citations: [], evidence_citations: [] });
  }
  return n;
}

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

// "Hay demasiadas cosas, no sé dónde leer" (a mother, 2026-11-09). The first
// screen is the conversation: the greeting, her baby's age, "Hoy" when there
// is something today, one example question, the record button and the field.
// Everything else (the API's suggestion cards, the visit summary, the
// questionnaire, imports, "Guardar mi cuenta") is under one folded "Más"
// (panel-more.tsx), once each. Once she asks, the thread is alone: no
// greeting, no "Más", no suggestion card under the answer, only the cards of
// the turn itself (a record to confirm, a question with buttons). There is no
// desktop rail any more: it drew the same suggestions a second time.
//
// `today` is the "Hoy con <nombre>" card (components/today-follows-child): the
// page fetches it and swaps it when she picks another child; the canvas only
// decides where it sits, under the greeting, and only while the thread is
// empty.
//
// `initialThread` is the stored conversation she was in (GET /agent/thread),
// read on the server. The panel still opens on her baby and "Hoy", as every
// account's always has; "Seguir la conversación" brings the thread back in one
// tap. `askKey` names the question she typed on the landing
// (lib/landing-question): it is sent once, on mount.
export function AgentCanvas({
  locale,
  today = null,
  initialThread = null,
  askKey = null,
  isGuest = false,
}: {
  locale: string;
  today?: React.ReactNode;
  initialThread?: AgentThread | null;
  askKey?: string | null;
  isGuest?: boolean;
}) {
  const t = useTranslations("agent");
  const tg = useTranslations("guestSpace");
  const tp = useTranslations("panel");
  const tAsk = useTranslations("showcaseAsk");
  const router = useRouter();
  const { activeId, profiles } = useActiveProfile();
  // Her baby's name in the greeting when we have it: the same server-fed
  // profile list the ProfileProvider starts with, so the first render already
  // has it and nothing is set after mount (7adb21c). Only a child's name: the
  // parent's own row ("Mi perfil", relationship self) is not a baby.
  const active = profiles.find((p) => p.id === activeId);
  const activeName = active?.relationship === "child" ? active.display_name?.trim() : undefined;
  const growthMark = useGrowthMarkLabel();
  // One example question that fits the child on screen (lib/ask-example: Lucía
  // at 5 months was once offered a question about a 13-month-old). Read from
  // the server-fed profile list during render, so nothing is set after mount
  // (7adb21c). Noon in Madrid, as the age line counts.
  const months =
    active?.relationship === "child" && active.date_of_birth
      ? monthsSince(active.date_of_birth, new Date(`${todayInAppZone()}T12:00:00`))
      : null;
  const askExample = tAsk(askExampleKey(months));
  const [qOpen, qClose] = locale === "fr" ? ["« ", " »"] : ["“", "”"];
  // Only a thread about the child on screen can be resumed; one about a
  // sibling stays in the history.
  const resumable =
    initialThread && initialThread.messages.length > 0 &&
    (!initialThread.profile_id || initialThread.profile_id === activeId)
      ? initialThread
      : null;
  const [messages, setMessages] = useState<Msg[]>([]);
  // The stored conversation the next turn continues (services/agent_thread).
  const threadRef = useRef<string | null>(null);
  const [resumed, setResumed] = useState(false);
  function resume() {
    if (!resumable) return;
    threadRef.current = resumable.id;
    setResumed(true);
    setMessages(resumable.messages.map((m) => ({
      role: m.role, content: m.content,
      citations: m.citations ?? [], evidence_citations: m.evidence_citations ?? [],
    })));
  }
  const [cards, setCards] = useState<AgentCard[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  // Cards a turn delivered (a clarify question, a record to confirm) must
  // survive a refresh of the dashboard suggestions. The refresh used to
  // REPLACE the list, so a suggestions request that finished after the turn
  // wiped the card she had to answer.
  const turnCardIds = useRef(new Set<string>());
  const withSuggestions = (suggested: AgentCard[]) => (prev: AgentCard[]) => {
    const kept = prev.filter((c) => turnCardIds.current.has(c.id));
    return [...kept, ...suggested.filter((c) => !turnCardIds.current.has(c.id))];
  };

  useEffect(() => {
    let alive = true;
    getSuggestions(activeId, locale).then((c) => { if (alive) setCards(withSuggestions(c)); }).catch(() => {});
    return () => { alive = false; };
  }, [activeId, locale]);

  // The landing's question, answered here and only once: taking it out of
  // sessionStorage is what makes a second mount (React's dev double effect, a
  // reload) find nothing to send. The ?ask key leaves the address bar too.
  useEffect(() => {
    if (!askKey) return;
    const question = takeLandingQuestion(askKey);
    router.replace("/dashboard");
    if (question) void drive({ message: question });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askKey]);

  // `display` is what her bubble shows when it differs from what the API
  // gets: a clarify press sends her question again with the value, and the
  // transcript shows the button she pressed.
  async function drive(input: DriveInput) {
    const { display, ...body } = input;
    const epoch = ++epochRef.current;
    const stale = () => epochRef.current !== epoch;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    // A failed exchange is not history: neither the error sentence nor the
    // question it failed on (that one is being sent again, or was abandoned).
    const history = body.message
      ? messages
          .filter((m, k) =>
            !(m.role === "assistant" && (m.content === "" || m.retry)) &&
            !(m.role === "user" && messages[k + 1]?.retry))
          .slice(-HISTORY_MAX_MESSAGES)
          .map((m) => ({
            role: m.role,
            content: m.content.slice(0, HISTORY_MAX_CHARS_PER_MESSAGE),
          }))
      : undefined;
    // Funnel steps (no-op without consent): that she asked, never what. A
    // clarify press answers the question already counted.
    const asking = Boolean(body.message) && display === undefined;
    if (asking) track(messages.some((m) => m.role === "user") ? "follow_up" : "question_sent");
    if (body.message)
      setMessages((p) => [
        ...p,
        { role: "user", content: display ?? body.message!, citations: [], evidence_citations: [] },
        { role: "assistant", content: "", citations: [], evidence_citations: [] },
      ]);
    try {
      for await (const ev of streamAgent(
        {
          ...body, profile_id: activeId, locale, thread_id: threadRef.current,
          ...(history ? { history } : {}),
        },
        controller.signal,
      )) {
        if (stale()) break;
        if (ev.type === "thread") {
          threadRef.current = ev.thread_id;
        } else if (ev.type === "token") {
          setMessages((p) => { const n = [...p]; const last = n[n.length - 1];
            if (last?.role === "assistant") n[n.length - 1] = { ...last, content: last.content + ev.content }; return n; });
        } else if (ev.type === "card") {
          turnCardIds.current.add(ev.card.id);
          setCards((p) => [ev.card, ...p.filter((c) => c.id !== ev.card.id)]);
        } else if (ev.type === "final") {
          if (asking) track("answer_shown");
          setMessages((p) => { const n = [...p]; const last = n[n.length - 1];
            if (last?.role === "assistant")
              n[n.length - 1] = { ...last, citations: ev.citations, evidence_citations: ev.evidence_citations };
            return n; });
        } else if (ev.type === "error") {
          // The API answered and said it could not: not her connection. Mostly
          // the model being unreachable (no key, an outage, a rate limit); the
          // red flags already ran before it, without any model.
          setMessages((p) => failTurn(p, t("unavailableAnswer"), input));
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
        setMessages((p) => {
          const last = p[p.length - 1];
          return last?.role === "assistant" && !last.content ? failTurn(p, t("errorAnswer"), input) : p;
        });
      }
    } finally { if (!stale()) setBusy(false); }
  }

  function retry(i: number) {
    const failed = messages[i];
    if (busy || !failed?.retry) return;
    setMessages((p) => p.slice(0, i - 1));
    void drive(failed.retry);
  }

  const onCardAction: CardActionHandler = (intent, card, value) => {
    turnCardIds.current.delete(card.id);
    if (intent === "cancel") { setCards((p) => p.filter((c) => c.id !== card.id)); return; }
    if (intent === "confirm") {
      const pl = card.payload as { tool_name: string; tool_args: object };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: pl.tool_name, tool_args: pl.tool_args } });
      getSuggestions(activeId, locale).then((c) => setCards(withSuggestions(c))).catch(() => {});
      return;
    }
    if (intent === "clarify") {
      const pl = card.payload as {
        field: string; message: string;
        options: { value: string; label: string }[]; skip: { value: string; label: string };
      };
      const chosen = [...pl.options, pl.skip].find((o) => o.value === value);
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({
        message: pl.message, display: chosen?.label ?? value,
        clarification: { field: pl.field, value: value ?? pl.skip.value },
      });
      return;
    }
    if (intent === "answer") {
      const pl = card.payload as { field: string };
      setCards((p) => p.filter((c) => c.id !== card.id));
      void drive({ card_action: { intent: "confirm", tool_name: "completar_perfil", tool_args: { field: pl.field, value } } });
      getSuggestions(activeId, locale).then((c) => setCards(withSuggestions(c))).catch(() => {});
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

  // She closed a suggestion: gone now, and the server remembers it for her
  // account (services/dismissals), so neither a reload nor another phone
  // brings it back. A failed save costs nothing worse than seeing it again.
  function dismiss(card: AgentCard) {
    const key = card.payload.dismiss_key;
    setCards((p) => p.filter((c) => c.id !== card.id));
    if (typeof key === "string") void dismissSuggestion(key).catch(() => {});
  }

  // The cards of the turn (a record to confirm, a question with buttons) sit
  // in the thread; the API's standing suggestions only under "Más".
  const turnCards = cards.filter((c) => turnCardIds.current.has(c.id));
  const suggestions = cards.filter((c) => !turnCardIds.current.has(c.id));

  return (
    <div
      data-testid="agent-canvas"
      className="ad-agent-canvas flex h-[calc(100dvh-7rem)] flex-col md:h-[calc(100dvh-3.5rem)]"
    >
      {/* One reading column, the page's main landmark. */}
      <main className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
        <ProfileSwitcher />
        {/* "Falta el botón para grabar la cita con el médico" (2026-11-06):
            the real recorder, consent first, one tap from the main screen,
            for every account, and visible while a conversation is open too.
            "Guardar mi cuenta" moved under "Más" (2026-11-09): two links
            side by side above the greeting was where "no sé dónde leer"
            started. */}
        {/* A <header>, not a <div>: the thread below stays the first div of
            this column, the scroll area whose bottom is the fold
            (e2e/showcase.spec.ts measures it as `main > div`). */}
        <header className="flex flex-wrap items-center gap-2 px-3 pt-2">
          <Link
            href="/dashboard/consulta/grabar"
            data-testid="record-consult"
            className="ad-btn ad-btn-ghost min-h-[44px] px-3.5 text-sm"
          >
            <Mic className="h-4 w-4" strokeWidth={2.2} aria-hidden />
            {tg("recordConsult")}
          </Link>
          {messages.length === 0 && resumable && !resumed && !askKey && (
            <button
              type="button"
              data-testid="continue-conversation"
              onClick={resume}
              className="ad-btn ad-btn-ghost min-h-[44px] px-3.5 text-sm"
            >
              {tg("continueConversation")}
            </button>
          )}
          {/* A conversation hides the greeting and "Hoy": this is the way
              back to them. The conversation stays in the history. */}
          {messages.length > 0 && (
            <button
              type="button"
              data-testid="new-conversation"
              disabled={busy}
              onClick={() => { threadRef.current = null; setMessages([]); }}
              className="ad-btn ad-btn-ghost min-h-[44px] px-3.5 text-sm"
            >
              {tg("newConversation")}
            </button>
          )}
        </header>
        {/* Empty state on md+: the greeting, the age, "Hoy", the example and
            "Más" are the only children, so `justify-content` centres the block instead
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
          {/* The one headline of this screen, the only serif on it. */}
          {/* Always the page's h1; once the thread has started it stays for
              screen readers only (axe page-has-heading-one), and the answers
              below start their headings at h2. */}
          <h1 className={messages.length === 0 ? "ad-rise font-display text-title text-ink" : "sr-only"}>
            {activeName ? t("greetingWithName", { name: activeName }) : t("greeting")}
          </h1>
          {/* Her baby's real name and age, one quiet line. Nothing when the
              profile has no date of birth. */}
          {messages.length === 0 && growthMark && <GrowthMark label={growthMark} />}
          {messages.length === 0 && today}
          {/* One question to start with, sent here in one tap, so a first
              visit is not an empty field. It replaces the showcase's three
              rows and four chips (2026-11-09). */}
          {messages.length === 0 && (
            <div className="mt-6">
              <p className="text-sm text-ink-soft">{tp("example")}</p>
              <button
                type="button"
                data-testid="ask-example"
                disabled={busy}
                onClick={() => void drive({ message: askExample })}
                className="mt-1 min-h-[44px] text-left text-base italic leading-snug text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink"
              >
                {qOpen}{askExample}{qClose}
              </button>
            </div>
          )}
          {messages.length === 0 && (
            <PanelMore cards={suggestions} isGuest={isGuest} onAction={onCardAction} onDismiss={dismiss} />
          )}
          {messages.map((m, i) => {
            // A turn that answered with a card only (a record to confirm, a
            // question with buttons) leaves no text: no empty bubble for it.
            const last = i === messages.length - 1;
            if (m.role === "assistant" && !m.content && !(busy && last)) return null;
            if (m.role === "user") {
              return (
                <div key={i} data-testid="agent-message" data-role="user" className="my-3 flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary-tint px-4 py-2.5 text-base text-ink">
                    {m.content}
                  </p>
                </div>
              );
            }
            // The answer is read like the demo's: Markdown, the plan's
            // sections and map, quiet citation markers, at full width. It used
            // to be printed raw, "## Hoy - **...**" (AUDITORIA_UX.md, 11c).
            return (
              <div key={i} data-testid="agent-message" data-role="assistant" className="my-4 [&_[data-testid=answer-content]]:mt-0">
                {m.retry ? (
                  <>
                    <p role="alert" className="text-base text-ink">{m.content}</p>
                    {last && (
                      <button
                        type="button"
                        onClick={() => retry(i)}
                        disabled={busy}
                        className="ad-btn ad-btn-ghost mt-3 min-h-[44px] px-4 text-sm disabled:opacity-60"
                      >
                        <RotateCcw className="h-4 w-4" strokeWidth={2} aria-hidden />
                        {t("retry")}
                      </button>
                    )}
                  </>
                ) : m.content ? (
                  <AnswerContent level={2} recordLinks={m.citations.length > 0}>{m.content}</AnswerContent>
                ) : (
                  <p role="status" className="flex items-center gap-2.5 text-base text-ink-soft">
                    <span className="ad-pulse-dot shrink-0" aria-hidden />
                    {t("thinking")}
                  </p>
                )}
                {/* The sources behind the markers in the text above, the same
                    cards the chat renders (audit 3.7), folded into one line
                    that a marker tap opens (agent-sources.tsx). */}
                <AgentSources citations={m.citations} evidence={m.evidence_citations} locale={locale} />
              </div>
            );
          })}
          {/* The cards of the turn, in the thread at every width. No
              standing suggestion here: a Telegram card under an answer or
              under "¿Lo anoto así?" competed with what she came to read. */}
          {turnCards.length > 0 && (
            <div className="mt-3 flex flex-col gap-3">
              {turnCards.map((c) => <CardRenderer key={c.id} card={c} onAction={onCardAction} />)}
            </div>
          )}
        </div>
        {/* After an answer the field says it continues the same topic: the
            history of this conversation rides with the next question. */}
        <AgentInput locale={locale} disabled={busy} onStop={() => abortRef.current?.abort()}
                    placeholder={messages.length > 0 ? tg("followUpPlaceholder") : undefined}
                    onSubmit={(text) => void drive({ message: text })} />
      </main>
    </div>
  );
}
