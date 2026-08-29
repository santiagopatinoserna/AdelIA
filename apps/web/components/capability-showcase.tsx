"use client";

import { useEffect, useState, type FocusEvent } from "react";
import { useTranslations } from "next-intl";
import {
  ClipboardList,
  Download,
  ListChecks,
  Mic,
  Send,
  Settings,
  Sparkles,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

import { Link } from "@/lib/navigation";
import { readShowcaseHidden, writeShowcaseHidden } from "@/lib/showcase-storage";

// The capability showcase everyone sees on the agent home while the thread
// is empty: one card per real capability, each with a concrete example from
// a parent's day and a visible action (a route). It comes back on every
// login on purpose: "hide for now" lives in sessionStorage, keyed to the
// signed-in user and cleared by the sign-in page (lib/showcase-storage).
const TITLE_ID = "capability-showcase-title";
const GRID_ID = "capability-showcase-grid";

// Where "ask" leads. The chat page runs the dual retrieval (the baby's
// documents + the clinical evidence corpus) and renders both citation
// blocks; the agent canvas on the home streams prose only, so sending the
// question there would break the card's "with citations" promise. `q` is
// sent once on arrival and then stripped from the URL (chat-page-client).
const CHAT_PATH = "/dashboard/chat";

type Tone = "pine" | "honey";

type ShowcaseCard =
  | { key: "record" | "diary" | "upload" | "briefing" | "questionnaire" | "import" | "settings";
      icon: LucideIcon; tone: Tone; href: string }
  | { key: "ask"; icon: LucideIcon; tone: Tone; href?: undefined };

// Order = the order a new parent meets the product: record the visit, ask,
// keep the diary, feed the record, then the "later" tools.
const CARDS: readonly ShowcaseCard[] = [
  { key: "record", icon: Mic, tone: "pine", href: "/dashboard/consulta/grabar" },
  { key: "ask", icon: Sparkles, tone: "honey" },
  { key: "diary", icon: Send, tone: "pine", href: "/dashboard/ingestion/telegram" },
  { key: "upload", icon: UploadCloud, tone: "pine", href: "/dashboard/upload" },
  { key: "briefing", icon: ClipboardList, tone: "pine", href: "/dashboard/briefings/new" },
  { key: "questionnaire", icon: ListChecks, tone: "pine", href: "/dashboard/questionnaire" },
  { key: "import", icon: Download, tone: "pine", href: "/dashboard/ingestion" },
  { key: "settings", icon: Settings, tone: "pine", href: "/dashboard/settings" },
];

const ICON_BOX: Record<Tone, string> = {
  pine: "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-600 ring-1 ring-pine-100",
  honey: "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-honey-100 text-honey-700 ring-1 ring-honey-200",
};

// Primary action: the visible label is the accessible name; the pseudo
// element stretches the hit area over the whole card (no nested controls).
const ACTION =
  "inline-flex items-center gap-1 text-sm font-semibold text-pine-600 hover:text-pine-700 " +
  "after:absolute after:inset-0 after:rounded-[inherit]";

// Phone carousel only: when a control inside a card receives focus (Tab),
// align its card with the snap point so the focused control is fully on
// screen. Without this, the browser's minimal reveal scroll is undone by
// scroll-snap and the focus ring lands half off the right edge. Guarded on
// real horizontal overflow so the md+ grid is never touched.
function alignFocusedCard(e: FocusEvent<HTMLLIElement>) {
  const list = e.currentTarget.parentElement;
  if (list && list.scrollWidth > list.clientWidth) {
    e.currentTarget.scrollIntoView({ inline: "start", block: "nearest" });
  }
}

export function CapabilityShowcase({ locale, userId }: { locale: string; userId: string }) {
  const t = useTranslations("showcase");
  // null until mounted: the server render must not guess the storage state
  // (no flash of the full grid for someone who just hid it, no hydration
  // mismatch either way).
  const [hidden, setHidden] = useState<boolean | null>(null);

  useEffect(() => {
    setHidden(readShowcaseHidden(userId));
  }, [userId]);

  if (hidden === null) return null;

  function toggle(next: boolean) {
    writeShowcaseHidden(userId, next);
    setHidden(next);
  }

  // Quotation marks follow the locale: guillemets (with the French
  // non-breaking inner spaces) in fr, curly quotes in es/en.
  const [qOpen, qClose] = locale === "fr" ? ["« ", " »"] : ["“", "”"];

  return (
    <section
      aria-labelledby={TITLE_ID}
      data-testid="capability-showcase"
      className={hidden ? "mt-4" : "ad-rise mt-4"}
    >
      {/* One persistent toggle (APG disclosure pattern): the same <button>
          node in both states, so keyboard and screen-reader focus stays on
          it and the aria-expanded change is announced on the focused
          control instead of the button vanishing under the user. */}
      <div className="flex items-center justify-between gap-3">
        {hidden ? (
          <p id={TITLE_ID} className="text-sm text-ink-soft">
            {t("collapsed")}
          </p>
        ) : (
          <h2 id={TITLE_ID} className="font-display text-base font-semibold text-pine-900">
            {t("title")}
          </h2>
        )}
        <button
          type="button"
          aria-expanded={!hidden}
          aria-controls={hidden ? undefined : GRID_ID}
          onClick={() => toggle(!hidden)}
          className={
            hidden
              ? "shrink-0 text-sm font-medium text-pine-600 underline underline-offset-2 hover:text-pine-700"
              : "shrink-0 text-xs text-ink-soft underline underline-offset-2 hover:text-pine-700"
          }
        >
          {hidden ? t("show") : t("hide")}
        </button>
      </div>
      {!hidden && (
        /* Phone: a horizontal, snapping carousel (78vw cards, next one
           peeking in as the scroll hint); the list scrolls, the body never
           does. md (768-1023): 2 columns, because the 320 px card rail sits
           beside the chat column and 4 columns would squash the cards.
           lg+: 4 columns, two rows. */
        <ul
          id={GRID_ID}
          data-testid="showcase-grid"
          className="-mx-3 mt-3 flex snap-x scroll-pl-3 gap-3 overflow-x-auto px-3 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:mx-0 md:grid md:grid-cols-2 md:scroll-pl-0 md:overflow-visible md:px-0 md:pb-0 lg:grid-cols-4"
        >
          {CARDS.map((card) => {
            const Icon = card.icon;
            const titleId = `capability-showcase-${card.key}`;
            const href =
              card.key === "ask"
                ? { pathname: CHAT_PATH, query: { q: t("cards.ask.example") } }
                : card.href;
            return (
              <li
                key={card.key}
                data-testid="showcase-card"
                onFocus={alignFocusedCard}
                className="ad-card ad-card-hover relative flex w-[78vw] max-w-xs shrink-0 snap-start flex-col p-4 md:w-auto md:max-w-none"
              >
                <span className={ICON_BOX[card.tone]} aria-hidden="true">
                  <Icon className="h-4 w-4" strokeWidth={2} />
                </span>
                <h3 id={titleId} className="mt-2.5 text-sm font-semibold text-ink">
                  {t(`cards.${card.key}.title`)}
                </h3>
                <p className="mt-1.5 text-sm italic leading-snug text-ink">
                  {qOpen}
                  {t(`cards.${card.key}.example`)}
                  {qClose}
                </p>
                <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">
                  {t(`cards.${card.key}.detail`)}
                </p>
                <div className="mt-auto pt-3">
                  <Link href={href} aria-describedby={titleId} className={ACTION}>
                    {t(`cards.${card.key}.action`)}
                    <span aria-hidden="true">→</span>
                  </Link>
                  {card.key === "ask" && (
                    /* Above the stretched primary action, so it stays clickable. */
                    <Link
                      href={{ pathname: CHAT_PATH, query: { q: t("cards.ask.altQuestion") } }}
                      className="relative z-10 mt-1.5 block text-left text-xs leading-snug text-ink-soft underline underline-offset-2 hover:text-pine-700"
                    >
                      {t("cards.ask.altLabel")} {t("cards.ask.altQuestion")}
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
