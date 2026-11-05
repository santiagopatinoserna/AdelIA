"""scripts/eval_lay_language.py: the measurement the lay lexicon waits for.

It is run once in production, by hand, with the setting on and off; these
tests pin, without a key or a database, that it measures what it says (the
probes reach retrieval, the controls carry no lay word, a B that moves under
the cut fails the run) and that it cannot write.
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

from adelia.agent.lay_terms import clinical_terms
from adelia.clinical import red_flags
from adelia.clinical.age_scope import child_outside_scope
from adelia.enrichment.evidence_retrieval import EvidenceMatch

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_lay_language.py"
_spec = importlib.util.spec_from_file_location("eval_lay_language", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ev  # dataclasses look their module up while the class is built
_spec.loader.exec_module(ev)


def test_seven_production_misses_and_twenty_three_colloquial_questions():
    assert len(ev.PROD_MISSES) == 7 and len(ev.COLLOQUIAL) == 23
    ids = [i for i, _, _ in ev.PROD_MISSES + ev.COLLOQUIAL]
    assert len(ids) == len(set(ids))
    assert {loc for _, loc, _ in ev.COLLOQUIAL} == {"es", "fr", "en"}


def test_the_probes_include_groups_a_and_b_of_the_golden_set():
    groups = [p.group for p in ev.probes()]
    assert groups.count("prod") == 7 and groups.count("lay") == 23
    assert groups.count("B") == 15 and groups.count("A") >= 18


@pytest.mark.parametrize("probe_id, locale, question", ev.PROD_MISSES + ev.COLLOQUIAL)
def test_every_written_probe_reaches_retrieval(probe_id, locale, question):
    """A probe the guard stops would measure nothing."""
    assert red_flags.detect(question, locale=locale, age_months=ev.AGE_MONTHS) is None
    assert not child_outside_scope(question)


def test_the_controls_carry_no_lay_word_and_the_rest_do():
    for probe_id, _, question in ev.COLLOQUIAL:
        if probe_id in ("L22", "L23"):
            assert clinical_terms(question) == (), probe_id
        else:
            assert clinical_terms(question), probe_id


def _result(cards):
    return ev.ModeResult(kind="answer" if cards else "no_evidence", cards=cards)


def test_a_b_question_that_moves_under_the_cut_is_reported():
    b = ev.Probe("B2", "B", "es", "¿Es normal que no gatee a los 9 meses?", 9)
    a = ev.Probe("A4", "A", "es", "Regurgita", 4, expect_source="reflujo")
    rows = [
        (b, _result([]), _result([("Bebé de 8-12 meses", 0.18)])),
        (a, _result([]), _result([("Reflujo del lactante", 0.12)])),
    ]
    summary = ev.summarise(rows)
    assert summary["new_b_under_cut"] == ["B2"]
    assert summary["off"]["A"]["expected"] == 0 and summary["on"]["A"]["expected"] == 1
    assert summary["on"]["B"]["under_cut"] == 1


class _Session:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append([])
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, params=None):
        self.log[-1].append(str(statement))


async def test_every_session_is_read_only_before_its_first_query(monkeypatch):
    from adelia.agent import graph
    from adelia.config import settings

    log: list[list[str]] = []
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(ev, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(graph, "AsyncSessionLocal", lambda: _Session(log))

    async def _embed(texts):
        return [[0.0] * 1024 for _ in texts]

    match = EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title="Nappy rash (NHS)",
        organization="NHS", publication_year=2026, url=None, content="x", chunk_index=0,
        distance=0.12,
    )

    async def _retrieve(session, **kwargs):
        await session.execute("SELECT 1")
        return [match]

    monkeypatch.setattr(ev, "embed_texts", _embed)
    monkeypatch.setattr(ev, "retrieve_evidence", _retrieve)
    probe = ev.Probe("P2", "prod", "es", "Tiene el culito muy rojo del pañal", 5)

    on = await ev.run_probe(probe, on=True, translate=False, cache={})

    assert log and all(s[0] == "SET TRANSACTION READ ONLY" for s in log)
    assert "dermatitis del pañal" in on.terms
    assert len(on.nearest) == 2 and on.best == pytest.approx(0.12)
    assert on.cards == [("Nappy rash (NHS)", 0.12)]


async def test_a_guarded_probe_searches_nothing_in_either_mode(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)

    async def _no(*args, **kwargs):
        raise AssertionError("a guarded probe reached retrieval")

    monkeypatch.setattr(ev, "embed_texts", _no)
    probe = ev.Probe("C1", "C", "es", "Mi bebé de 2 meses tiene 38,2 y granitos", 2)
    for on in (False, True):
        result = await ev.run_probe(probe, on=on, translate=False, cache={})
        assert result.guarded and not result.nearest and not result.cards
