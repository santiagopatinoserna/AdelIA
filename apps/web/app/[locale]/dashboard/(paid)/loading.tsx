import { Baby } from "lucide-react";
import { getTranslations } from "next-intl/server";

// Shown during async data fetches across dashboard routes — a calm branded
// skeleton with a reassuring line, instead of a blank flash or bare spinner.
export default async function DashboardLoading() {
  const t = await getTranslations("dashboard");

  return (
    <main className="mx-auto max-w-5xl px-6 py-10" aria-busy="true">
      <div className="ad-rise flex flex-col items-center pt-6 text-center">
        <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
          <Baby className="h-7 w-7 animate-pulse" strokeWidth={1.8} aria-hidden="true" />
        </span>
        <p className="mt-4 text-sm text-ink-soft">{t("loadingSpace")}</p>
      </div>

      {/* Calm placeholder shapes so the layout doesn't jump when content lands. */}
      <div className="mt-9 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="ad-card flex items-center gap-3 px-5 py-4"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <span className="h-10 w-10 shrink-0 animate-pulse rounded-xl bg-line/60" />
            <span className="h-3.5 w-24 animate-pulse rounded-full bg-line/60" />
          </div>
        ))}
      </div>

      <div className="mt-7 grid grid-cols-2 gap-2.5 sm:grid-cols-4" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="ad-card flex items-center gap-2.5 bg-surface-2/40 px-3.5 py-3"
            style={{ animationDelay: `${(3 + i) * 60}ms` }}
          >
            <span className="h-4 w-4 shrink-0 animate-pulse rounded bg-line/50" />
            <span className="h-3 w-16 animate-pulse rounded-full bg-line/50" />
          </div>
        ))}
      </div>
    </main>
  );
}
