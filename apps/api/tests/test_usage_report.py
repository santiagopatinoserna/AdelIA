"""scripts/usage_report.py and the price table it reads (2026-11-08).

The report is what the supervisor runs in the production container to answer
"where do the ~200 $ a month go": today, the last 7 days and the month so far,
per provider and model, at list price, with the golden gate's calls kept out
of real use and the unpriced models named instead of guessed.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import UsageCounter
from adelia.services import usage, usage_prices
from tests.pg_gate import PG_AVAILABLE

API_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
import usage_report  # noqa: E402

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


def _row(day, surface, operation, provider, model, **counts):
    out = {"day": day, "surface": surface, "operation": operation, "provider": provider,
           "model": model}
    counts.setdefault("calls", 1)
    out.update({name: int(counts.get(name, 0)) for name in usage.COUNTERS})
    return out


# --- prices -------------------------------------------------------------------------


def test_every_default_model_is_priced_or_says_why_not():
    from adelia.config import Settings

    defaults = {(p, Settings.model_fields[f].default) for p, f in [
        ("anthropic", "agent_model"), ("anthropic", "anthropic_chat_model"),
        ("anthropic", "anthropic_extraction_model"), ("anthropic", "anthropic_briefing_model"),
        ("anthropic", "anthropic_routing_model"), ("anthropic", "anthropic_ocr_model"),
        ("mistral", "mistral_chat_model"), ("mistral", "mistral_extraction_model"),
        ("mistral", "mistral_briefing_model"), ("mistral", "mistral_routing_model"),
        ("mistral", "mistral_ocr_model"), ("mistral", "mistral_embed_model"),
        ("mistral", "mistral_stt_model"), ("openai", "openai_chat_model"),
        ("openai", "openai_stt_model"),
    ]}

    missing = defaults - set(usage_prices.PRICES) - set(usage_prices.UNPRICED)

    assert missing == set()
    assert not set(usage_prices.PRICES) & set(usage_prices.UNPRICED)


def test_every_price_names_an_official_source_read_on_a_date():
    official = (usage_prices.ANTHROPIC_PRICING, usage_prices.MISTRAL_PRICING,
                usage_prices.OPENAI_PRICING)

    assert usage_prices.READ_ON == date(2026, 11, 8)
    for key, price in usage_prices.PRICES.items():
        assert price.source in official, key
    for url in official:
        assert url.startswith("https://") and any(
            host in url for host in ("claude.com", "mistral.ai", "openai.com"))


def test_the_estimate_prices_each_column_apart():
    counts = {"input_tokens": 1_000_000, "output_tokens": 100_000,
              "cache_read_tokens": 1_000_000, "cache_write_tokens": 200_000}

    # Opus 5.5: 4 in, 20 out, 0.20 cache read, 5 cache write.
    assert usage_prices.estimate_usd("anthropic", "claude-opus-5-5", counts) == pytest.approx(
        4 + 2 + 0.2 + 1)
    assert usage_prices.estimate_usd("mistral", "mistral-ocr-latest", {"pages": 250}) == 1.0
    assert usage_prices.estimate_usd("mistral", "mistral-medium-latest", counts) is None
    assert "deprecated" in usage_prices.unpriced_reason("mistral", "mistral-medium-latest")


# --- the report, from rows ----------------------------------------------------------


def test_the_report_splits_today_the_week_and_the_month_and_keeps_golden_apart():
    today = date(2026, 11, 8)
    rows = [
        _row(today, "agent", "agent_step", "anthropic", "claude-sonnet-5",
             input_tokens=1_000_000, output_tokens=100_000),
        _row(today, "golden", "embed", "mistral", "mistral-embed", input_tokens=1_000_000),
        _row(today - timedelta(days=3), "chat", "chat", "anthropic", "claude-opus-5-5",
             input_tokens=500_000),
        _row(today - timedelta(days=7), "ingestion", "ocr", "mistral", "mistral-ocr-latest",
             pages=1000),
        _row(date(2026, 10, 31), "chat", "chat", "anthropic", "claude-opus-5-5",
             input_tokens=9_000_000),
        _row(today, "ingestion", "transcribe", "mistral", "voxtral-mini-latest",
             audio_seconds=600),
    ]

    report = usage_report.build_report(rows, today=today, budget_usd=200)

    periods = report["periods"]
    assert periods["today"]["from"] == periods["today"]["to"] == "2026-11-08"
    assert periods["today"]["real"]["estimated_usd"] == pytest.approx(3.0)  # 2 + 1
    assert periods["today"]["golden"] == {"calls": 1, "estimated_usd": pytest.approx(0.1)}
    assert periods["last_7_days"]["from"] == "2026-11-02"
    assert periods["last_7_days"]["real"]["estimated_usd"] == pytest.approx(5.0)
    assert periods["month_to_date"]["from"] == "2026-11-01"
    assert periods["month_to_date"]["real"]["estimated_usd"] == pytest.approx(9.0)
    assert periods["month_to_date"]["real"]["by_provider"] == {
        "anthropic": pytest.approx(5.0), "mistral": pytest.approx(4.0)}
    assert periods["today"]["unpriced"] == [{
        "provider": "mistral", "model": "voxtral-mini-latest", "calls": 1,
        "audio_seconds": 600, "input_tokens": 0, "output_tokens": 0, "pages": 0,
        "reason": usage_prices.unpriced_reason("mistral", "voxtral-mini-latest"),
    }]
    projection = report["month_projection"]
    assert projection["days_elapsed"] == 8 and projection["days_in_month"] == 30
    assert projection["projected_usd"] == pytest.approx(9.0 / 8 * 30)
    assert projection["anthropic_projected_usd"] == pytest.approx(5.0 / 8 * 30)
    assert report["budget_usd"] == 200
    json.dumps(report)


def test_the_text_says_the_budget_the_estimate_and_what_has_no_price():
    today = date(2026, 11, 8)
    rows = [
        _row(today, "agent", "agent_step", "anthropic", "claude-sonnet-5",
             input_tokens=1_000_000),
        _row(today, "ingestion", "transcribe", "mistral", "voxtral-mini-latest",
             audio_seconds=60),
    ]

    text = usage_report.render_text(usage_report.build_report(rows, today=today, budget_usd=200))

    assert "200" in text
    assert "claude-sonnet-5" in text
    assert "voxtral-mini-latest" in text and "sin precio" in text
    assert "2026-11-08" in text
    assert "—" not in text  # no em dashes (house rule)


# --- against the database ---------------------------------------------------------------


@pytest.fixture
async def month():
    """A month of its own, far in the past, wiped before and after."""
    start = date(1990 + random.randrange(8), 1 + random.randrange(12), 1)
    end = (start + timedelta(days=32)).replace(day=1)

    async def _wipe():
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(UsageCounter).where(
                UsageCounter.day >= start - timedelta(days=7), UsageCounter.day < end))
            await session.commit()

    await _wipe()
    yield start
    await _wipe()


@needs_pg
async def test_the_report_reads_usage_counters(month):
    today = month + timedelta(days=9)
    await usage.record("chat", "anthropic", "claude-opus-5-5", input_tokens=1_000_000,
                       surface="chat", day=today)
    await usage.record("chat", "anthropic", "claude-opus-5-5", input_tokens=1_000_000,
                       surface="chat", day=month)

    report = await usage_report.gather(today=today, budget_usd=200)

    assert report["periods"]["today"]["real"]["estimated_usd"] == pytest.approx(4.0)
    assert report["periods"]["month_to_date"]["real"]["estimated_usd"] == pytest.approx(8.0)


@needs_pg
async def test_the_report_session_cannot_write():
    from sqlalchemy.exc import DBAPIError

    async with usage_report.read_only_session() as session:
        with pytest.raises(DBAPIError, match="read-only"):
            await session.execute(sa.text(
                "INSERT INTO usage_counters (day, surface, operation, provider, model) "
                "VALUES ('1980-01-01', 'other', 'chat', 'mistral', 'x')"))


@needs_pg
def test_the_script_prints_json_and_text():
    run = subprocess.run(
        [sys.executable, "scripts/usage_report.py", "--today", "1985-06-15", "--format", "both"],
        cwd=API_DIR, capture_output=True, text=True, timeout=60,
    )

    assert run.returncode == 0, run.stderr[-2000:]
    text, _, raw = run.stdout.partition("\n{")
    report = json.loads("{" + raw)
    assert report["budget_usd"] == 200
    assert set(report["periods"]) == {"today", "last_7_days", "month_to_date"}
    assert "1985-06-15" in text
