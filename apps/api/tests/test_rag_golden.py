"""The golden set as a deploy gate (audit 3.1 and 3.2).

Three groups, five numbers, three locales. The set itself lives in
`adelia/clinical/golden.py` so `scripts/deploy-prod.sh` can read the same
definition; this file runs it and asserts the thresholds. It started as
fifteen Spanish questions and was widened on 2026-10-14 to English and French
in every group, near-miss clinical questions in B and a dosage check on every
red-flag answer; the original fifteen keep their ids and their wording.

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
The report (recall@4, refusal rate, orphan citations, red-flag rate, red-flag
answers carrying a dose, and a verdict per question) is printed and written to
`golden_report.json` next to the test run, which is what the deploy script
prints and `scripts/compare_golden.py` diffs. See
docs/APROBAR_CAMBIO_DE_MODELO.md for the procedure that uses it.
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
    LOCALES,
    NEAR_MISS_KINDS,
    RECALL_AT_4_MIN,
    REFUSAL_RATE_MIN,
    TOP_K,
    GoldenReport,
    citation_defects,
    contains_dosage,
    corpus_blind_spots,
    count_orphan_citations,
    is_refusal,
    questions,
    run_red_flag_group,
    source_matches,
)
from adelia.services.answer_contract import no_evidence_reply, red_flag_reply
from adelia.services.chat_orchestrator import answer_question_streaming

REPORT_PATH = Path(__file__).resolve().parents[1] / "golden_report.json"
EMBEDDINGS_FIXTURE = Path(__file__).parent / "fixtures" / "golden_query_embeddings.json"


# ---------------------------------------------------------------------------
# Structure of the set: cheap, always runs, and catches a set that drifted
# ---------------------------------------------------------------------------


#: The fifteen questions the gate started with. They keep their ids, their
#: group and their Spanish wording: a report taken before the widening must
#: still compare, question by question, against one taken after it.
ORIGINAL_IDS = (
    "A1", "A2", "A3", "A4", "A5", "A6",
    "B1", "B2", "B3", "B4",
    "C1", "C2", "C3", "C4", "C5",
)


def test_the_original_fifteen_are_still_the_first_fifteen_in_spanish():
    by_id = {q.id: q for q in GOLDEN_SET}
    for qid in ORIGINAL_IDS:
        assert qid in by_id, qid
        assert by_id[qid].group == qid[0], qid
        assert by_id[qid].locale == "es", qid
    assert len(ORIGINAL_IDS) == 15
    assert [q.id for q in questions("A")][:6] == list(ORIGINAL_IDS[:6])
    assert [q.id for q in questions("B")][:4] == list(ORIGINAL_IDS[6:10])
    assert [q.id for q in questions("C")][:5] == list(ORIGINAL_IDS[10:])


def test_the_set_is_forty_six_questions_in_three_groups():
    # 42 until A13-A16 were added from the 2026-10-14 demo measurement.
    assert len(GOLDEN_SET) == 46
    assert len(questions("A")) == 16
    assert len(questions("B")) == 15
    assert len(questions("C")) == 15
    assert len({q.id for q in GOLDEN_SET}) == 46


def test_every_group_speaks_all_three_locales():
    """The point of widening: no group is monolingual any more."""
    counts = {(q.group, q.locale) for q in GOLDEN_SET}
    for group in ("A", "B", "C"):
        for locale in LOCALES:
            assert (group, locale) in counts, f"group {group} has no {locale} question"
    assert {q.locale for q in GOLDEN_SET} == set(LOCALES)


def test_the_count_per_group_and_locale_is_the_published_table():
    """The table in the work summary; a drift here is a question added silently."""
    table = {
        (g, loc): sum(1 for q in GOLDEN_SET if q.group == g and q.locale == loc)
        for g in ("A", "B", "C")
        for loc in LOCALES
    }
    assert table == {
        ("A", "es"): 10, ("A", "en"): 3, ("A", "fr"): 3,
        ("B", "es"): 9, ("B", "en"): 3, ("B", "fr"): 3,
        ("C", "es"): 5, ("C", "en"): 5, ("C", "fr"): 5,
    }


def test_group_b_has_the_five_near_miss_kinds_in_spanish():
    """Hole 2: B must contain questions that sound like the corpus."""
    kinds = {q.kind for q in questions("B") if q.locale == "es"} - {""}
    assert kinds == set(NEAR_MISS_KINDS)
    for q in questions("B"):
        assert q.kind == "" or q.kind in NEAR_MISS_KINDS, q.id
        assert q.rationale, q.id


def test_the_near_misses_are_a_majority_of_group_b():
    near = [q for q in questions("B") if q.kind]
    assert len(near) >= 11
    assert len(near) > len(questions("B")) / 2


def test_every_a_source_alternative_names_a_real_corpus_title():
    """A typo in `expect_source` would turn a recall miss into a silent one.

    Reads the corpus files (no database, no key). Every "|" alternative must
    match at least one title, so a dead alternative is a failure rather than
    a comfortable extra way to pass.
    """
    import json

    from adelia.clinical.golden import CORPUS_DATA_DIR

    titles: list[str] = []
    for path in sorted(CORPUS_DATA_DIR.glob("evidence_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        titles.extend(str(src["title"]) for src in payload["sources"])
    assert titles, "no corpus files found"
    for q in questions("A"):
        for alt in q.expect_source.split("|"):
            assert any(source_matches(alt, t) for t in titles), f"{q.id}: {alt!r} matches no title"


# The A/B questions run through the real answering path, where the red-flag
# detector comes FIRST. A question that trips it is answered by the referral
# and never reaches retrieval, so it would be measuring the detector while
# claiming to measure retrieval or the refusal.
KNOWN_A_QUESTIONS_THAT_TRIP_THE_DETECTOR = {
    "A6": (
        "pre-existing: 'deshidratación' fires the dehydration flag, so the answer is the "
        "referral and the question passes through the red-flag citation title "
        "('...gastroenteritis (NICE CG84)'), not through retrieval. Reported, not reworded: "
        "the original fifteen keep their wording."
    ),
}


@pytest.mark.parametrize("q", [q for q in GOLDEN_SET if q.group in ("A", "B")], ids=lambda q: q.id)
def test_no_retrieval_question_trips_the_red_flag_detector(q):
    from adelia.clinical.red_flags import detect

    flag = detect(q.question, locale=q.locale, age_months=q.age_months)
    if q.id in KNOWN_A_QUESTIONS_THAT_TRIP_THE_DETECTOR:
        assert flag is not None, f"{q.id} no longer trips the detector; drop it from the known list"
    else:
        assert flag is None, f"{q.id} fires {flag.code}: it would never reach retrieval"


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


def test_group_c_fires_in_every_locale_and_carries_no_dose():
    """Hole 1 and hole 3 on the always-runnable half of the gate."""
    report = run_red_flag_group()
    assert report.rates_by_locale()["C"] == {"en": 1.0, "es": 1.0, "fr": 1.0}, report.render()
    assert report.red_flag_dosage == 0, report.render()
    assert report.failures() == [], report.render()
    assert all(r["passed"] for r in report.results.values()), report.render()


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
    # The reply is in the parent's language and carries no dose (audit 3.3's
    # acceptance criterion, "no contiene mg/kg", which nothing asserted).
    assert text == red_flag_reply(q.expect_red_flag, q.locale)
    assert not contains_dosage(text, q.locale), f"{q.id}: the red-flag answer carries a dose"


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


def _missing_recordings(embeddings: dict[str, list[float]] | None) -> list[str]:
    """Group A and B ids the recording has no vector for.

    The recording is written for the questions that existed when it was made.
    A question added later has no vector, and a half-covering recording used
    to surface as a KeyError in the middle of the run. It is now a skip with
    the ids named, or (when there is a key) a live embedding of everything.
    """
    have = embeddings or {}
    return [q.id for q in GOLDEN_SET if q.group in ("A", "B") and q.id not in have]


def _usable_recording() -> dict[str, list[float]] | None:
    """The recording, only when it covers every group A and B question."""
    recording = _recorded_embeddings()
    return recording if recording is not None and not _missing_recordings(recording) else None


async def _skip_reason() -> str | None:
    """Why A and B cannot run here, or None when they can.

    Async because the test awaiting it already runs inside an event loop:
    this used to call `asyncio.run(_corpus_size())`, which raises "cannot be
    called from a running event loop" there, which the `except` below turned
    into a skip. With a key and a full corpus, groups A and B could never run.
    """
    have_key = bool(os.environ.get("MISTRAL_API_KEY"))
    recording = _recorded_embeddings()
    missing = _missing_recordings(recording) if recording is not None else []
    if not have_key and (recording is None or missing):
        if recording is not None:
            return (
                f"tests/fixtures/golden_query_embeddings.json no tiene vector para "
                f"{', '.join(missing)}: vuelve a grabarlo con "
                "`uv run python -m tests.record_golden_embeddings`"
            )
        return (
            "sin MISTRAL_API_KEY y sin tests/fixtures/golden_query_embeddings.json: "
            "grábalo con `uv run python -m tests.record_golden_embeddings`"
        )
    try:
        size = await _corpus_size()
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
    reason = await _skip_reason()
    report = run_red_flag_group()
    if reason:
        report.skipped_reason = reason
        _publish(report)
        pytest.skip(reason)

    embeddings = _usable_recording()
    hits = 0
    orphans = 0
    for q in questions("A"):
        answer, evidence = await _answer(q, embeddings)
        titles = " | ".join((c.get("title") or "").lower() for c in evidence[:TOP_K])
        hit = source_matches(q.expect_source, titles)
        if hit:
            hits += 1
        else:
            report.misses.append(f"{q.id}: {q.expect_source!r} fuera del top-{TOP_K} ({titles[:120]})")
        # Counted apart from recall: the right guideline can be in the top four
        # and still sit beside a repeat of itself or a card about something else.
        defects = citation_defects(q, evidence)
        report.misses.extend(f"{q.id}: {defect}" for defect in defects)
        report.citation_defects += len(defects)
        report.mark(q, hit and not defects)
        orphans += count_orphan_citations(answer, evidence)
    report.a_ran = len(questions("A"))
    report.recall_at_4 = hits / report.a_ran

    refusals = 0
    for q in questions("B"):
        answer, evidence = await _answer(q, embeddings)
        refused = is_refusal(answer, q.locale)
        if refused:
            refusals += 1
        else:
            report.misses.append(f"{q.id}: respondió en vez de negarse ({answer[:120]!r})")
        report.mark(q, refused)
        orphans += count_orphan_citations(answer, evidence)
    report.b_ran = len(questions("B"))
    report.refusal_rate = refusals / report.b_ran
    report.orphan_citations = orphans

    _publish(report)
    assert not report.failures(), report.render()
    assert report.recall_at_4 >= RECALL_AT_4_MIN
    assert report.refusal_rate >= REFUSAL_RATE_MIN


def _publish(report: GoldenReport) -> None:
    # Files only, no database: the line prints on a laptop with nothing
    # running, and degrades to a note rather than failing the gate.
    report.blind_spots = corpus_blind_spots()
    print("\n" + report.render())
    REPORT_PATH.write_text(_report_json(report.as_dict()), encoding="utf-8")


def _report_json(data: dict) -> str:
    """The report as indented JSON, with one line per question and per theme.

    `scripts/deploy-prod.sh` prints this file into the deploy log. Fully
    indented, the 42 per-question verdicts alone would add some 250 lines to
    a log a person reads at deploy time; one line each keeps the aggregates
    readable and the verdicts greppable.
    """
    shell = dict(data)
    compact: dict[str, str] = {}
    results = data.get("results") or {}
    if results:
        rows = ",\n".join(
            f"    {json.dumps(qid)}: {json.dumps(r, ensure_ascii=False)}" for qid, r in results.items()
        )
        compact["results"] = "{\n" + rows + "\n  }"
        shell["results"] = "@@results@@"
    spots = data.get("blind_spots") or []
    if spots:
        rows = ",\n".join(f"    {json.dumps(t, ensure_ascii=False)}" for t in spots)
        compact["blind_spots"] = "[\n" + rows + "\n  ]"
        shell["blind_spots"] = "@@blind_spots@@"
    body = json.dumps(shell, ensure_ascii=False, indent=2)
    for key, text in compact.items():
        body = body.replace(f'"@@{key}@@"', text)
    return body + "\n"


# ---------------------------------------------------------------------------
# The machinery around A and B, tested without a key or a corpus
# ---------------------------------------------------------------------------


def _full_recording() -> dict[str, list[float]]:
    return {q.id: [0.0] for q in GOLDEN_SET if q.group in ("A", "B")}


@pytest.mark.asyncio
async def test_the_skip_check_runs_inside_the_event_loop(monkeypatch):
    """It used to call asyncio.run() here and always skip with a RuntimeError.

    With a recording and a corpus of 500 fragments there is nothing to skip
    for; before the fix this returned "cannot be called from a running event
    loop" and A and B could never run, with or without a key.
    """
    import sys

    module = sys.modules[__name__]

    async def _corpus_500() -> int:
        return 500

    monkeypatch.setattr(module, "_recorded_embeddings", _full_recording)
    monkeypatch.setattr(module, "_corpus_size", _corpus_500)
    assert await module._skip_reason() is None


@pytest.mark.asyncio
async def test_a_small_corpus_is_a_skip_with_the_size_in_the_reason(monkeypatch):
    import sys

    module = sys.modules[__name__]

    async def _corpus_32() -> int:
        return 32

    monkeypatch.setattr(module, "_recorded_embeddings", _full_recording)
    monkeypatch.setattr(module, "_corpus_size", _corpus_32)
    reason = await module._skip_reason()
    assert reason is not None and "32 fragmentos" in reason


@pytest.mark.asyncio
async def test_an_unreachable_database_is_a_skip_not_a_crash(monkeypatch):
    import sys

    module = sys.modules[__name__]

    async def _down() -> int:
        raise ConnectionRefusedError("no route")

    monkeypatch.setattr(module, "_recorded_embeddings", _full_recording)
    monkeypatch.setattr(module, "_corpus_size", _down)
    reason = await module._skip_reason()
    assert reason is not None and "no responde" in reason and "no route" in reason


@pytest.mark.asyncio
async def test_a_recording_that_misses_new_questions_skips_naming_them(monkeypatch):
    """The recording predates a question: skip with its id, never a KeyError mid-run."""
    import sys

    module = sys.modules[__name__]
    partial = {q.id: [0.0] for q in GOLDEN_SET if q.group in ("A", "B") and q.id not in ("A12", "B15")}
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(module, "_recorded_embeddings", lambda: partial)
    assert module._missing_recordings(partial) == ["A12", "B15"]
    assert module._usable_recording() is None
    reason = await module._skip_reason()
    assert reason is not None and "A12" in reason and "B15" in reason


@pytest.mark.asyncio
async def test_no_key_and_no_recording_says_how_to_record(monkeypatch):
    import sys

    module = sys.modules[__name__]
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(module, "_recorded_embeddings", lambda: None)
    reason = await module._skip_reason()
    assert reason is not None and "record_golden_embeddings" in reason


def test_the_published_report_is_valid_json_with_one_line_per_question():
    report = run_red_flag_group()
    report.blind_spots = corpus_blind_spots()
    text = _report_json(report.as_dict())
    assert json.loads(text) == json.loads(json.dumps(report.as_dict(), ensure_ascii=False))
    import re

    assert len([ln for ln in text.splitlines() if re.match(r'^    "C\d+": \{.*\},?$', ln)]) == 15
    indented = json.dumps(report.as_dict(), ensure_ascii=False, indent=2).splitlines()
    saved = len(indented) - len(text.splitlines())
    assert saved >= 6 * 15, f"the deploy log prints this file; only {saved} lines saved"
    assert _report_json(GoldenReport().as_dict()).count('"results": {}') == 1


# ---------------------------------------------------------------------------
# The A/B scoring loop, driven by canned answers
#
# `test_groups_a_and_b_meet_the_deploy_gate` skips wherever there is no key or
# no corpus, which is most places. Its body would then be code nobody has run.
# These tests call it for real with `_answer` replaced by a canned answer, so
# the wiring (source matching, refusal check, per-question verdicts, the file
# the deploy script prints) is exercised on every run, and the same canned
# reports prove the compare script end to end.
# ---------------------------------------------------------------------------


def _drive_the_gate(
    monkeypatch,
    tmp_path,
    *,
    bad_b: tuple[str, ...] = (),
    bad_a: tuple[str, ...] = (),
    repeated_a: tuple[str, ...] = (),
):
    """Run the real gate test with canned answers; return (report path, raised).

    `repeated_a` names group A questions whose canned answer cites the same
    source twice (right guideline, one source in two cards)."""
    import sys

    module = sys.modules[__name__]
    path = tmp_path / "golden_report.json"

    async def _no_skip() -> None:
        return None

    async def _canned(q, embeddings):
        if q.group == "A":
            title = "Otra guía sin relación" if q.id in bad_a else f"Guía: {q.expect_source.split('|')[0]}"
            # A real answer carries the source id and the start of the fragment;
            # the canned one has to, or the citation checks could never fire.
            snippet = q.every_citation_mentions.split("|")[0] if q.every_citation_mentions else ""
            card = {"tag": "ev_1", "title": title, "source_id": f"src-{q.id}-1", "snippet": snippet}
            cards = [card]
            if q.id in repeated_a:
                cards.append({**card, "tag": "ev_2"})
            cited = " [ev_2]" if len(cards) > 1 else ""
            return f"Respuesta con fuente [ev_1]{cited}.", cards
        if q.id in bad_b:
            return "Dale 5 ml de cetirizina cada 8 horas.", []
        return no_evidence_reply(q.locale), []

    monkeypatch.setattr(module, "_skip_reason", _no_skip)
    monkeypatch.setattr(module, "_answer", _canned)
    monkeypatch.setattr(module, "_usable_recording", lambda: _full_recording())
    monkeypatch.setattr(module, "REPORT_PATH", path)
    return path, module


@pytest.mark.asyncio
async def test_the_gate_passes_with_canned_perfect_answers_and_publishes_every_question(
    monkeypatch, tmp_path
):
    path, module = _drive_the_gate(monkeypatch, tmp_path)
    await module.test_groups_a_and_b_meet_the_deploy_gate()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recall_at_4"] == 1.0 and data["refusal_rate"] == 1.0 and data["red_flag_rate"] == 1.0
    assert data["questions_run"] == {"A": 16, "B": 15, "C": 15}
    assert set(data["results"]) == {q.id for q in GOLDEN_SET}
    assert all(r["passed"] for r in data["results"].values())
    assert data["questions_run_by_locale"] == {
        "es": {"A": 10, "B": 9, "C": 5},
        "en": {"A": 3, "B": 3, "C": 5},
        "fr": {"A": 3, "B": 3, "C": 5},
    }
    assert data["blind_spots"], "the report must carry the blind-spots section"
    assert data["misses"] == [] and data["skipped_reason"] is None
    assert data["citation_defects"] == 0


@pytest.mark.asyncio
async def test_a_group_b_answer_that_gives_a_dose_instead_of_refusing_fails_the_gate(
    monkeypatch, tmp_path
):
    path, module = _drive_the_gate(monkeypatch, tmp_path, bad_b=("B6",))
    with pytest.raises(AssertionError) as failed:
        await module.test_groups_a_and_b_meet_the_deploy_gate()
    assert "tasa de rechazo del grupo B" in str(failed.value)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["results"]["B6"]["passed"] is False
    assert data["results"]["B6"]["kind"] == "dose"
    assert data["refusal_rate"] == pytest.approx(14 / 15)
    assert any(m.startswith("B6:") for m in data["misses"])


@pytest.mark.asyncio
async def test_an_a_question_whose_source_is_missing_is_recorded_as_a_miss(monkeypatch, tmp_path):
    # Three French misses were enough to trip recall@4 >= 0.8 while group A had
    # twelve questions (9/12 = 0.75). With A13-A16 it has sixteen, three misses
    # are 13/16 = 0.8125 and the gate rightly lets them pass, so A16 joins them:
    # 12/16 is the same 0.75 and the same failure.
    path, module = _drive_the_gate(monkeypatch, tmp_path, bad_a=("A10", "A11", "A12", "A16"))
    with pytest.raises(AssertionError):
        await module.test_groups_a_and_b_meet_the_deploy_gate()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recall_at_4"] == 0.75
    assert data["rates_by_locale"]["A"] == {"en": 1.0, "es": 0.9, "fr": 0.0}


@pytest.mark.asyncio
async def test_the_right_guideline_twice_fails_the_question_but_not_recall(monkeypatch, tmp_path):
    """A14 gets its source, in two cards: recall@4 keeps its meaning, the gate still fails."""
    path, module = _drive_the_gate(monkeypatch, tmp_path, repeated_a=("A14",))
    with pytest.raises(AssertionError) as failed:
        await module.test_groups_a_and_b_meet_the_deploy_gate()
    assert "repetida(s) o de otro tema" in str(failed.value)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recall_at_4"] == 1.0
    assert data["citation_defects"] == 1
    assert data["results"]["A14"]["passed"] is False
    assert any(m.startswith("A14:") and "repite" in m for m in data["misses"])


@pytest.mark.asyncio
async def test_a_card_that_does_not_address_the_question_fails_the_gate(monkeypatch, tmp_path):
    """The sleep question with a card about feeding: the source is there, the card is not."""
    import sys

    module = sys.modules[__name__]
    path, _ = _drive_the_gate(monkeypatch, tmp_path)
    canned = module._answer

    async def _with_a_feeding_card(q, embeddings):
        answer, cards = await canned(q, embeddings)
        if q.id == "A13":
            cards = cards + [{
                "tag": "ev_2", "title": "Manejo conservador del reflujo del lactante",
                "source_id": "src-other",
                "snippet": "Bebé amamantado con reflujo: NO suspender la lactancia",
            }]
            answer += " [ev_2]"
        return answer, cards

    monkeypatch.setattr(module, "_answer", _with_a_feeding_card)
    with pytest.raises(AssertionError):
        await module.test_groups_a_and_b_meet_the_deploy_gate()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recall_at_4"] == 1.0 and data["citation_defects"] == 1
    assert data["results"]["A13"]["passed"] is False
    assert any(m.startswith("A13:") and "no habla del tema" in m for m in data["misses"])


@pytest.mark.asyncio
async def test_two_gate_runs_compare_end_to_end(monkeypatch, tmp_path):
    """Baseline all green, candidate with one broken near miss: exit status 1."""
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "compare_golden.py"
    spec = importlib.util.spec_from_file_location("compare_golden_e2e", script)
    compare = importlib.util.module_from_spec(spec)
    sys_modules = __import__("sys").modules
    sys_modules["compare_golden_e2e"] = compare
    spec.loader.exec_module(compare)

    base_dir, cand_dir = tmp_path / "base", tmp_path / "cand"
    base_dir.mkdir()
    cand_dir.mkdir()
    path, module = _drive_the_gate(monkeypatch, base_dir)
    await module.test_groups_a_and_b_meet_the_deploy_gate()
    base = path
    path, module = _drive_the_gate(monkeypatch, cand_dir, bad_b=("B9",))
    with pytest.raises(AssertionError):
        await module.test_groups_a_and_b_meet_the_deploy_gate()
    assert compare.main([str(base), str(path)]) == 1
    assert compare.main([str(base), str(base)]) == 0
