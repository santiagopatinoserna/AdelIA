"use client";
import { createContext, useCallback, useContext, useRef, useState } from "react";

import { today } from "@/lib/api-client-browser";
import type { TodayDTO } from "@/lib/api-endpoints";
import { OnProfileSwitch } from "@/lib/profile-context";
import { TodayCard } from "./today-card";

// "Hoy con <nombre>" for the child she is looking at. The page renders the
// default child's card on the server; this keeps that exact card in the first
// render (`initial`, no effect, nothing fetched on mount) and replaces it only
// when she picks another child, by asking GET /today for that child through
// the same /api/backend proxy as every other per-child read in the browser.
//
// While the other child's day loads there is no card: Nora's vaccines under
// "¿Cómo está Adel?" would be the misattribution the card is scoped to avoid.
// A child with nothing due gets no card, as on the server, and a failed read
// leaves none either: fail-open to nothing, like the page.
const TodayCtx = createContext<TodayDTO | null>(null);

export function TodayFollowsChild({
  initial,
  locale,
  children,
}: {
  initial: TodayDTO | null;
  locale: string;
  children: React.ReactNode;
}) {
  const [shown, setShown] = useState<TodayDTO | null>(initial);
  // Only the latest tap may fill the card: Adel then Leo in quick succession
  // must not end on Adel's lines because his answer came back last.
  const latest = useRef(0);
  const onSwitch = useCallback(
    (profileId: string) => {
      const mine = ++latest.current;
      setShown(null);
      today(locale, profileId)
        .then((day) => {
          if (latest.current === mine) setShown(day);
        })
        .catch(() => {});
    },
    [locale],
  );
  return (
    <OnProfileSwitch onSwitch={onSwitch}>
      <TodayCtx.Provider value={shown}>{children}</TodayCtx.Provider>
    </OnProfileSwitch>
  );
}

// Where the canvas places the card (under the greeting, before the showcase).
export function TodaySlot() {
  const day = useContext(TodayCtx);
  return day ? <TodayCard name={day.name} items={day.items} /> : null;
}
