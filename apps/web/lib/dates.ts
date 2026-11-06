// Dates she reads, formatted the same on the server and in the browser.
//
// A formatter without a time zone uses the zone of the machine it runs on:
// the container renders in UTC, her phone in Europe/Madrid. Around midnight
// (and for every hour, wherever the time is shown) the two texts differ and
// React throws #418 during hydration; production did on /dashboard/briefings
// and /dashboard/settings at 01:05 in Madrid (prod journey 2026-11-06). Every
// date in the app goes through here, in the zone the API already reads "today"
// in (agent/graph.LOCAL_TZ, settings.diary_reminder_tz).

export const APP_TIME_ZONE = "Europe/Madrid";

type Style = "long" | "medium" | "dateTime";

const OPTIONS: Record<Style, Intl.DateTimeFormatOptions> = {
  long: { dateStyle: "long" },
  medium: { dateStyle: "medium" },
  dateTime: { dateStyle: "medium", timeStyle: "short" },
};

// An instant (an ISO timestamp from the API), shown in APP_TIME_ZONE.
export function formatInstant(iso: string | Date, locale: string, style: Style = "dateTime"): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat(locale, { ...OPTIONS[style], timeZone: APP_TIME_ZONE }).format(date);
}

// A calendar day with no time ("2026-08-27", a diary date, a date of birth).
// It is not an instant, so no zone may move it: read and print it in UTC.
export function formatDay(ymd: string, locale: string, style: Exclude<Style, "dateTime"> = "long"): string {
  return new Intl.DateTimeFormat(locale, { ...OPTIONS[style], timeZone: "UTC" }).format(
    new Date(`${ymd.slice(0, 10)}T12:00:00Z`),
  );
}

// Today's calendar day in APP_TIME_ZONE, as "YYYY-MM-DD".
export function todayInAppZone(now: Date = new Date()): string {
  // en-CA prints ISO order (2026-11-06).
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: APP_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
}
