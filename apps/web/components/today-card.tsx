import { getTranslations } from "next-intl/server";

import type { TodayItem } from "@/lib/api-endpoints";

// "Hoy con Nora": what is due today, in one glance, at the top of the panel
// home (vision note 2026-10-22). Read-only and computed by the API from her
// own tables (vaccination calendar, observations, the last stored plan); the
// web draws the lines it gets and adds nothing. No items, no card: an empty
// card would be the filler the home is designed not to have.
//
// Server component: the page fetches GET /today next to the rest of the
// server-side reads, so the card arrives in the first HTML and never pops in
// after the greeting. The region is named after the heading so a screen
// reader lands on "Hoy con Nora", not on "region".
export async function TodayCard({
  name,
  items,
}: {
  name: string | null;
  items: TodayItem[];
}) {
  if (items.length === 0) return null;
  const t = await getTranslations("today");
  const title = name ? t("titleWithName", { name }) : t("title");
  return (
    <section aria-labelledby="today-card-title" className="ad-card ad-rise mb-4 p-4" data-testid="today-card">
      <h2 id="today-card-title" className="ad-eyebrow">
        {title}
      </h2>
      <ul className="mt-2 flex flex-col gap-1.5">
        {items.map((item) => (
          <li
            key={item.kind}
            data-kind={item.kind}
            className={`text-[0.9375rem] leading-snug ${
              item.tone === "warn" ? "text-error-text" : "text-ink"
            }`}
          >
            {item.text}
          </li>
        ))}
      </ul>
    </section>
  );
}
