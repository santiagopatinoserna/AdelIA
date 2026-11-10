"""What the AI providers cost, counted without knowing whose call it was.

Written on 2026-11-03 (6773d0b) and integrated on 2026-11-08, when Santiago
asked where the app's ~200 $ a month of Anthropic goes. Mistral credits are
prepaid with auto-recharge off, so a good campaign can also empty them in a day
and stop OCR, embeddings and transcription for everyone. The count follows the
funnel's privacy design (services/funnel, audit 4.8), because /privacidad
promises that our counters cannot say who you are or whether you came back:

* `count()` adds one call and its tokens, pages or audio seconds to a row of
  `usage_counters` keyed by (day, surface, operation, provider, model). Those
  labels describe the call. Nothing about the person, the baby or the text
  goes in, so there is no raw event table to leak and no query that can
  answer "how much did SHE cost?".
* `summary()` divides by active accounts derived at read time from rows we
  already keep (documents, chat messages, briefings), guests excluded, so
  the mean cost per active account needs no new identifier.

Never in the way of an answer (2026-11-08). 6773d0b awaited the write right
after each reply; on main that would put a database round trip inside the
route classifier's 2 s deadline, where a slow write turns the decision into the
`plan` fallback and changes what she reads. So `count()` only schedules the
write and returns; the write runs as its own task, bounded in time and in
number, and `drain()` finishes them before the engine is disposed (house rule).

The surface is a ContextVar set at the top of each entry point (a request
handler, a document task). asyncio gives every Task a copy of the context, so a
value set in one request is never seen by another, and the calls made deep
inside (embed_texts, the agent provider) inherit it without a parameter.
A golden gate process exports ADELIA_USAGE_SURFACE=golden, which pins the
label for the whole process, so tests never pass for use.

Test traffic is counted apart, not left out (2026-11-10). A request with
`X-AdelIA-QA: 1` (adelia/qa_traffic.py) used to be skipped here, so what the
smoke runs and a conversation battery with the model cost was invisible. Its
calls now go under the surface `qa`, whatever door they came through, and the
summary and scripts/usage_report.py show them next to the real use, never in
it. `metered()` lets one run read what its own calls cost from this same count
(scripts/conversation_battery.py stops at its budget with it).

Prices are not stored: services/usage_prices holds the list prices with their
source, and the summary and scripts/usage_report.py apply them when read.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from typing import Any, Iterator

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from adelia import qa_traffic
from adelia.db import AsyncSessionLocal
from adelia.models import Briefing, ChatMessage, Document, UsageCounter, User
from adelia.services.funnel import MAX_SUMMARY_DAYS, _utc_date, utc_today
from adelia.services import usage_prices
from adelia.services.usage_prices import estimate_usd, unpriced_reason

logger = logging.getLogger(__name__)

# Closed lists for the same reason as funnel.COUNTED_EVENTS: an open string
# column is an invitation to log something about the person in a label.
SURFACES = (
    "chat", "agent", "guest", "demo", "ingestion", "briefing", "corpus", "golden", "qa",
    "other",
)
#: Test traffic (adelia/qa_traffic.py): counted, but never as real use.
QA_SURFACE = "qa"
OPERATIONS = (
    "chat", "agent_step", "route", "record", "translate", "ocr", "extract", "embed",
    "transcribe", "summarize", "briefing_qa",
)
# What the JSON helpers of agent/route.py are doing for whoever borrowed them.
JSON_PURPOSES = ("route", "record", "translate")
PROVIDERS = ("anthropic", "mistral", "openai")
COUNTERS = (
    "calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "pages", "audio_seconds",
)

SURFACE_ENV = "ADELIA_USAGE_SURFACE"
# A write is one upsert. Past this it is waiting on a sick database, and the
# count is worth less than the connection it holds.
WRITE_TIMEOUT_S = 10.0
# Pending writes beyond this are dropped with a warning, never queued: a
# database that cannot keep up must not grow a backlog in memory.
MAX_PENDING = 256

_surface: ContextVar[str] = ContextVar("adelia_usage_surface", default="other")
_json_purpose: ContextVar[str] = ContextVar("adelia_usage_json_purpose", default="route")
_PENDING: set[asyncio.Task] = set()
_meter: ContextVar["Meter | None"] = ContextVar("adelia_usage_meter", default=None)


def _check_surface(name: str) -> None:
    if name not in SURFACES:
        raise ValueError(f"unknown usage surface: {name!r}")


def set_surface(name: str) -> None:
    """Label every provider call made from here on in this Task with `name`.

    Called once at the top of an entry point and never reset: the context
    belongs to that request's or that document's Task and dies with it.
    """
    _check_surface(name)
    _surface.set(name)


@contextmanager
def surface(name: str) -> Iterator[None]:
    """`name` inside the block, the caller's label after it.

    Not across the `yield` of an async generator: its steps can run in
    different contexts and the reset would fail.
    """
    _check_surface(name)
    token = _surface.set(name)
    try:
        yield
    finally:
        _surface.reset(token)


def in_surface(name: str):
    """Decorator: run a coroutine function under `name`, then restore the caller's.

    For work that has its own label but is also awaited inline by another
    surface: the agent's `generar_briefing` card runs briefing_orchestrator.run
    inside the agent's turn, and a plain set_surface there would label the rest
    of that turn "briefing". The label is kept on the wrapper as
    `__usage_surface__` so a test can read it without running the work.
    """
    _check_surface(name)

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            with surface(name):
                return await fn(*args, **kwargs)

        wrapper.__usage_surface__ = name
        return wrapper

    return decorate


async def surface_for_account(user_id: Any, default: str) -> str:
    """`guest` for a guest of the landing (migration 0025), else `default`.

    A guest's turns are the demo's cost, not a paying account's, so the agent
    and chat routers count them apart. One primary-key read before the answer
    streams; any failure gives `default`, never an error.
    """
    _check_surface(default)
    try:
        async with AsyncSessionLocal() as session:
            is_guest = await session.scalar(sa.select(User.is_guest).where(User.id == user_id))
    except Exception:  # noqa: BLE001 - a label is not worth a failed turn
        logger.warning("usage: could not read the account kind, counting as %s", default)
        return default
    return "guest" if is_guest else default


def current_surface() -> str:
    if qa_traffic.is_qa():
        return QA_SURFACE
    pinned = os.environ.get(SURFACE_ENV, "").strip()
    if pinned in SURFACES:
        return pinned
    return _surface.get()


@contextmanager
def json_purpose(name: str) -> Iterator[None]:
    """What route._complete_json is called for inside the block.

    The route classifier's plumbing is borrowed by the record extraction
    (agent/record.py) and the corpus translation (agent/corpus_query.py);
    6773d0b counted all three as "route". A context rather than a parameter
    because the tests replace _complete_json with fakes of a fixed signature.
    """
    if name not in JSON_PURPOSES:
        raise ValueError(f"unknown json purpose: {name!r}")
    token = _json_purpose.set(name)
    try:
        yield
    finally:
        _json_purpose.reset(token)


def json_operation() -> str:
    return _json_purpose.get()


# --- reading a provider's usage -----------------------------------------------------


def _count(value: Any) -> int:
    """A provider's usage field as a non-negative int, 0 when absent.

    Only real numbers count: the test doubles answer any attribute with a
    MagicMock, and int(MagicMock()) is 1, which would invent usage.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(round(value)))


def _field(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def anthropic_tokens(message: Any) -> dict[str, int]:
    """Tokens of an Anthropic Message. Cache reads and writes come apart from
    `input_tokens`, which is also how they are priced."""
    usage = _field(message, "usage")
    if usage is None:
        return {}
    return {
        "input_tokens": _count(_field(usage, "input_tokens")),
        "output_tokens": _count(_field(usage, "output_tokens")),
        "cache_read_tokens": _count(_field(usage, "cache_read_input_tokens")),
        "cache_write_tokens": _count(_field(usage, "cache_creation_input_tokens")),
    }


def openai_style_tokens(response_or_usage: Any) -> dict[str, int]:
    """Tokens of a Mistral or OpenAI chat or embedding reply.

    Both use `usage.prompt_tokens` / `usage.completion_tokens`, on the SDK
    object and on the raw JSON the REST calls (summarize) read. Accepts the
    reply or its `usage` directly, because a stream carries usage only on its
    last chunk. Their cached tokens are a part of prompt_tokens
    (`prompt_tokens_details.cached_tokens`, or `num_cached_tokens` in some
    Mistral replies), so they are moved out of input to price them apart.
    """
    usage = _field(response_or_usage, "usage")
    if usage is None:
        usage = response_or_usage
    if usage is None:
        return {}
    prompt = _count(_field(usage, "prompt_tokens"))
    cached = _count(_field(_field(usage, "prompt_tokens_details"), "cached_tokens")) or _count(
        _field(usage, "num_cached_tokens")
    )
    cached = min(cached, prompt)
    return {
        "input_tokens": prompt - cached,
        "output_tokens": _count(_field(usage, "completion_tokens")),
        "cache_read_tokens": cached,
    }


# --- a run's own meter ---------------------------------------------------------------


class Meter:
    """The calls counted inside one `metered()` block, priced at list price.

    A list in a ContextVar: the tasks the block creates (the route
    classifier's deadline, the embedding) get a copy of the context that
    points at the same list, so their calls are seen too. Nothing about the
    person is kept, only what count() receives.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def estimated_usd(self) -> float:
        return round(sum(
            estimate_usd(c["provider"], c["model"], c) or 0.0 for c in self.calls), 6)

    def capped_usd(self) -> float | None:
        """What a spending cap must assume: list price, and a model without one
        at the dearest known price (usage_prices.ceiling_usd). None when some
        call cannot be bounded at all."""
        total = 0.0
        for c in self.calls:
            usd = estimate_usd(c["provider"], c["model"], c)
            if usd is None:
                usd = usage_prices.ceiling_usd(c)
            if usd is None:
                return None
            total += usd
        return round(total, 6)

    def unpriced(self) -> list[str]:
        """provider/model of every call without an official price, once each."""
        out: list[str] = []
        for c in self.calls:
            if estimate_usd(c["provider"], c["model"], c) is None:
                name = f"{c['provider']}/{c['model']}"
                if name not in out:
                    out.append(name)
        return out


@contextmanager
def metered() -> Iterator[Meter]:
    """Every call counted inside the block is also added to the Meter it yields."""
    meter = Meter()
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def _to_meter(operation: str, provider: str, model: str | None, surface: str,
              counts: dict[str, int]) -> None:
    meter = _meter.get()
    if meter is None:
        return
    entry: dict[str, Any] = {"operation": operation, "provider": provider,
                             "model": model or "unknown", "surface": surface}
    entry.update({name: _count(counts.get(name, 0)) for name in COUNTERS if name != "calls"})
    entry["calls"] = 1
    meter.calls.append(entry)


# --- writing ------------------------------------------------------------------------


def _spawn(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return task


def _live_pending() -> list[asyncio.Task]:
    """Pending writes of a loop still running. A test's closed loop leaves
    tasks that will never finish; forgetting them keeps MAX_PENDING honest."""
    alive = []
    for task in list(_PENDING):
        if task.done() or task.get_loop().is_closed():
            _PENDING.discard(task)
        else:
            alive.append(task)
    return alive


def count(operation: str, provider: str, model: str | None, **counts: int) -> None:
    """Count one provider call, without waiting for the write. Never raises.

    Called right after the reply has arrived. The surface and the day are
    read now, in the caller's context, and the write is a task of its own:
    the answer never waits for the database, and a failed or hung write is a
    warning in the log, never an error she sees. Only the operation and the
    provider are logged, never the arguments. Calls made for test traffic
    (adelia/qa_traffic.py) are counted under `qa` (current_surface).
    """
    coro = None
    try:
        label = current_surface()
        _to_meter(operation, provider, model, label, counts)
        if len(_live_pending()) >= MAX_PENDING:
            logger.warning("usage: could not count %s/%s: too many pending writes",
                           operation, provider)
            return
        coro = record(operation, provider, model, surface=label, day=utc_today(), **counts)
        _spawn(coro)
    except Exception:  # noqa: BLE001 - a missed count is not an incident
        if coro is not None:
            coro.close()
        logger.warning("usage: could not count %s/%s", operation, provider)


async def record(
    operation: str,
    provider: str,
    model: str | None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    pages: int = 0,
    audio_seconds: int = 0,
    surface: str | None = None,
    day: date | None = None,
) -> None:
    """Add one call to the counter of this (day, surface, operation, provider, model).

    Never raises: every error is logged and swallowed, as funnel.bump_quietly
    does. One short session, opened after the provider has answered, so it is
    never held across network I/O.
    """
    try:
        label = surface or current_surface()
        _check_surface(label)
        if operation not in OPERATIONS:
            raise ValueError(f"unknown usage operation: {operation!r}")
        if provider not in PROVIDERS:
            raise ValueError(f"unknown usage provider: {provider!r}")
        values = {
            "calls": 1,
            "input_tokens": _count(input_tokens),
            "output_tokens": _count(output_tokens),
            "cache_read_tokens": _count(cache_read_tokens),
            "cache_write_tokens": _count(cache_write_tokens),
            "pages": _count(pages),
            "audio_seconds": _count(audio_seconds),
        }
        stmt = (
            pg_insert(UsageCounter)
            .values(
                day=day or utc_today(),
                surface=label,
                operation=operation,
                provider=provider,
                model=(model or "unknown")[:128],
                **values,
            )
            .on_conflict_do_update(
                index_elements=[
                    UsageCounter.day, UsageCounter.surface, UsageCounter.operation,
                    UsageCounter.provider, UsageCounter.model,
                ],
                set_={
                    name: getattr(UsageCounter, name) + value for name, value in values.items()
                },
            )
        )

        async def _write() -> None:
            async with AsyncSessionLocal() as session:
                await session.execute(stmt)
                await session.commit()

        await asyncio.wait_for(_write(), timeout=WRITE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - a missed count is not an incident
        logger.warning("usage: could not record %s/%s", operation, provider, exc_info=True)


async def drain(grace_s: float = 5.0) -> int:
    """Let the pending writes of this loop finish, cancel what outlives `grace_s`.

    Called by the lifespan before engine.dispose() (house rule: cancel and
    await background tasks first) and by the test suite after each test.
    Returns how many writes were pending.
    """
    loop = asyncio.get_running_loop()
    tasks = [t for t in _live_pending() if t.get_loop() is loop]
    if not tasks:
        return 0
    _, late = await asyncio.wait(tasks, timeout=grace_s)
    for task in late:
        task.cancel()
    if late:
        await asyncio.gather(*late, return_exceptions=True)
    return len(tasks)


# --- reading back -------------------------------------------------------------------


async def _active_accounts(start: date, end: date) -> int:
    """Accounts that uploaded, asked or made a briefing between start and end.

    Derived from rows the product keeps anyway, like the funnel's signups, so
    the mean cost per active account needs no identifier in usage_counters.
    Guests are left out: each one is born with Lucía's seeded documents, so
    every visitor of the landing would count as an active account.
    """
    def _in_window(column):
        day = _utc_date(column)
        return sa.and_(day >= start, day <= end)

    active = sa.union(
        sa.select(Document.user_id).where(_in_window(Document.created_at)),
        sa.select(ChatMessage.user_id)
        .where(ChatMessage.role == "user")
        .where(_in_window(ChatMessage.created_at)),
        sa.select(Briefing.user_id).where(_in_window(Briefing.created_at)),
    ).subquery()
    query = (
        sa.select(sa.func.count())
        .select_from(active)
        .join(User, User.id == active.c.user_id)
        .where(User.is_guest.is_(False))
    )
    async with AsyncSessionLocal() as session:
        value = await session.scalar(query)
    return int(value or 0)


async def summary(days: int = 30, *, today: date | None = None) -> dict[str, Any]:
    """Totals per (surface, operation, provider, model) over the last `days` days.

    One row per label set with the window's sums and its list-price estimate,
    biggest consumers first, the same totals per day and provider for the
    trend, and `active_accounts` for the window. Models without an official
    price are named in `unpriced` and left out of `estimated_usd`. Test
    traffic keeps its rows in `totals` (surface `qa`) but its cost is in `qa`,
    never in `estimated_usd` nor in the daily trend.
    """
    days = max(1, min(days, MAX_SUMMARY_DAYS))
    end = today or utc_today()
    start = end - timedelta(days=days - 1)
    labels = (
        UsageCounter.surface, UsageCounter.operation, UsageCounter.provider, UsageCounter.model,
    )
    sums = [sa.func.sum(getattr(UsageCounter, name)).label(name) for name in COUNTERS]
    window = (UsageCounter.day >= start, UsageCounter.day <= end)

    async with AsyncSessionLocal() as session:
        total_rows = (
            await session.execute(
                sa.select(*labels, *sums).where(*window).group_by(*labels)
            )
        ).all()
        daily_rows = (
            await session.execute(
                sa.select(UsageCounter.day, UsageCounter.provider, UsageCounter.model, *sums)
                .where(*window, UsageCounter.surface != QA_SURFACE)
                .group_by(UsageCounter.day, UsageCounter.provider, UsageCounter.model)
                .order_by(UsageCounter.day.desc(), UsageCounter.provider)
            )
        ).all()
    active = await _active_accounts(start, end)

    def _row(row, keys) -> dict[str, Any]:
        out = {key: getattr(row, key) for key in keys}
        out.update({name: int(getattr(row, name) or 0) for name in COUNTERS})
        return out

    unpriced: dict[str, str] = {}
    totals = []
    for r in total_rows:
        out = _row(r, ("surface", "operation", "provider", "model"))
        out["estimated_usd"] = estimate_usd(r.provider, r.model, out)
        if out["estimated_usd"] is None:
            unpriced[f"{r.provider}/{r.model}"] = unpriced_reason(r.provider, r.model)
        totals.append(out)
    totals.sort(key=lambda r: (-(r["estimated_usd"] or 0), -r["calls"]))

    by_day: dict[tuple[str, str], dict[str, Any]] = {}
    for r in daily_rows:
        key = (r.day.isoformat(), r.provider)
        entry = by_day.setdefault(
            key, {"day": key[0], "provider": r.provider, **{n: 0 for n in COUNTERS},
                  "estimated_usd": 0.0})
        row = _row(r, ())
        for name in COUNTERS:
            entry[name] += row[name]
        entry["estimated_usd"] = round(
            entry["estimated_usd"] + (estimate_usd(r.provider, r.model, row) or 0), 6)

    qa = [r for r in totals if r["surface"] == QA_SURFACE]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "active_accounts": active,
        "estimated_usd": round(
            sum(r["estimated_usd"] or 0 for r in totals if r["surface"] != QA_SURFACE), 6),
        "qa": {"calls": sum(r["calls"] for r in qa),
               "estimated_usd": round(sum(r["estimated_usd"] or 0 for r in qa), 6)},
        "unpriced": unpriced,
        "totals": totals,
        "daily": list(by_day.values()),
    }
