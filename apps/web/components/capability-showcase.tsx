"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ChevronRight,
  ClipboardList,
  Download,
  ListChecks,
  Mic,
  Send,
  Sparkles,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

import { Link } from "@/lib/navigation";
import { readShowcaseHidden, writeShowcaseHidden } from "@/lib/showcase-storage";

// The capability showcase everyone sees on the agent home while the thread is
// empty: the real doors into the product, in the order a parent needs them,
// with three visual weights instead of eight identical cards.
//
//   1. three PRIMARY rows, the capabilities of the first day (spec 7.3);
//   2. four SECONDARY chips, the second-week tools;
//   3. "Ajustes", which is already a tab of the bottom bar and is deliberately
//      NOT repeated here (the same door twice is what made everything weigh
//      the same).
//
// On a phone there is no carousel any more: a full-width list cannot cut a
// word in half, and the titles WRAP there instead of being ellipsised (fr is
// the long locale: "Journal quotidien sur Telegram à 20 h" was cut inside the
// "20 h" the feature is named after). The rows become three cards only at
// 1264 px, not at md and not at lg: at md the 320 px card rail is already
// beside the chat column, and at lg the card is 215 px wide, where the
// two-line clamp cuts the parent's own sentence mid-word in every locale. As
// cards they carry a fixed number of lines (title 1, example 2, detail 2), so
// their heights match by CONTENT and no card ends in dead space.
// The 1264 of every `min-[1264px]:` below MUST stay in step with the
// `@media (min-width: 1264px)` block of .ad-cap-row in app/globals.css.
// It comes back on every login on purpose: "hide for now" lives in
// sessionStorage, keyed to the signed-in user and cleared by the sign-in page
// (lib/showcase-storage).
const TITLE_ID = "capability-showcase-title";
const GRID_ID = "capability-showcase-grid";

// Where "ask" leads. The chat page runs the dual retrieval (the baby's
// documents + the clinical evidence corpus) and renders both citation
// blocks; the agent canvas on the home streams prose only, so sending the
// question there would break the card's "with citations" promise. `q` is
// sent once on arrival and then stripped from the URL (chat-page-client).
const CHAT_PATH = "/dashboard/chat";

type PrimaryKey = "ask" | "diary" | "record";
type ChipKey = "upload" | "briefing" | "questionnaire" | "import";

type PrimaryCard = { key: PrimaryKey; icon: LucideIcon; accent: boolean; href?: string };

// Order (spec 7.3): first what bears fruit today with an empty account, then
// what has to be set up today to exist tomorrow, then the strongest promise,
// which needs an appointment and rarely happens on day one.
const PRIMARY: readonly PrimaryCard[] = [
  { key: "ask", icon: Sparkles, accent: true },
  { key: "diary", icon: Send, accent: false, href: "/dashboard/ingestion/telegram" },
  { key: "record", icon: Mic, accent: false, href: "/dashboard/consulta/grabar" },
];

const CHIPS: readonly { key: ChipKey; icon: LucideIcon; href: string }[] = [
  { key: "upload", icon: UploadCloud, href: "/dashboard/upload" },
  { key: "briefing", icon: ClipboardList, href: "/dashboard/briefings/new" },
  { key: "questionnaire", icon: ListChecks, href: "/dashboard/questionnaire" },
  { key: "import", icon: Download, href: "/dashboard/ingestion" },
];

// Amber is the colour of discovering, and "Pregunta con citas" is the only
// capability that answers on an empty account. It is the one amber row.
const ICON_BOX =
  "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[0.625rem] ring-1 " +
  "min-[1264px]:h-9 min-[1264px]:w-9 min-[1264px]:rounded-lg";
const ICON_PINE = "bg-primary-tint text-on-primary-tint ring-primary-tint-line";
const ICON_ACCENT = "bg-accent-tint text-on-accent-tint ring-accent-tint-line";

// The action link: the visible label is the accessible name and the pseudo
// element stretches the hit area over the whole row (no nested controls). On a
// phone the label collapses to a chevron; the name stays for the screen
// reader and for the keyboard.
const ACTION =
  "inline-flex items-center gap-1 self-center text-sm font-semibold " +
  "after:absolute after:inset-0 after:rounded-[inherit] min-[1264px]:mt-3 min-[1264px]:self-start";

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
      className={hidden ? "mt-3" : "ad-rise mt-3"}
    >
      {/* One persistent toggle (APG disclosure pattern): the same <button>
          node in both states, so keyboard and screen-reader focus stays on
          it and the aria-expanded change is announced on the focused
          control instead of the button vanishing under the user.
          The section title is still an h2 in the DOM, but it is painted as an
          eyebrow: the greeting is the only headline of this screen. */}
      <div className="flex items-center justify-between gap-3">
        {hidden ? (
          <p id={TITLE_ID} className="text-sm text-ink-soft">
            {t("collapsed")}
          </p>
        ) : (
          <h2 id={TITLE_ID} className="ad-eyebrow">
            {t("primaryEyebrow")}
          </h2>
        )}
        <button
          type="button"
          aria-expanded={!hidden}
          aria-controls={hidden ? undefined : GRID_ID}
          onClick={() => toggle(!hidden)}
          className={
            "-mr-1 inline-flex min-h-[var(--tap-md)] shrink-0 items-center px-1 text-sm underline underline-offset-2 hover:text-primary-text-hover " +
            (hidden ? "font-medium text-primary-text" : "text-ink-soft")
          }
        >
          {hidden ? t("show") : t("hide")}
        </button>
      </div>

      {!hidden && (
        <>
          {/* Phone, tablet and laptop up to 1264: three full-width rows,
              72 px each, titles that wrap, nothing to cut. 1264+: three cards
              of equal content (title 1 line, example 2, detail 2), so no card
              ends in a hole. */}
          <ul
            id={GRID_ID}
            data-testid="showcase-grid"
            className="mt-2 grid gap-2 min-[1264px]:mt-3 min-[1264px]:grid-cols-3 min-[1264px]:gap-3"
          >
            {PRIMARY.map((card) => {
              const Icon = card.icon;
              const titleId = `capability-showcase-${card.key}`;
              const href =
                card.key === "ask"
                  ? { pathname: CHAT_PATH, query: { q: t("cards.ask.example") } }
                  : card.href!;
              return (
                <li
                  key={card.key}
                  data-testid="showcase-card"
                  data-key={card.key}
                  className="ad-cap-row"
                >
                  <span
                    className={`${ICON_BOX} ${card.accent ? ICON_ACCENT : ICON_PINE}`}
                    aria-hidden="true"
                  >
                    <Icon className="h-[1.125rem] w-[1.125rem]" strokeWidth={2} />
                  </span>
                  {/* `w-full` is load-bearing at 1264+: the card is a column
                      flex container with `align-items: flex-start`, which
                      sizes this div to max-content, so without it the text
                      column grows past the card padding and the h3 is clipped
                      by the card border instead of by `truncate`. */}
                  <div className="min-w-0 min-[1264px]:w-full">
                    {/* `font-sans` is load-bearing, not decoration: the base
                        layer paints every h1..h4 in the display serif, so
                        without it these three titles come out in Fraunces and
                        the greeting stops being the one headline of the
                        screen (spec 7.1: one display face per panel screen). */}
                    <h3
                      id={titleId}
                      className="font-sans text-[0.9375rem] font-semibold leading-5 text-ink min-[1264px]:truncate"
                    >
                      {t(`cards.${card.key}.title`)}
                    </h3>
                    <p className="ad-clamp-2 mt-0.5 text-[0.8125rem] italic leading-[1.125rem] text-ink-soft min-[1264px]:mt-1.5 min-[1264px]:min-h-9 min-[1264px]:text-sm min-[1264px]:leading-[1.125rem] min-[1264px]:text-ink">
                      {qOpen}
                      {t(`cards.${card.key}.example`)}
                      {qClose}
                    </p>
                    {/* The wrapper carries the hiding, not the paragraph:
                        `.ad-clamp-2` sets display:-webkit-box and, being a
                        later rule of the same utilities layer, it would beat
                        `hidden` and print the detail on the phone too, where
                        the row has no room for it. */}
                    <div className="hidden min-[1264px]:block">
                      <p className="ad-clamp-2 mt-1.5 min-h-9 text-xs leading-[1.125rem] text-ink-soft">
                        {t(`cards.${card.key}.detail`)}
                      </p>
                    </div>
                  </div>
                  <Link
                    href={href}
                    aria-describedby={titleId}
                    className={`${ACTION} ${
                      card.accent
                        ? "text-accent-text hover:text-accent-text-hover"
                        : "text-primary-text hover:text-primary-text-hover"
                    }`}
                  >
                    <span className="sr-only min-[1264px]:not-sr-only">
                      {t(`cards.${card.key}.action`)}
                    </span>
                    <ChevronRight
                      className="h-5 w-5 min-[1264px]:hidden"
                      strokeWidth={2.2}
                      aria-hidden="true"
                    />
                    <span aria-hidden="true" className="hidden min-[1264px]:inline">
                      →
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>

          <p className="ad-eyebrow mt-4">{t("secondaryEyebrow")}</p>
          <ul
            data-testid="showcase-chips"
            className="mt-2 grid grid-cols-2 gap-2 min-[1264px]:grid-cols-4"
          >
            {CHIPS.map((chip) => {
              const Icon = chip.icon;
              return (
                <li
                  key={chip.key}
                  data-testid="showcase-chip"
                  data-key={chip.key}
                  className="ad-cap-chip"
                >
                  <Icon
                    className="h-[1.125rem] w-[1.125rem] text-primary-text"
                    strokeWidth={2}
                    aria-hidden="true"
                  />
                  <Link
                    href={chip.href}
                    className="min-w-0 after:absolute after:inset-0 after:rounded-[inherit]"
                  >
                    {t(`chips.${chip.key}`)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
