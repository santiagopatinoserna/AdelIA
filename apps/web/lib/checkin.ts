// Check-in card of /dashboard/overview (the "panel that asks you things").
// Whether it shows, and which prompt, is decided on the SERVER from a cookie
// so the card is part of the first paint: deciding it in a client effect
// (localStorage) inserted it after hydration and pushed the whole page down
// (CLS 0.138 on a 390px phone, over the 0.1 threshold, for every returning
// user). Shared by the page (reads) and components/check-in-prompt (writes).
export const CHECKIN_COOKIE = "adelia_checkin";
export const CHECKIN_INTERVAL_MS = 3 * 24 * 60 * 60 * 1000; // ask again at most every 3 days

// Three high-intent rotations only: each pairs one clear action with its
// destination. More than three reads as a nag and dilutes the ask.
export const CHECKIN_PROMPTS = [
  { key: "upload", href: "/dashboard/upload" },
  { key: "weight", href: "/dashboard/questionnaire" },
  { key: "doubt", href: "/dashboard/chat" },
] as const;

// Cookie value: "<last ack, epoch ms>.<next prompt index>". Absent or
// garbled = never acknowledged, so the first prompt shows.
export function checkinIndexFromCookie(raw: string | undefined, now = Date.now()): number | null {
  const [last = 0, next = 0] = (raw ?? "").split(".").map((s) => Number.parseInt(s, 10) || 0);
  return now - last > CHECKIN_INTERVAL_MS ? next % CHECKIN_PROMPTS.length : null;
}

export function checkinCookie(nextIndex: number, now = Date.now()): string {
  return `${CHECKIN_COOKIE}=${now}.${nextIndex}; path=/; max-age=31536000; samesite=lax`;
}
