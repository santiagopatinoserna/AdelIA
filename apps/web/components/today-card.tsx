import { useTranslations } from "next-intl";
import { Bookmark, Syringe, Thermometer } from "lucide-react";

import type { TodayItem } from "@/lib/api-endpoints";

// "Hoy con Nora": what is due today, in one glance, at the top of the panel
// home (vision note 2026-10-22). Read-only and computed by the API from her
// own tables (vaccination calendar, observations, the last stored plan); the
// web draws the lines it gets and adds nothing. No items, no card: an empty
// card would be the filler the home is designed not to have.
//
// The page fetches GET /today next to the rest of the server-side reads, so
// the card arrives in the first HTML and never pops in after the greeting.
// Not async and no server-only import: when she picks another child,
// components/today-follows-child draws the same card in the browser from the
// new child's /today, with the same markup. The region is named after the
// heading so a screen reader lands on "Hoy con Nora", not on "region".
export function TodayCard({
  name,
  items,
}: {
  name: string | null;
  items: TodayItem[];
}) {
  const t = useTranslations("today");
  if (items.length === 0) return null;
  const title = name ? t("titleWithName", { name }) : t("title");
  // The most useful block of the home, so it gets a real heading, not the
  // 11 px eyebrow it had; a due vaccine is a reminder, in the warning colour,
  // not the error red of an emergency (AUDITORIA_UX.md, problems 6 and 7).
  return (
    <section aria-labelledby="today-card-title" className="ad-card ad-rise mb-5 p-4" data-testid="today-card">
      <h2 id="today-card-title" className="font-sans text-lg font-semibold leading-snug text-ink">
        {title}
      </h2>
      <ul className="mt-1 flex flex-col divide-y divide-line">
        {items.map((item) => {
          const Icon = ICONS[item.kind] ?? Bookmark;
          return (
            <li
              key={item.kind}
              data-kind={item.kind}
              className={`flex items-start gap-3 py-2.5 text-base leading-snug last:pb-0 ${
                item.tone === "warn" ? "text-warning-text" : "text-ink"
              }`}
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={1.9} aria-hidden />
              {item.text}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const ICONS = { vaccine: Syringe, observation: Thermometer, remember: Bookmark } as const;
