"use client";

import { useTranslations } from "next-intl";
import type { Profile } from "@/lib/enrichment-types";
import { useActiveProfile } from "@/lib/profile-context";

// The height mark: the pencil line a parent draws on the door frame. It is the
// ONE warm element of the panel home, and it is a MARK, not a rule: it sits to
// the left of the label and takes one line of height.
//
// It cannot read as stock by construction: the label comes from the active
// profile (a real name, a real age that changes on its own every month), so no
// two accounts see the same mark. No pastel, no curve, no baby icon.
//
// Two strokes, not one, and in two colours. A single tilted stroke beside a
// mono small-caps label fuses into a typographic glyph: the mark read as
// "/ LUCIA · 7 MESES", a path separator, not a pencil line. The vertical
// neutral stroke is the door frame; the near-level amber one is the tick left
// on it, and it needs the frame to mean anything. Both are drawn at uniform
// scale in a fixed 9x14 box, so the tilt does not change with the viewport.
//
// It is NOT a separator: the flex-1 hairline this used to carry became a
// 781 px full-width divider at 1280, right under the header's own rule and
// between the greeting and the content the greeting introduces.
export function GrowthMark({ label }: { label: string }) {
  return (
    <div className="mt-2 mb-4 flex w-fit items-center gap-2" data-testid="growth-mark">
      <svg
        aria-hidden="true"
        viewBox="0 0 9 14"
        className="h-3.5 w-[9px] shrink-0 overflow-visible"
      >
        <path
          d="M1.5 0 L1.5 14"
          fill="none"
          stroke="var(--color-line-strong)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d="M0 8.9 L9 7.6"
          fill="none"
          stroke="var(--color-accent-line)"
          strokeWidth="1.5"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="ad-eyebrow shrink-0 whitespace-nowrap">{label}</span>
    </div>
  );
}

// Whole months lived, calendar-wise (not days/30.44): a baby born on the 12th
// turns "3 months" on the 12th, which is the date the parent has in mind.
export function monthsSince(dobISO: string, now: Date): number | null {
  const dob = new Date(`${dobISO.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(dob.getTime()) || dob.getTime() > now.getTime()) return null;
  let months = (now.getFullYear() - dob.getFullYear()) * 12 + (now.getMonth() - dob.getMonth());
  if (now.getDate() < dob.getDate()) months -= 1;
  return months;
}

export function daysSince(dobISO: string, now: Date): number | null {
  const dob = new Date(`${dobISO.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(dob.getTime()) || dob.getTime() > now.getTime()) return null;
  return Math.floor((now.getTime() - dob.getTime()) / 86_400_000);
}

// The label, or null when there is nothing true to write. A height mark with
// no age means nothing, so the component simply does not render: no filler
// state, no generic string.
export function useGrowthMarkLabel(): string | null {
  const t = useTranslations("agent");
  const { profiles, activeId } = useActiveProfile();
  const active: Profile | undefined =
    profiles.find((p) => p.id === activeId) ?? undefined;
  if (!active?.date_of_birth || !active.display_name) return null;
  const now = new Date();
  const months = monthsSince(active.date_of_birth, now);
  if (months === null) return null;
  const name = active.display_name;
  if (months >= 1) return t("growthMarkMonths", { name, months });
  const days = daysSince(active.date_of_birth, now);
  if (days === null) return null;
  return t("growthMarkDays", { name, days });
}
