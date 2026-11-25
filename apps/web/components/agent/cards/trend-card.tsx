"use client";
import type { AgentCard } from "@/lib/agent-types";
import type { CardActionHandler } from "./card-renderer";

// What she noted, drawn (agent/diary, 2026-11-21): a total per day as bars,
// readings (a temperature, a weight) as a line spaced by the calendar. Every
// label and number arrives formatted by the API, in her language, so this only
// draws. Bars start at zero, and a day with nothing noted has no bar at all:
// not noted is not zero. The answer above the card carries the same numbers
// as text; the chart is the trend at a glance, and screen readers get the
// points as one label.
type Point = { label: string; value: number; text: string; x?: number };

export function TrendCard({ card }: { card: AgentCard; onAction: CardActionHandler }) {
  const p = card.payload as { title: string; unit: string; style: string; points: Point[] };
  const points = (p.points ?? []).filter((pt) => Number.isFinite(pt.value));
  if (points.length < 2) return null;
  const last = points[points.length - 1];
  const label = `${p.title}: ${points.map((pt) => `${pt.label} ${pt.text}`).join(", ")}`;
  return (
    <figure data-testid="trend-card" data-style={p.style} className="ad-card ad-rise p-4">
      <figcaption className="ad-eyebrow">{p.title}</figcaption>
      <div role="img" aria-label={label} className="mt-3">
        {p.style === "bars" ? <Bars points={points} /> : <Line points={points} />}
      </div>
      <div aria-hidden className="mt-2 flex items-baseline justify-between gap-3 text-xs text-ink-faint">
        <span>{points[0].label}</span>
        <span className="font-medium text-ink">
          {last.label} · {last.text}
        </span>
      </div>
    </figure>
  );
}

function Bars({ points }: { points: Point[] }) {
  const max = Math.max(...points.map((pt) => pt.value)) || 1;
  return (
    <div className="flex h-24 items-end gap-1">
      {points.map((pt, i) => (
        <div
          key={i}
          title={`${pt.label} · ${pt.text}`}
          className={`min-w-[3px] flex-1 rounded-t-sm ${
            i === points.length - 1 ? "bg-primary-text" : "bg-primary-text/35"
          }`}
          style={{ height: `${Math.max((pt.value / max) * 100, 3)}%` }}
        />
      ))}
    </div>
  );
}

function Line({ points }: { points: Point[] }) {
  const values = points.map((pt) => pt.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // Some air above and below, so 38,2 to 38,9 °C does not fill the box like a
  // climb from 36 to 40.
  const pad = Math.max((hi - lo) * 0.25, 0.2);
  const min = lo - pad;
  const max = hi + pad;
  const timed = points.every((pt) => typeof pt.x === "number");
  const span = timed ? (points[points.length - 1].x as number) - (points[0].x as number) : 0;
  const xy = points.map((pt, i) => ({
    x: timed && span > 0
      ? (((pt.x as number) - (points[0].x as number)) / span) * 100
      : (i / (points.length - 1)) * 100,
    y: 100 - ((pt.value - min) / (max - min)) * 100,
  }));
  return (
    <div className="relative mx-1 h-24 text-primary-text">
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full overflow-visible"
        aria-hidden
      >
        <polyline
          points={xy.map((pt) => `${pt.x},${pt.y}`).join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {xy.map((pt, i) => (
        <span
          key={i}
          aria-hidden
          className={`absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current ${
            i === xy.length - 1 ? "" : "opacity-50"
          }`}
          style={{ left: `${pt.x}%`, top: `${pt.y}%` }}
        />
      ))}
    </div>
  );
}
