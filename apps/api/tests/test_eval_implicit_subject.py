"""scripts/eval_implicit_subject.py: the measurement the implicit subject waits for.

Run once in production, by hand, with settings.implicit_subject_expansion off
and on in the same process. These tests pin, without a key or a database, that
it measures what it says (20 sentences without a subject in es/fr/en that reach
retrieval and get the baby, the fever button flow, groups A and B of the golden
set), that a B that moves under the cut fails the run, and that it cannot write.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

from adelia.agent.implicit_subject import subject_query
from adelia.clinical import red_flags
from adelia.clinical.age_scope import child_outside_scope
from adelia.enrichment.evidence_retrieval import EvidenceMatch

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_implicit_subject.py"
_spec = importlib.util.spec_from_file_location("eval_implicit_subject", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ev  # dataclasses look their module up while the class is built
_spec.loader.exec_module(ev)


def test_twenty_sentences_without_a_subject_in_the_three_languages():
    assert len(ev.SUBJECTLESS) == 20
    ids = [i for i, _, _ in ev.SUBJECTLESS]
    assert len(ids) == len(set(ids))
    locales = [loc for _, loc, _ in ev.SUBJECTLESS]
    assert {"es", "fr", "en"} == set(locales) and locales.count("es") >= 10


@pytest.mark.parametrize("probe_id, locale, question", ev.SUBJECTLESS)
def test_every_sentence_reaches_retrieval_and_gets_the_baby(probe_id, locale, question):
    """A probe the guard stops, or one the rules leave alone, would measure nothing."""
    assert red_flags.detect(question, locale=locale, age_months=ev.AGE_MONTHS) is None
    assert not child_outside_scope(question)
    assert subject_query(question, locale=locale, spoken=question) is not None


def test_the_fever_button_flow_is_probed_with_and_without_the_baby():
    clarified = [p for p in ev.probes() if p.group == "clarified"]
    assert [p.question for p in clarified] == [
        "Tiene fiebre, ¿qué hago?", "Mi bebé tiene fiebre, ¿qué hago?",
    ]
    assert all(p.clarification == {"field": "temperature", "value": "38-38.9"}
               for p in clarified)


def test_the_probes_include_groups_a_and_b_of_the_golden_set():
    groups = [p.group for p in ev.probes()]
    assert groups.count("subject") == 20
    assert groups.count("B") == 18 and groups.count("A") >= 35


async def test_both_modes_run_in_one_process_with_backoff_and_a_pause(monkeypatch):
    """The prod run of 2026-11-06 died halfway on a Mistral 429: embeddings go
    through embed_with_retry and the script waits two seconds between probes.
    The setting is put back as it was, whatever happens."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "implicit_subject_expansion", False)
    calls: list[tuple[str, bool]] = []
    pauses: list[float] = []

    async def _probe(probe, *, on, translate, cache):
        calls.append((probe.id, on))
        return ev.ModeResult(kind="no_evidence")

    async def _pause(seconds):
        pauses.append(seconds)

    two = [ev.SubjectProbe(i, "subject", "es", "Tiene tos", 5) for i in ("X1", "X2")]
    monkeypatch.setattr(ev, "probes", lambda: two)
    monkeypatch.setattr(ev, "run_probe", _probe)
    monkeypatch.setattr(ev, "_pause", _pause)
    status = await ev.main_async(argparse.Namespace(no_translate=True, json=None))
    assert status == 0
    assert calls == [("X1", False), ("X1", True), ("X2", False), ("X2", True)]
    assert pauses == [2.0]
    assert settings.implicit_subject_expansion is False
    assert ev.embed_with_retry.__module__ == "adelia.enrichment.evidence_loader"


async def test_a_b_question_newly_under_the_cut_exits_with_one(monkeypatch):
    b = ev.SubjectProbe("B3", "B", "es", "¿Cuánto cuesta una guardería privada?", 18)

    async def _probe(probe, *, on, translate, cache):
        cards = [("Adaptación a la guardería", 0.18)] if on else []
        return ev.ModeResult(kind="answer" if cards else "no_evidence", cards=cards)

    async def _pause(seconds):
        return None

    monkeypatch.setattr(ev, "probes", lambda: [b])
    monkeypatch.setattr(ev, "run_probe", _probe)
    monkeypatch.setattr(ev, "_pause", _pause)
    assert await ev.main_async(argparse.Namespace(no_translate=True, json=None)) == 1


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


def _restore_setting(monkeypatch):
    """run_probe sets the setting for the process, as the prod run needs;
    monkeypatch puts it back after the test so no other test inherits it."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "implicit_subject_expansion", False)


def _fakes(monkeypatch, log, embedded):
    from adelia.agent import graph

    _restore_setting(monkeypatch)

    monkeypatch.setattr(ev, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(graph, "AsyncSessionLocal", lambda: _Session(log))

    async def _embed(texts):
        embedded.append(list(texts))
        return [[0.0] * 1024 for _ in texts]

    match = EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title="Fiebre (AEPap)",
        organization="AEPap", publication_year=2026, url=None, content="x", chunk_index=0,
        distance=0.18,
    )

    async def _retrieve(session, **kwargs):
        await session.execute("SELECT 1")
        return [match]

    monkeypatch.setattr(ev, "embed_with_retry", _embed)
    monkeypatch.setattr(ev, "retrieve_evidence", _retrieve)


async def test_every_session_is_read_only_and_on_searches_with_the_baby(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    log: list[list[str]] = []
    embedded: list[list[str]] = []
    _fakes(monkeypatch, log, embedded)
    probe = ev.SubjectProbe("S1", "subject", "es", "Tiene diarrea desde ayer", 5)

    off = await ev.run_probe(probe, on=False, translate=False, cache={})
    on = await ev.run_probe(probe, on=True, translate=False, cache={})

    assert log and all(s[0] == "SET TRANSACTION READ ONLY" for s in log)
    assert embedded == [
        ["Tiene diarrea desde ayer"],
        ["Tiene diarrea desde ayer", "Mi bebé de 5 meses: Tiene diarrea desde ayer"],
    ]
    assert len(off.nearest) == 1 and len(on.nearest) == 2
    assert on.cards == [("Fiebre (AEPap)", 0.18)]


async def test_the_clarified_probe_searches_her_message_with_the_button_line(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    embedded: list[list[str]] = []
    _fakes(monkeypatch, [], embedded)
    probe = next(p for p in ev.probes() if p.id == "K1")
    await ev.run_probe(probe, on=True, translate=False, cache={})
    absorbed = "Tiene fiebre, ¿qué hago?\nTemperatura: 38 a 38,9 °C"
    assert embedded == [[absorbed, f"Mi bebé de 5 meses: {absorbed}"]]


async def test_a_guarded_probe_searches_nothing_in_either_mode(monkeypatch):
    async def _no(*args, **kwargs):
        raise AssertionError("a guarded probe reached retrieval")

    _restore_setting(monkeypatch)
    monkeypatch.setattr(ev, "embed_with_retry", _no)
    probe = ev.SubjectProbe("C1", "C", "es", "Tiene 2 meses y 38,5 de fiebre", 2)
    for on in (False, True):
        result = await ev.run_probe(probe, on=on, translate=False, cache={})
        assert result.guarded and not result.nearest and not result.cards
