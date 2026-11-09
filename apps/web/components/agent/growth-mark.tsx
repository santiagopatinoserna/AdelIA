"use client";

import { useTranslations } from "next-intl";
import { todayInAppZone } from "@/lib/dates";
import type { Profile } from "@/lib/enrichment-types";
import { useActiveProfile } from "@/lib/profile-context";

// Her baby's age under the greeting, one quiet line of body text ("5 meses").
// It was a pencil mark on a door frame with "LUCÍA · 5 MESES" in amber small
// caps; on 2026-11-09 a mother said the panel had "demasiadas cosas" and it
// became plain text: one colour less, one icon less, and no second "Lucía"
// under "¿Cómo está Lucía?". The age comes from the active profile, and there
// is nothing to render without a date of birth or a name to greet.
export function GrowthMark({ label }: { label: string }) {
  return (
    <p className="mt-1 text-base text-ink-soft" data-testid="growth-mark">
      {label}
    </p>
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
  // Noon of today in Madrid, read with local getters like the date of birth:
  // the server (UTC) and the phone then count the same months and days, even
  // in the hour after midnight (lib/dates.ts).
  const now = new Date(`${todayInAppZone()}T12:00:00`);
  const months = monthsSince(active.date_of_birth, now);
  if (months === null) return null;
  const name = active.display_name;
  if (months >= 1) return t("growthMarkMonths", { name, months });
  const days = daysSince(active.date_of_birth, now);
  if (days === null) return null;
  return t("growthMarkDays", { name, days });
}
