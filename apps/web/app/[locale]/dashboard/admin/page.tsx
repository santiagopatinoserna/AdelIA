import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { analyticsSummary, type AnalyticsSummary } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import { Link } from "@/lib/navigation";

// Visitor analytics for the emails on ADMIN_EMAILS (decision of 2026-11-07).
// The API decides who is an admin: anyone else gets its 404, and this page
// answers notFound() so it does not even say that it exists. Outside the
// (paid) group, like Settings, so the paywall never stands in front of it.
//
// A server component with no client JavaScript: a phone reads it as a page.
// One measure per figure, in the primary ink, with the numbers written next
// to every bar; the tables are the figures' own accessible view.

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "admin" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

const PERIODS = [7, 30, 90] as const;
const TIME_ZONE = "Europe/Madrid";

export default async function AdminAnalyticsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ days?: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);
  const requested = Number((await searchParams).days);
  const days = (PERIODS as readonly number[]).includes(requested) ? requested : 30;
  const data = await analyticsSummary(days).catch(() => null);
  if (!data) notFound();

  const t = await getTranslations("admin");
  const number = new Intl.NumberFormat(locale);
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 });
  const dayLabel = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" });
  const timeLabel = new Intl.DateTimeFormat(locale, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE,
  });
  const clock = new Intl.DateTimeFormat(locale, {
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: TIME_ZONE,
  });
  const stepName = (step: string | null) => (step ? t(`steps.${step}` as "steps.payment") : "");
  const empty = data.totals.sessions === 0;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 pb-16 pt-6 md:px-6" data-testid="admin-analytics" data-track-private>
      <h1 className="font-display text-title text-ink">{t("title")}</h1>
      <p className="mt-2 max-w-prose text-[15px] leading-relaxed text-ink-soft">{t("intro")}</p>

      <nav className="mt-4 flex flex-wrap items-center gap-2" aria-label={t("title")}>
        {PERIODS.map((p) => (
          <Link
            key={p}
            href={`/dashboard/admin?days=${p}`}
            aria-current={p === days ? "page" : undefined}
            className={`ad-pill ${p === days ? "!border-primary-text font-semibold" : ""}`}
          >
            {t("period", { days: p })}
          </Link>
        ))}
        <a
          href={`/api/backend/analytics/summary?days=${days}`}
          className="ad-tap-inline ml-auto text-sm font-medium text-primary-text underline underline-offset-4"
        >
          <span>{t("json")}</span>
        </a>
      </nav>

      <dl className="mt-6 grid grid-cols-3 gap-3" data-testid="admin-totals">
        {(
          [
            ["visitors", data.totals.visitors],
            ["sessions", data.totals.sessions],
            ["pageviews", data.totals.pageviews],
          ] as const
        ).map(([key, value]) => (
          <div key={key} className="border-t border-line pt-2">
            <dt className="text-sm text-ink-soft">{t(key)}</dt>
            <dd className="mt-0.5 font-display text-2xl tabular-nums text-ink">{number.format(value)}</dd>
          </div>
        ))}
      </dl>

      {empty && <p className="mt-6 text-ink-soft">{t("empty")}</p>}

      <Section title={t("funnelTitle")} note={t("funnelNote")} testid="admin-funnel">
        <Funnel data={data} stepName={stepName} number={number} percent={percent} t={t} />
      </Section>

      <Section title={t("dailyTitle")} testid="admin-daily">
        <Daily data={data} number={number} dayLabel={dayLabel} t={t} />
      </Section>

      <Section title={t("sourcesTitle")} testid="admin-sources">
        <h3 className="text-base font-semibold text-ink">{t("referrers")}</h3>
        <Bars
          rows={data.sources.referrers.map((r) => ({
            label: r.domain ?? t("direct"),
            value: r.sessions,
          }))}
          number={number}
          unit={t("sessions")}
        />
        <h3 className="mt-6 text-base font-semibold text-ink">{t("utmTitle")}</h3>
        {data.sources.utm.length === 0 ? (
          <p className="mt-2 text-sm text-ink-soft">{t("utmEmpty")}</p>
        ) : (
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {data.sources.utm.map((u, i) => (
              <li key={i} className="py-3">
                <p className="break-words font-medium text-ink">
                  {[u.campaign, u.content].filter(Boolean).join(" / ") || u.source || "?"}
                </p>
                <p className="mt-0.5 break-words text-sm text-ink-soft">
                  {[u.source, u.medium].filter(Boolean).join(" / ")}
                </p>
                <p className="mt-1 text-sm text-ink">
                  <span className="tabular-nums">{t("sessionCount", { count: u.sessions })}</span>
                  {u.deepest && (
                    <>
                      {". "}
                      {t("deepest")}: <strong className="font-semibold">{stepName(u.deepest)}</strong>
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("clicksTitle")} testid="admin-clicks">
        <Clicks data={data} number={number} t={t} />
      </Section>

      <Section title={t("recentTitle")} testid="admin-recent">
        <ul className="divide-y divide-line border-y border-line">
          {data.recent_sessions.map((s) => (
            <li key={s.session}>
              <details className="group py-1">
                <summary className="flex min-h-11 cursor-pointer list-none flex-wrap items-baseline gap-x-2 py-2 text-[15px] text-ink">
                  <span className="tabular-nums font-medium">{timeLabel.format(new Date(s.started_at))}</span>
                  <span className="text-ink-soft">
                    {[
                      s.utm_campaign ?? s.utm_source ?? s.referrer_domain ?? t("direct"),
                      s.device,
                      s.country,
                      s.locale,
                    ].filter(Boolean).join(", ")}
                  </span>
                  <span className="ml-auto text-sm tabular-nums text-ink-soft">{s.events.length}</span>
                </summary>
                <ol className="mb-3 ml-1 border-l-2 border-line pl-3">
                  {s.events.map((e, i) => (
                    <li key={i} className="py-1 text-sm leading-snug">
                      <span className="mr-2 tabular-nums text-ink-soft">{clock.format(new Date(e.at))}</span>
                      {e.type === "step" ? (
                        <strong className="font-semibold text-primary-text">{stepName(e.step)}</strong>
                      ) : (
                        <span className="text-ink">
                          {e.type === "pageview" && `${t("typePageview")} `}
                          {e.type === "click" && `${t("typeClick")} ${e.element ?? ""} `}
                          {e.type === "scroll" && `${t("typeScroll")} ${e.depth}% `}
                        </span>
                      )}{" "}
                      <span className="break-all text-ink-soft">{e.path}</span>
                    </li>
                  ))}
                </ol>
              </details>
            </li>
          ))}
        </ul>
      </Section>

      <Section title={t("consentTitle")} testid="admin-consent">
        <dl className="grid grid-cols-3 gap-3">
          {(["accepted", "rejected", "withdrawn"] as const).map((k) => (
            <div key={k} className="border-t border-line pt-2">
              <dt className="text-sm text-ink-soft">{t(k)}</dt>
              <dd className="mt-0.5 font-display text-xl tabular-nums text-ink">{number.format(data.consent[k])}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title={t("countersTitle")} testid="admin-counters">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[20rem] text-sm">
            <thead>
              <tr className="text-left text-ink-soft">
                <th className="py-1.5 pr-2 font-medium">{t("day")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("counterVisit")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("counterStart")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("counterSignup")}</th>
                <th className="py-1.5 text-right font-medium">{t("counterActivation")}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums text-ink">
              {data.counters
                .filter((r) => r.visit || r.start || r.signup || r.activation)
                .map((r) => (
                  <tr key={r.day} className="border-t border-line">
                    <td className="py-1.5 pr-2">{dayLabel.format(new Date(r.day))}</td>
                    <td className="py-1.5 pr-2 text-right">{number.format(r.visit)}</td>
                    <td className="py-1.5 pr-2 text-right">{number.format(r.start)}</td>
                    <td className="py-1.5 pr-2 text-right">{number.format(r.signup)}</td>
                    <td className="py-1.5 text-right">{number.format(r.activation)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Section>
    </main>
  );
}

type T = Awaited<ReturnType<typeof getTranslations<"admin">>>;

function Section({
  title, note, testid, children,
}: { title: string; note?: string; testid: string; children: React.ReactNode }) {
  return (
    <section className="mt-10" data-testid={testid}>
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>
      {note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{note}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** The figure of the page: each step as a bar against the first step. */
function Funnel({
  data, stepName, number, percent, t,
}: {
  data: AnalyticsSummary;
  stepName: (s: string | null) => string;
  number: Intl.NumberFormat;
  percent: Intl.NumberFormat;
  t: T;
}) {
  const max = Math.max(1, ...data.funnel.map((r) => r.visitors));
  return (
    <ol className="space-y-3">
      {data.funnel.map((row) => (
        <li key={row.step} data-step={row.step}>
          <div className="flex items-baseline justify-between gap-3 text-[15px]">
            <span className="text-ink">{stepName(row.step)}</span>
            <span className="shrink-0 tabular-nums font-semibold text-ink">{number.format(row.visitors)}</span>
          </div>
          <div className="mt-1 h-2.5 rounded-full bg-line/60" aria-hidden>
            <div
              className="h-2.5 rounded-full bg-primary"
              style={{ width: `${(row.visitors / max) * 100}%`, minWidth: row.visitors ? "4px" : 0 }}
              title={`${stepName(row.step)}: ${number.format(row.visitors)}`}
            />
          </div>
          {row.rate_from_previous !== null && (
            <p className="mt-0.5 text-xs tabular-nums text-ink-soft">
              {t("ofPrevious", { rate: percent.format(row.rate_from_previous) })}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function Daily({
  data, number, dayLabel, t,
}: { data: AnalyticsSummary; number: Intl.NumberFormat; dayLabel: Intl.DateTimeFormat; t: T }) {
  const max = Math.max(1, ...data.daily.map((d) => d.visitors));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[20rem] text-sm">
        <thead>
          <tr className="text-left text-ink-soft">
            <th className="py-1.5 pr-2 font-medium">{t("day")}</th>
            <th className="w-full py-1.5 pr-2 font-medium">{t("visitors")}</th>
            <th className="py-1.5 pr-2 text-right font-medium">{t("sessions")}</th>
            <th className="py-1.5 text-right font-medium">{t("pageviews")}</th>
          </tr>
        </thead>
        <tbody className="tabular-nums text-ink">
          {data.daily.map((d) => (
            <tr key={d.day} className="border-t border-line">
              <td className="whitespace-nowrap py-1.5 pr-2">{dayLabel.format(new Date(d.day))}</td>
              <td className="py-1.5 pr-2">
                <span className="flex items-center gap-2">
                  <span
                    className="h-2 rounded-full bg-primary"
                    style={{ width: `${(d.visitors / max) * 70}%`, minWidth: d.visitors ? "4px" : 0 }}
                    title={`${number.format(d.visitors)}`}
                    aria-hidden
                  />
                  <span>{number.format(d.visitors)}</span>
                </span>
              </td>
              <td className="py-1.5 pr-2 text-right">{number.format(d.sessions)}</td>
              <td className="py-1.5 text-right">{number.format(d.pageviews)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Bars({
  rows, number, unit,
}: { rows: { label: string; value: number }[]; number: Intl.NumberFormat; unit: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="mt-2 space-y-2.5">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-[15px]">
            <span className="min-w-0 break-all text-ink">{r.label}</span>
            <span className="shrink-0 tabular-nums text-ink" title={unit}>{number.format(r.value)}</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-line/60" aria-hidden>
            <div className="h-2 rounded-full bg-primary" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Clicks({ data, number, t }: { data: AnalyticsSummary; number: Intl.NumberFormat; t: T }) {
  const byPath = new Map<string, { element: string | null; clicks: number }[]>();
  for (const c of data.clicks) {
    const list = byPath.get(c.path) ?? [];
    if (list.length < 6) list.push({ element: c.element, clicks: c.clicks });
    byPath.set(c.path, list);
  }
  if (byPath.size === 0) return <p className="text-sm text-ink-soft">{t("empty")}</p>;
  return (
    <div className="space-y-5">
      {[...byPath.entries()].map(([path, list]) => (
        <div key={path}>
          <h3 className="break-all text-base font-semibold text-ink">{path}</h3>
          <ul className="mt-1 divide-y divide-line">
            {list.map((c, i) => (
              <li key={i} className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
                <span className="min-w-0 break-words text-ink">{c.element ?? "?"}</span>
                <span className="shrink-0 tabular-nums text-ink-soft" title={t("clicks")}>
                  {number.format(c.clicks)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
