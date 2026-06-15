"use client";

import { Link } from "@/lib/navigation";
import { useTranslations } from "next-intl";

import type { BriefingOut } from "@/lib/briefing-types";

interface Props {
  briefings: BriefingOut[];
  locale: string;
}

export function BriefingList({ briefings, locale }: Props) {
  const t = useTranslations();
  if (briefings.length === 0) {
    return <p className="text-ink-soft">{t("briefing.listEmpty")}</p>;
  }
  return (
    <ul className="flex flex-col gap-2.5">
      {briefings.map((b) => (
        <li key={b.id}>
          <Link
            href={`/dashboard/briefings/${b.id}`}
            className="ad-card ad-card-hover flex items-center justify-between gap-3 p-4"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2 font-medium text-ink">
                {t(`briefing.specialty.${b.target_specialty}`)}
                {b.is_stale && (
                  <span className="rounded-md bg-honey-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-honey-600">
                    stale
                  </span>
                )}
              </div>
              <div className="mt-1 font-mono text-xs text-ink-faint">
                {t("briefing.createdAt")}
                {new Date(b.created_at).toLocaleString(locale)}
              </div>
            </div>
            <span className="ad-eyebrow shrink-0">
              {t(`briefing.status.${b.status}`)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
