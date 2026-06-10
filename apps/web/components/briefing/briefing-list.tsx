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
    return <p className="text-slate-500">{t("briefing.listEmpty")}</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {briefings.map((b) => (
        <li key={b.id}>
          <Link
            href={`/dashboard/briefings/${b.id}`}
            className="flex items-center justify-between rounded border border-slate-200 bg-white p-3 hover:bg-slate-50"
          >
            <div>
              <div className="font-medium">
                {t(`briefing.specialty.${b.target_specialty}`)}
                {b.is_stale && (
                  <span className="ml-2 rounded bg-yellow-100 px-1.5 py-0.5 text-xs text-yellow-800">
                    stale
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500">
                {t("briefing.createdAt")}
                {new Date(b.created_at).toLocaleString()}
              </div>
            </div>
            <span className="text-xs uppercase text-slate-600">
              {t(`briefing.status.${b.status}`)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
