"""What the AI providers cost: today, the last 7 days and this month, against 200 $.

Read-only. It runs one read-only transaction on usage_counters (services/usage)
and prices it with the list prices of services/usage_prices, so the figures
are an ESTIMATE at list price, not the invoice. Calls of the golden gate
(surface `golden`) and of test traffic (surface `qa`: X-AdelIA-QA requests and
scripts/conversation_battery.py, counted since 2026-11-10) are shown apart and
never counted as real use nor in the month's projection; models
without an official price are named with their calls instead of priced at a
guess. Santiago's question of 2026-11-08: where do the ~200 $ a month of
Anthropic go.

In the production container (from /app):

    .venv/bin/python scripts/usage_report.py               # text, then JSON
    .venv/bin/python scripts/usage_report.py --format json
    .venv/bin/python scripts/usage_report.py --budget 200 --today 2026-11-08

Days are UTC, like every counter (services/funnel.utc_today). Counting starts
the day the release with migration 0026 is deployed: before that there is
nothing to read.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import sys
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

from adelia.db import AsyncSessionLocal, engine  # noqa: E402
from adelia.models import UsageCounter  # noqa: E402
from adelia.services.funnel import utc_today  # noqa: E402
from adelia.services.usage import COUNTERS  # noqa: E402
from adelia.services.usage_prices import (  # noqa: E402
    ANTHROPIC_PRICING,
    MISTRAL_PRICING,
    OPENAI_PRICING,
    READ_ON,
    estimate_usd,
    unpriced_reason,
)

DEFAULT_BUDGET_USD = 200.0
GOLDEN = "golden"
QA = "qa"


@asynccontextmanager
async def read_only_session() -> AsyncIterator[Any]:
    """A session whose transaction Postgres refuses to write in."""
    async with AsyncSessionLocal() as session:
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        try:
            yield session
        finally:
            await session.rollback()


async def fetch_rows(start: date, end: date) -> list[dict[str, Any]]:
    """Every counter row between start and end, both included."""
    async with read_only_session() as session:
        result = await session.execute(
            sa.select(UsageCounter).where(UsageCounter.day >= start, UsageCounter.day <= end)
        )
        return [
            {c: getattr(row, c) for c in UsageCounter.__table__.columns.keys()}
            for row in result.scalars().all()
        ]


def _windows(today: date) -> dict[str, tuple[date, date]]:
    return {
        "today": (today, today),
        "last_7_days": (today - timedelta(days=6), today),
        "month_to_date": (today.replace(day=1), today),
    }


def _period(rows: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    inside = [r for r in rows if start <= r["day"] <= end]
    models: dict[tuple[str, str], dict[str, Any]] = {}
    by_surface: dict[str, float] = {}
    apart = {GOLDEN: {"calls": 0, "estimated_usd": 0.0}, QA: {"calls": 0, "estimated_usd": 0.0}}
    for r in inside:
        usd = estimate_usd(r["provider"], r["model"], r)
        if r["surface"] in apart:
            bucket = apart[r["surface"]]
            bucket["calls"] += r["calls"]
            bucket["estimated_usd"] = round(bucket["estimated_usd"] + (usd or 0), 6)
            continue
        entry = models.setdefault(
            (r["provider"], r["model"]),
            {"provider": r["provider"], "model": r["model"], **{n: 0 for n in COUNTERS},
             "estimated_usd": None if usd is None else 0.0},
        )
        for name in COUNTERS:
            entry[name] += r[name]
        if usd is not None:
            entry["estimated_usd"] = round(entry["estimated_usd"] + usd, 6)
            by_surface[r["surface"]] = round(by_surface.get(r["surface"], 0.0) + usd, 6)

    priced = [m for m in models.values() if m["estimated_usd"] is not None]
    priced.sort(key=lambda m: -m["estimated_usd"])
    by_provider: dict[str, float] = {}
    for m in priced:
        by_provider[m["provider"]] = round(by_provider.get(m["provider"], 0.0)
                                           + m["estimated_usd"], 6)
    unpriced = [
        {"provider": m["provider"], "model": m["model"], "calls": m["calls"],
         "input_tokens": m["input_tokens"], "output_tokens": m["output_tokens"],
         "pages": m["pages"], "audio_seconds": m["audio_seconds"],
         "reason": unpriced_reason(m["provider"], m["model"])}
        for m in models.values() if m["estimated_usd"] is None
    ]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "real": {
            "estimated_usd": round(sum(m["estimated_usd"] for m in priced), 6),
            "calls": sum(m["calls"] for m in models.values()),
            "by_provider": by_provider,
            "by_surface": dict(sorted(by_surface.items(), key=lambda kv: -kv[1])),
            "by_model": priced,
        },
        "golden": apart[GOLDEN],
        "qa": apart[QA],
        "unpriced": unpriced,
    }


def build_report(rows: list[dict[str, Any]], *, today: date, budget_usd: float) -> dict:
    """The three periods, the month's projection and the budget, from counter rows."""
    periods = {name: _period(rows, *window) for name, window in _windows(today).items()}
    month = periods["month_to_date"]["real"]
    days_elapsed = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    def project(usd: float) -> float:
        return round(usd / days_elapsed * days_in_month, 6)

    projected = project(month["estimated_usd"])
    anthropic_projected = project(month["by_provider"].get("anthropic", 0.0))
    return {
        "today": today.isoformat(),
        "budget_usd": budget_usd,
        "basis": "list prices, standard tier; an estimate, not the invoice; UTC days",
        "prices": {
            "read_on": READ_ON.isoformat(),
            "sources": [ANTHROPIC_PRICING, MISTRAL_PRICING, OPENAI_PRICING],
        },
        "periods": periods,
        "month_projection": {
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "real_usd_so_far": month["estimated_usd"],
            "projected_usd": projected,
            "anthropic_usd_so_far": month["by_provider"].get("anthropic", 0.0),
            "anthropic_projected_usd": anthropic_projected,
            "share_of_budget": round(projected / budget_usd, 4) if budget_usd else None,
        },
    }


def _usd(value: float) -> str:
    return f"{value:,.2f} $"


def render_text(report: dict) -> str:
    """The report for a person, in Spanish: Santiago reads it."""
    titles = {"today": "Hoy", "last_7_days": "Últimos 7 días", "month_to_date": "Mes en curso"}
    lines = [
        f"Gasto en IA de AdelIA, {report['today']} (días UTC)",
        f"Estimación a precio de lista leído el {report['prices']['read_on']}; "
        "la factura del proveedor manda.",
        "",
    ]
    for key, title in titles.items():
        p = report["periods"][key]
        real = p["real"]
        lines.append(f"{title} ({p['from']} a {p['to']}): {_usd(real['estimated_usd'])} "
                     f"en {real['calls']} llamadas")
        for provider, usd in real["by_provider"].items():
            lines.append(f"  {provider}: {_usd(usd)}")
        for m in real["by_model"]:
            lines.append(
                f"    {m['provider']}/{m['model']}: {_usd(m['estimated_usd'])}, "
                f"{m['calls']} llamadas, {m['input_tokens']:,} entrada, "
                f"{m['output_tokens']:,} salida, {m['cache_read_tokens']:,} caché leída, "
                f"{m['cache_write_tokens']:,} caché escrita, {m['pages']:,} páginas")
        if real["by_surface"]:
            lines.append("  por función: " + ", ".join(
                f"{s} {_usd(v)}" for s, v in real["by_surface"].items()))
        for u in p["unpriced"]:
            lines.append(
                f"  sin precio oficial: {u['provider']}/{u['model']}, {u['calls']} llamadas, "
                f"{u['input_tokens']:,} entrada, {u['output_tokens']:,} salida, "
                f"{u['pages']:,} páginas, {u['audio_seconds']:,} s de audio ({u['reason']})")
        if p["golden"]["calls"]:
            lines.append(f"  aparte, puerta golden: {p['golden']['calls']} llamadas, "
                         f"{_usd(p['golden']['estimated_usd'])}")
        if p["qa"]["calls"]:
            lines.append(f"  aparte, pruebas (QA): {p['qa']['calls']} llamadas, "
                         f"{_usd(p['qa']['estimated_usd'])}")
        lines.append("")
    proj = report["month_projection"]
    budget = report["budget_usd"]
    lines.append(
        f"Presupuesto: {_usd(budget)} al mes. Llevamos {_usd(proj['real_usd_so_far'])} en "
        f"{proj['days_elapsed']} de {proj['days_in_month']} días; a este ritmo, "
        f"{_usd(proj['projected_usd'])} al cierre"
        + (f" ({proj['share_of_budget'] * 100:.0f} % del presupuesto)."
           if proj["share_of_budget"] is not None else "."))
    lines.append(
        f"Solo Anthropic: {_usd(proj['anthropic_usd_so_far'])}, a este ritmo "
        f"{_usd(proj['anthropic_projected_usd'])} al cierre.")
    return "\n".join(lines)


async def gather(*, today: date, budget_usd: float) -> dict:
    windows = _windows(today)
    start = min(w[0] for w in windows.values())
    rows = await fetch_rows(start, today)
    return build_report(rows, today=today, budget_usd=budget_usd)


async def _run(args: argparse.Namespace) -> dict:
    try:
        return await gather(today=args.today or utc_today(), budget_usd=args.budget)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("text", "json", "both"), default="both")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                        help="monthly budget in USD (default 200)")
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="report as of this UTC day (YYYY-MM-DD); default today")
    args = parser.parse_args(argv)
    report = asyncio.run(_run(args))
    if args.format in ("text", "both"):
        print(render_text(report))
    if args.format in ("json", "both"):
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
