"""The golden set as a deploy gate (audit 3.1 and 3.2).

Fifteen questions, three groups, four numbers. The set itself lives in
`adelia/clinical/golden.py` so `scripts/deploy-prod.sh` can read the same
definition; this file runs it and asserts the thresholds.

What runs where
---------------
* **Group C (red flags) always runs.** It is pure code: no model, no
  retrieval, no key. That is deliberate. The part of the gate that protects
  against the audit's risk 1 must not be the part that silently skips in CI.
* **Groups A and B need embeddings and a loaded corpus.** Two ways to get
  them:
    1. live, with `MISTRAL_API_KEY` set and the evidence corpus loaded into
       the database;
    2. offline, from `tests/fixtures/golden_query_embeddings.json`, which
       holds one recorded 1024-dim query vector per question. Record it once
       with `uv run python -m tests.record_golden_embeddings` on a machine
       that has a key; after that the set runs with no key at all, as long as
       the corpus is in the database.
  With neither, both groups skip and say so. A skip is reported, never
  counted as a pass: `GoldenReport.failures()` treats "did not run" as
  "unknown", so a human decides instead of a green tick lying.

Publishing
----------
The report (recall@4, refusal rate, orphan citations, red-flag rate) is
printed and written to `golden_report.json` next to the test run, which is
what the deploy script reads.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from adelia.clinical.golden import (
    GOLDEN_SET,
    RECALL_AT_4_MIN,
    REFUSAL_RATE_MIN,
    TOP_K,
    GoldenReport,
    count_orphan_citations,
    questions,
    run_red_flag_group,
)
from adelia.services.answer_contract import no_evidence_reply
from adelia.services.chat_orchestrator import answer_question_streaming

REPORT_PATH = Path(__file__).resolve().parents[1] / "golden_report.json"
EMBEDDINGS_FIXTURE = Path(__file__).parent / "fixtures" / "golden_query_embeddings.json"


# ---------------------------------------------------------------------------
# Structure of the set: cheap, always runs, and catches a set that drifted
# ---------------------------------------------------------------------------


def test_the_set_is_fifteen_questions_in_three_groups():
    assert len(GOLDEN_SET) == 15
    assert len(questions("A")) == 6
    assert len(questions("B")) == 4
    assert len(questions("C")) == 5
    assert len({q.id for q in GOLDEN_SET}) == 15


def test_every_question_declares_what_it_expects_and_why():
    for q in GOLDEN_SET:
        assert q.rationale, q.id
        if q.group == "A":
            assert q.expect_source, q.id
        if q.group == "C":
            assert q.expect_red_flag, q.id


# ---------------------------------------------------------------------------
# Group C: the half of the gate that can never skip
# ---------------------------------------------------------------------------


def test_group_c_red_flags_all_fire():
    report = run_red_flag_group()
    assert report.red_flag_rate == 1.0, report.render()


@pytest.mark.parametrize("q", questions("C"), ids=[q.id for q in questions("C")])
def test_group_c_never_reaches_the_generative_model(q):
    """The referral is the answer, and it is produced without the model."""

    def _explode(*args, **kwargs):
        raise AssertionError(f"{q.id}: the model was called on a red flag")

    async def _run():
        out = []
        with patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode), \
             patch("adelia.services.chat_orchestrator.embed_texts", _explode):
            async for ev in answer_question_streaming(
                user_id=uuid4(), question=q.question, locale=q.locale,
                age_months=q.age_months,
            ):
                out.append(ev)
        return out

    import asyncio

    events = asyncio.run(_run())
    text = "".join(e.content for e in events if e.type == "token")
    assert "112" in text
    assert events[-1].type == "final"
    assert len(events[-1].evidence_citations) == 1


# ---------------------------------------------------------------------------
# Groups A and B: retrieval, gated on having embeddings and a corpus
# ---------------------------------------------------------------------------


def _recorded_embeddings() -> dict[str, list[float]] | None:
    if not EMBEDDINGS_FIXTURE.exists():
        return None
    data = json.loads(EMBEDDINGS_FIXTURE.read_text(encoding="utf-8"))
    return data.get("embeddings") or None


async def _corpus_size() -> int:
    from sqlalchemy import func, select

    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk

    async with AsyncSessionLocal() as session:
        return int(await session.scalar(select(func.count()).select_from(EvidenceChunk)) or 0)


def _skip_reason() -> str | None:
    """Why A and B cannot run here, or None when they can."""
    have_key = bool(os.environ.get("MISTRAL_API_KEY"))
    have_recording = _recorded_embeddings() is not None
    if not have_key and not have_recording:
        return (
            "sin MISTRAL_API_KEY y sin tests/fixtures/golden_query_embeddings.json: "
            "grábalo con `uv run python -m tests.record_golden_embeddings`"
        )
    try:
        import asyncio

        size = asyncio.run(_corpus_size())
    except Exception as exc:  # noqa: BLE001
        return f"la base de datos de evidencia no responde: {exc}"
    if size < 100:
        return f"el corpus cargado tiene {size} fragmentos, insuficiente para medir recall@{TOP_K}"
    return None


async def _answer(q, embeddings: dict[str, list[float]] | None) -> tuple[str, list[dict]]:
    """Run one golden question through the real answering path."""
    text: list[str] = []
    evidence: list[dict] = []

    async def _fake_embed(texts):
        return [embeddings[q.id]]

    ctx = (
        patch("adelia.services.chat_orchestrator.embed_texts", _fake_embed)
        if embeddings is not None
        else _null_context()
    )
    with ctx:
        async for ev in answer_question_streaming(
            user_id=uuid4(), question=q.question, locale=q.locale, age_months=q.age_months
        ):
            if ev.type == "token":
                text.append(ev.content)
            elif ev.type == "final":
                evidence = list(ev.evidence_citations)
            elif ev.type == "error":
                raise AssertionError(f"{q.id}: {ev.content}")
    return "".join(text), evidence


def _null_context():
    from contextlib import nullcontext

    return nullcontext()


@pytest.mark.asyncio
async def test_groups_a_and_b_meet_the_deploy_gate():
    reason = _skip_reason()
    report = run_red_flag_group()
    if reason:
        report.skipped_reason = reason
        _publish(report)
        pytest.skip(reason)

    embeddings = _recorded_embeddings()
    hits = 0
    orphans = 0
    for q in questions("A"):
        answer, evidence = await _answer(q, embeddings)
        titles = " | ".join((c.get("title") or "").lower() for c in evidence[:TOP_K])
        if q.expect_source.lower() in titles:
            hits += 1
        else:
            report.misses.append(f"{q.id}: {q.expect_source!r} fuera del top-{TOP_K} ({titles[:120]})")
        orphans += count_orphan_citations(answer, evidence)
    report.a_ran = len(questions("A"))
    report.recall_at_4 = hits / report.a_ran

    refusals = 0
    for q in questions("B"):
        answer, evidence = await _answer(q, embeddings)
        expected = no_evidence_reply(q.locale)
        if expected in answer or "112" in answer:
            refusals += 1
        else:
            report.misses.append(f"{q.id}: respondió en vez de negarse ({answer[:120]!r})")
        orphans += count_orphan_citations(answer, evidence)
    report.b_ran = len(questions("B"))
    report.refusal_rate = refusals / report.b_ran
    report.orphan_citations = orphans

    _publish(report)
    assert not report.failures(), report.render()
    assert report.recall_at_4 >= RECALL_AT_4_MIN
    assert report.refusal_rate >= REFUSAL_RATE_MIN


def _publish(report: GoldenReport) -> None:
    print("\n" + report.render())
    REPORT_PATH.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
