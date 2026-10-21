import { getTranslations } from "next-intl/server";
import { ChevronDown, FileText, FlaskConical, Mic, NotebookPen } from "lucide-react";

import type { DemoProfile } from "@/lib/demo-profile";

const ICONS = {
  report: FileText,
  lab: FlaskConical,
  consulta: Mic,
  diary: NotebookPen,
} as const;

/**
 * The fictional record, folded. It stays on the landing because it says WHO
 * the question is about and that the data is invented: the badge on the card,
 * the note under the name, and the banner the API itself writes. A demo of a
 * health product that looks like a real child's file is a liability.
 */
export async function DemoRecord({ profile }: { profile: DemoProfile | null }) {
  const t = await getTranslations("demo");
  return (
    <details className="group border-t border-line pt-3" data-testid="demo-record">
      {profile ? (
        <>
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden">
            <div className="min-w-0">
              <h2 className="font-display text-lg text-ink">
                {profile.baby_name}, {profile.age_label}
              </h2>
              <p className="text-sm text-ink-soft">{profile.record_note}</p>
            </div>
            <span className="ml-auto shrink-0 rounded-full border border-accent-tint-line bg-accent-tint px-2 py-0.5 text-[11px] font-semibold text-accent-text">
              {t("badge")}
            </span>
            <ChevronDown
              className="h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180"
              strokeWidth={2}
              aria-hidden
            />
          </summary>
          <p className="mt-4 text-sm leading-relaxed text-ink-soft">{profile.banner}</p>
          <p className="ad-eyebrow mt-6">{profile.record_title}</p>
          <ul className="mt-3 flex flex-col divide-y divide-line">
            {profile.items.map((item) => {
              const Icon = ICONS[item.kind] ?? FileText;
              return (
                <li key={item.title} className="py-3">
                  <div className="flex items-start gap-2.5">
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary-text" strokeWidth={2} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink">{item.title}</p>
                      <p className="mt-0.5 text-xs leading-relaxed text-ink-soft">
                        {item.meta} · {item.date}
                      </p>
                    </div>
                  </div>
                  <ul className="mt-2 flex flex-col gap-1 pl-7">
                    {item.lines.map((line) => (
                      <li key={line} className="text-sm leading-relaxed text-ink-soft">
                        {line}
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p className="text-sm leading-relaxed text-ink-soft">{t("recordUnavailable")}</p>
      )}
    </details>
  );
}
