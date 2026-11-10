"""Provider usage is counted per call and never per person (audit 4.8's promise).

Ported from 6773d0b (Santiago's own session, 2026-11-03) and extended on
2026-11-08 when the counter was integrated. What is under test, in this order
of importance:

1. The table cannot hold anybody: its columns are a day, labels that describe
   the call, and integers.
2. A count can never break or delay the request it rides along with, and only
   the closed lists of labels are written.
3. The surface label follows the Task that set it and does not leak into
   another request or out of an inline briefing; a golden gate process is
   labelled `golden` whatever its code paths set.
4. Active accounts are derived from rows the product already keeps, guests
   excluded, so the mean cost per account needs no identifier here.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import ChatMessage, ChatSession, Document, UsageCounter, User
from adelia.services import usage
from adelia.workers.transcribe import _audio_seconds

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


@pytest.fixture
async def day():
    """A day of its own, far in the past, wiped before and after.

    usage_counters is global and the rest of the suite writes today's rows
    through the mocked providers, so these cases never read today.
    """
    the_day = date(2001, 1, 1) + timedelta(days=random.randrange(3000))

    async def _wipe():
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(UsageCounter).where(UsageCounter.day == the_day))
            await session.commit()

    await _wipe()
    yield the_day
    await _wipe()


@pytest.fixture(autouse=True)
def _no_pinned_surface(monkeypatch):
    """A developer may export ADELIA_USAGE_SURFACE; these cases assume none."""
    monkeypatch.delenv(usage.SURFACE_ENV, raising=False)


# --- 1. the shape ------------------------------------------------------------------


def test_the_table_has_no_column_that_could_hold_a_person():
    columns = set(UsageCounter.__table__.columns.keys())

    assert columns == {
        "day", "surface", "operation", "provider", "model",
        "calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
        "pages", "audio_seconds",
    }


def test_record_takes_numbers_and_labels_only():
    """No parameter of the writer can carry a text: a caller that tried to
    pass the question would get a TypeError, swallowed by count()."""
    import inspect

    params = set(inspect.signature(usage.record).parameters)

    assert params == {
        "operation", "provider", "model", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "pages", "audio_seconds", "surface", "day",
    }


# --- token readers -----------------------------------------------------------------


def test_anthropic_tokens_include_the_cache_fields():
    message = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=1200, output_tokens=80,
        cache_read_input_tokens=3000, cache_creation_input_tokens=500,
    ))

    assert usage.anthropic_tokens(message) == {
        "input_tokens": 1200, "output_tokens": 80,
        "cache_read_tokens": 3000, "cache_write_tokens": 500,
    }


def test_openai_style_tokens_split_the_cached_part_out_of_the_prompt():
    """Mistral and OpenAI count cached tokens INSIDE prompt_tokens; Anthropic
    counts them apart. Stored the Anthropic way, so a price per column is
    right for every provider."""
    mistral_reply = SimpleNamespace(usage=SimpleNamespace(
        prompt_tokens=50, completion_tokens=7,
        prompt_tokens_details=SimpleNamespace(cached_tokens=20),
    ))
    rest_payload = {"usage": {"prompt_tokens": 9, "completion_tokens": 3}}
    num_cached = {"usage": {"prompt_tokens": 100, "completion_tokens": 1, "num_cached_tokens": 40}}

    assert usage.openai_style_tokens(mistral_reply) == {
        "input_tokens": 30, "output_tokens": 7, "cache_read_tokens": 20,
    }
    assert usage.openai_style_tokens(rest_payload) == {
        "input_tokens": 9, "output_tokens": 3, "cache_read_tokens": 0,
    }
    assert usage.openai_style_tokens(num_cached) == {
        "input_tokens": 60, "output_tokens": 1, "cache_read_tokens": 40,
    }
    # A stream hands over the usage object of its last chunk directly.
    assert usage.openai_style_tokens(mistral_reply.usage)["output_tokens"] == 7


def test_a_test_double_counts_no_tokens():
    """int(MagicMock()) is 1: without the type check every mocked call in the
    suite would invent one token in and one out."""
    assert set(usage.anthropic_tokens(MagicMock()).values()) == {0}
    assert set(usage.openai_style_tokens(MagicMock()).values()) == {0}
    assert usage.openai_style_tokens(None) == {}
    assert usage.anthropic_tokens(SimpleNamespace(usage=None)) == {}


def test_audio_seconds_prefer_what_was_billed():
    segments = [{"start": 0.0, "end": 12.5}, {"start": 12.5, "end": 61.2}]

    assert _audio_seconds({"usage": {"prompt_audio_seconds": 63}}, segments) == 63
    assert _audio_seconds({}, segments) == 61.2
    assert _audio_seconds({"text": "hola"}, []) == 0


# --- 3. labels -----------------------------------------------------------------------


def test_an_unknown_surface_is_refused():
    with pytest.raises(ValueError):
        usage.set_surface("user-1234")
    with pytest.raises(ValueError):
        usage.in_surface("whatever")
    with pytest.raises(ValueError):
        with usage.surface("whatever"):
            pass
    with pytest.raises(ValueError):
        with usage.json_purpose("somebody's question"):
            pass


async def test_an_inline_briefing_hands_the_label_back_to_the_agent():
    """briefing_orchestrator.run is awaited inside the agent's turn; the
    agent's later calls must not be counted as briefing."""
    seen: list[str] = []

    @usage.in_surface("briefing")
    async def bake():
        seen.append(usage.current_surface())
        raise RuntimeError("the briefing failed")

    async def agent_turn():
        usage.set_surface("agent")
        with pytest.raises(RuntimeError):
            await bake()
        seen.append(usage.current_surface())

    await asyncio.create_task(agent_turn())

    assert seen == ["briefing", "agent"]


async def test_a_label_set_in_one_request_is_not_seen_by_another():
    started = asyncio.Event()
    labels: dict[str, str] = {}

    async def demo_request():
        usage.set_surface("demo")
        started.set()
        await asyncio.sleep(0)
        labels["demo"] = usage.current_surface()

    async def other_request():
        await started.wait()
        labels["other"] = usage.current_surface()

    await asyncio.gather(asyncio.create_task(demo_request()), asyncio.create_task(other_request()))

    assert labels == {"demo": "demo", "other": "other"}


def test_a_golden_gate_process_is_golden_whatever_its_paths_set(monkeypatch):
    """scripts/golden_gate.sh exports ADELIA_USAGE_SURFACE=golden: the corpus
    load, the set and the previews of a gate run are tests, not use, even when
    they pass through code that labels itself chat or corpus."""
    monkeypatch.setenv(usage.SURFACE_ENV, "golden")

    with usage.surface("chat"):
        assert usage.current_surface() == "golden"


def test_a_pinned_surface_outside_the_list_is_ignored(monkeypatch):
    monkeypatch.setenv(usage.SURFACE_ENV, "someone@example.com")

    with usage.surface("chat"):
        assert usage.current_surface() == "chat"


def test_the_gate_script_pins_the_golden_surface():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "scripts" / "golden_gate.sh").read_text()
    export = script.index("export ADELIA_USAGE_SURFACE=golden")

    # Before the first thing that can call a provider: the corpus load.
    assert export < script.index("from adelia.main import load_startup_corpora")


def test_the_json_helpers_default_to_route_and_take_a_purpose():
    assert usage.json_operation() == "route"
    with usage.json_purpose("record"):
        assert usage.json_operation() == "record"
    assert usage.json_operation() == "route"


# --- 2. count() never blocks and never raises ---------------------------------------------


async def test_count_returns_before_the_write_and_drain_finishes_it(monkeypatch):
    gate = asyncio.Event()
    written: list[tuple] = []

    async def slow_record(operation, provider, model, **kwargs):
        await gate.wait()
        written.append((operation, provider, model, kwargs["surface"]))

    monkeypatch.setattr(usage, "record", slow_record)

    with usage.surface("chat"):
        assert usage.count("chat", "mistral", "m", input_tokens=3) is None
    assert written == []

    gate.set()
    await usage.drain()

    assert written == [("chat", "mistral", "m", "chat")]


async def test_a_hung_write_is_cancelled_by_drain_not_waited_forever(monkeypatch):
    async def hung_record(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(usage, "record", hung_record)
    usage.count("embed", "mistral", "mistral-embed")

    assert await usage.drain(grace_s=0.05) == 1
    assert not [t for t in usage._PENDING if not t.done()]


async def test_count_swallows_a_bad_call_and_a_broken_scheduler(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="adelia.services.usage")

    usage.count("chat", "mistral", "m", question="¿Es normal que regurgite?")

    def broken(*args, **kwargs):
        raise RuntimeError("no loop")

    monkeypatch.setattr(usage, "_spawn", broken)
    usage.count("chat", "mistral", "m")

    assert "usage: could not count" in caplog.text
    assert "regurgite" not in caplog.text


async def test_too_many_pending_writes_drop_the_count_instead_of_queueing(monkeypatch):
    async def hung_record(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(usage, "record", hung_record)
    monkeypatch.setattr(usage, "MAX_PENDING", 2)
    for _ in range(5):
        usage.count("embed", "mistral", "mistral-embed")

    assert len([t for t in usage._PENDING if not t.done()]) == 2
    await usage.drain(grace_s=0.01)


# --- DB --------------------------------------------------------------------------------


@needs_pg
async def test_calls_are_summed_per_label_set(day):
    async def ingestion():
        usage.set_surface("ingestion")
        await usage.record("ocr", "anthropic", "claude-x", input_tokens=900, output_tokens=300,
                           cache_read_tokens=10, day=day)
        await usage.record("ocr", "anthropic", "claude-x", input_tokens=100, output_tokens=50,
                           cache_write_tokens=7, day=day)
        await usage.record("ocr", "mistral", "mistral-ocr", pages=4, day=day)

    await asyncio.create_task(ingestion())

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                sa.select(
                    UsageCounter.surface, UsageCounter.provider, UsageCounter.calls,
                    UsageCounter.input_tokens, UsageCounter.output_tokens,
                    UsageCounter.cache_read_tokens, UsageCounter.cache_write_tokens,
                    UsageCounter.pages,
                )
                .where(UsageCounter.day == day)
                .order_by(UsageCounter.provider)
            )
        ).all()

    assert rows == [
        ("ingestion", "anthropic", 2, 1000, 350, 10, 7, 0),
        ("ingestion", "mistral", 1, 0, 0, 0, 0, 4),
    ]


@needs_pg
async def test_count_writes_under_the_surface_of_the_moment_it_was_called(day, monkeypatch):
    monkeypatch.setattr(usage, "utc_today", lambda: day)

    with usage.surface("demo"):
        usage.count("chat", "anthropic", "claude-x", input_tokens=5, output_tokens=2)
    await usage.drain()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa.select(UsageCounter.surface, UsageCounter.calls).where(UsageCounter.day == day)
        )).all()
    assert rows == [("demo", 1)]


@needs_pg
async def test_an_unknown_label_is_logged_not_raised_and_not_written(day, caplog):
    await usage.record("whatever_the_caller_wants", "anthropic", "m", day=day)
    await usage.record("chat", "someone@example.com", "m", day=day)
    await usage.record("chat", "anthropic", "m", surface="user-42", day=day)

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(UsageCounter).where(UsageCounter.day == day)
        )
    assert count == 0
    assert "usage: could not record" in caplog.text


@needs_pg
async def test_active_accounts_come_from_rows_we_already_keep_and_skip_guests(day):
    noon = datetime.combine(day, time(12, 0), tzinfo=timezone.utc)
    uploader = await make_user()
    asker = await make_user()
    async with AsyncSessionLocal() as session:
        guest = User(email=f"guest-{uuid.uuid4().hex}@guest.invalid", is_guest=True)
        session.add(guest)
        await session.flush()
        docs = [
            Document(user_id=owner, source="web", mime_type="application/pdf",
                     s3_key=f"test/{uuid.uuid4()}.pdf", created_at=noon, processed_at=noon)
            for owner in (uploader, guest.id)
        ]
        chat = ChatSession(user_id=asker)
        session.add_all([*docs, chat])
        await session.flush()
        session.add_all([
            ChatMessage(session_id=chat.id, user_id=asker, role="user", content="?",
                        created_at=noon),
            ChatMessage(session_id=chat.id, user_id=asker, role="assistant", content=".",
                        created_at=noon),
        ])
        await session.commit()
        doc_ids, chat_id, guest_id = [d.id for d in docs], chat.id, guest.id
    await usage.record("chat", "anthropic", "claude-opus-5-5", input_tokens=1_000_000,
                       output_tokens=0, day=day)

    try:
        result = await usage.summary(1, today=day)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(Document).where(Document.id.in_(doc_ids)))
            await session.execute(sa.delete(ChatSession).where(ChatSession.id == chat_id))
            await session.execute(
                sa.delete(User).where(User.id.in_([uploader, asker, guest_id])))
            await session.commit()

    assert result["active_accounts"] == 2
    assert result["totals"] == [{
        "surface": "other", "operation": "chat", "provider": "anthropic",
        "model": "claude-opus-5-5", "calls": 1, "input_tokens": 1_000_000, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "pages": 0, "audio_seconds": 0,
        "estimated_usd": 4.0,
    }]
    assert result["estimated_usd"] == 4.0


@needs_pg
async def test_only_the_owner_reads_usage_and_everyone_else_gets_404(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    stranger = await make_user()
    owner_email = f"owner-{uuid.uuid4().hex[:8]}@godi.ai"
    async with AsyncSessionLocal() as session:
        owner = User(email=owner_email, subscription_status="active")
        session.add(owner)
        await session.commit()
        await session.refresh(owner)
        owner_id = owner.id
    monkeypatch.setattr(settings, "owner_email", owner_email)

    try:
        as_stranger = await client.get(
            "/funnel/usage", headers={"Authorization": f"Bearer {make_token(str(stranger))}"}
        )
        as_owner = await client.get(
            "/funnel/usage?days=7",
            headers={"Authorization": f"Bearer {make_token(str(owner_id))}"},
        )
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(User).where(User.id.in_([stranger, owner_id])))
            await session.commit()

    assert as_stranger.status_code == 404
    assert as_owner.status_code == 200
    assert set(as_owner.json()) == {
        "from", "to", "active_accounts", "totals", "daily", "estimated_usd", "unpriced", "qa",
    }


@needs_pg
async def test_a_guest_account_is_labelled_guest_and_anything_else_the_default(monkeypatch):
    """The agent and chat routers ask this once per turn. Their tests override
    get_current_user_id with ids that have no row; those, and a database that
    does not answer, get the default label, never an error."""
    paying = await make_user()
    async with AsyncSessionLocal() as session:
        guest = User(email=f"guest-{uuid.uuid4().hex}@guest.invalid", is_guest=True)
        session.add(guest)
        await session.commit()
        guest_id = guest.id

    try:
        assert await usage.surface_for_account(guest_id, "agent") == "guest"
        assert await usage.surface_for_account(paying, "agent") == "agent"
        assert await usage.surface_for_account(uuid.uuid4(), "chat") == "chat"

        def broken():
            raise RuntimeError("pool exhausted")

        monkeypatch.setattr(usage, "AsyncSessionLocal", broken)
        assert await usage.surface_for_account(guest_id, "chat") == "chat"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(User).where(User.id.in_([paying, guest_id])))
            await session.commit()


# --- the meter: what one run spent, read from the same count (2026-11-10) -------------


async def test_a_meter_sees_the_calls_counted_inside_it_and_in_its_child_tasks(monkeypatch):
    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    usage.count("embed", "mistral", "mistral-embed", input_tokens=1)
    with usage.metered() as meter:
        usage.count("chat", "anthropic", "claude-opus-5-5", input_tokens=1_000_000)

        async def _child():
            usage.count("embed", "mistral", "mistral-embed", input_tokens=1_000_000)

        await asyncio.create_task(_child())
    usage.count("embed", "mistral", "mistral-embed", input_tokens=1)
    await usage.drain()

    assert [(c["operation"], c["provider"], c["model"]) for c in meter.calls] == [
        ("chat", "anthropic", "claude-opus-5-5"), ("embed", "mistral", "mistral-embed")]
    assert meter.calls[0]["input_tokens"] == 1_000_000
    # Opus 5.5 at 4 $ per million input, mistral-embed at 0.10.
    assert meter.estimated_usd() == pytest.approx(4.1)
    assert meter.unpriced() == []


async def test_a_meter_counts_test_traffic_too_and_names_what_it_cannot_price(monkeypatch):
    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    from adelia import qa_traffic

    with usage.metered() as meter, qa_traffic.marked():
        usage.count("chat", "anthropic", "a-model-nobody-priced", output_tokens=10)
    await usage.drain()

    assert len(meter.calls) == 1 and meter.calls[0]["surface"] == "qa"
    assert meter.unpriced() == ["anthropic/a-model-nobody-priced"]
    assert meter.estimated_usd() == 0
    # The cap reads it at the dearest output price known (Opus 5.5, 20 $ per million).
    assert meter.capped_usd() == pytest.approx(10 * 20 / 1_000_000)


@needs_pg
async def test_the_summary_keeps_test_traffic_out_of_the_real_figure(day):
    await usage.record("chat", "anthropic", "claude-opus-5-5", input_tokens=1_000_000,
                       surface="agent", day=day)
    await usage.record("chat", "anthropic", "claude-opus-5-5", input_tokens=500_000,
                       surface="qa", day=day)

    out = await usage.summary(1, today=day)

    assert out["estimated_usd"] == pytest.approx(4.0)
    assert out["qa"] == {"calls": 1, "estimated_usd": pytest.approx(2.0)}
    assert {r["surface"] for r in out["totals"]} == {"agent", "qa"}
    # The daily trend is real use only.
    assert [d["estimated_usd"] for d in out["daily"]] == [pytest.approx(4.0)]
    assert [d["calls"] for d in out["daily"]] == [1]
