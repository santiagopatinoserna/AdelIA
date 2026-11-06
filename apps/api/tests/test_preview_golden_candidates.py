"""scripts/preview_golden_candidates.py: the candidates measured before they gate a deploy.

A question added to the golden set runs on the server in every deploy and stops
it when it misses (docs/GOLDEN_GATE_DESPLIEGUE.md). The 2026-11-06 candidates
(clinical/golden.CANDIDATES) are run first by this script, by hand, in the
production container. These tests pin, with no key and no database, that it
judges a question the way the gate does (source in the cards, clean cards, a B
under the cut is a failure, a guarded A is a failure), that it cannot write and
never generates, and that the vectors it records have the fixture's shape.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

from adelia.clinical.golden import GOLDEN_SET, GoldenQuestion, written_2026_11_06
from adelia.enrichment.evidence_retrieval import EvidenceMatch

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "preview_golden_candidates.py"
_spec = importlib.util.spec_from_file_location("preview_golden_candidates", _PATH)
pv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pv  # dataclasses look their module up while the class is built
_spec.loader.exec_module(pv)


def _match(title: str, distance: float, content: str = "x", source_id=None) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=source_id or uuid.uuid4(), source_title=title,
        organization="AEPap", publication_year=2024, url=None, content=content,
        chunk_index=0, distance=distance,
    )


def _card(title: str, snippet: str = "x", source_id: str | None = None) -> dict:
    return {"tag": "ev_1", "title": title, "snippet": snippet,
            "source_id": source_id or str(uuid.uuid4())}


_A = GoldenQuestion(
    "A90", "A", "Tiene la piel muy seca, ¿es dermatitis atópica?", age_months=6,
    expect_source="dermatitis atópica", every_citation_mentions="atopic|eccema|piel",
    rationale="doble",
)
_B = GoldenQuestion(
    "B90", "B", "¿Qué champú le pongo para los piojos?", age_months=20, kind="adjacent",
    rationale="doble",
)


# --- which questions --------------------------------------------------------------


def test_the_default_is_the_candidates_and_none_left_is_an_error(monkeypatch):
    from adelia.clinical import golden

    two = written_2026_11_06()[:2]
    monkeypatch.setattr(golden, "CANDIDATES", two)
    assert pv.select(None) == list(two)
    monkeypatch.setattr(golden, "CANDIDATES", ())
    with pytest.raises(SystemExit):
        pv.select(None)


def test_ids_pick_from_the_gate_and_the_candidates_in_the_order_given():
    picked = pv.select("B18,A16")
    assert [q.id for q in picked] == ["B18", "A16"]
    assert picked[1] is next(q for q in GOLDEN_SET if q.id == "A16")
    with pytest.raises(SystemExit):
        pv.select("A16,Z99")


def test_export_and_load_round_trip_and_ignore_unknown_fields(tmp_path):
    """The export is read by a production container whose golden.py may be
    older than this one: a field it does not know is dropped, not a crash."""
    nov6 = list(written_2026_11_06())
    path = tmp_path / "candidates.json"
    pv.export(nov6, path)
    assert pv.load(path) == nov6
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["a_field_from_the_future"] = 1
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    assert pv.load(path)[0] == nov6[0]


async def test_export_needs_no_database_and_no_key(tmp_path, monkeypatch):
    async def _no(*args, **kwargs):
        raise AssertionError("export must not search or embed")

    monkeypatch.setattr(pv, "preview", _no)
    out = tmp_path / "c.json"
    args = argparse.Namespace(ids="A16,B18", questions=None, export=str(out), record=None,
                              json=None)
    assert await pv.main_async(args) == 0
    assert [r["id"] for r in json.loads(out.read_text(encoding="utf-8"))] == ["A16", "B18"]


# --- the verdict, judged the way the gate judges ------------------------------------


def test_an_a_with_its_source_and_clean_cards_passes():
    passed, hit, defects = pv.judge(_A, guard=None, cards=[
        _card("Dermatitis atópica (Familia y Salud, AEPap)", "eccema del lactante"),
    ])
    assert (passed, hit, defects) == (True, True, [])


def test_an_a_without_its_source_fails():
    passed, hit, _ = pv.judge(_A, guard=None, cards=[_card("Nappy rash (NHS)", "piel")])
    assert not passed and hit is False


def test_an_a_with_an_off_topic_card_fails_like_in_the_gate():
    passed, hit, defects = pv.judge(_A, guard=None, cards=[
        _card("Dermatitis atópica (Familia y Salud, AEPap)", "eccema"),
        _card("Colic (NHS)", "llanto de la tarde"),
    ])
    assert hit and not passed
    assert any("no habla del tema" in d for d in defects)


def test_an_a_stopped_by_the_guard_fails():
    passed, hit, defects = pv.judge(_A, guard="red_flag:choking", cards=[])
    assert not passed and hit is False and "red_flag:choking" in defects[0]


def test_a_b_under_the_cut_fails_and_a_b_with_nothing_passes():
    assert pv.judge(_B, guard=None, cards=[_card("Conjuntivitis", "x")])[0] is False
    assert pv.judge(_B, guard=None, cards=[])[0] is True


def test_a_b_stopped_by_the_guard_is_a_refusal():
    assert pv.judge(_B, guard="age_scope", cards=[])[0] is True


# --- read only, no generation, the gate's retrieval --------------------------------


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


def _offline(monkeypatch, log, matches, embedded):
    from adelia.agent import graph

    monkeypatch.setattr(pv, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(graph, "AsyncSessionLocal", lambda: _Session(log))

    async def _embed(texts):
        embedded.extend(texts)
        return [[float(len(t))] * 1024 for t in texts]

    far = _match("Lejana", 0.31)  # one fragment, whichever text finds it

    async def _retrieve(session, **kwargs):
        await session.execute("SELECT evidence")
        if kwargs["max_distance"] >= 1.0:  # the diagnostic, uncut search
            return [*matches, far]
        return [m for m in matches if m.distance <= kwargs["max_distance"]]

    async def _translate(text, locale, **kwargs):
        return f"(es) {text}"

    monkeypatch.setattr(pv, "embed_with_retry", _embed)
    monkeypatch.setattr(pv, "retrieve_evidence", _retrieve)
    monkeypatch.setattr(pv, "corpus_query", _translate)


async def test_every_session_is_read_only_before_its_first_query(monkeypatch):
    from adelia.config import settings

    log: list[list[str]] = []
    embedded: list[str] = []
    monkeypatch.setattr(settings, "lay_query_expansion", True)
    _offline(monkeypatch, log, [_match("Dermatitis atópica (AEPap)", 0.12, "eccema")], embedded)

    verdict = await pv.preview(_A, cache={}, recording=None)

    assert log and all(s[0] == "SET TRANSACTION READ ONLY" for s in log)
    assert verdict.passed and verdict.guard is None
    assert [c["title"] for c in verdict.cards] == ["Dermatitis atópica (AEPap)"]
    assert verdict.cards[0]["distance"] == pytest.approx(0.12)
    # Production's lexicon setting is used as it is: her sentence plus the terms.
    assert len(verdict.searched) == 2 and "eccema" in verdict.searched[1]
    assert [t for t, _ in verdict.nearest] == ["Dermatitis atópica (AEPap)", "Lejana"]


async def test_the_cut_offs_are_production_s_and_never_generation(monkeypatch):
    """The model that answers is never called: the router is a stub and the
    answer a constant. conftest switches the routing model off, so a live
    routing call would raise here."""
    from adelia.config import settings
    from adelia.services import chat_orchestrator

    def _explode(*args, **kwargs):
        raise AssertionError("the preview must not generate")

    monkeypatch.setattr(chat_orchestrator, "_stream_llm_tokens", _explode)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(settings, "evidence_max_distance", 0.15)
    log: list[list[str]] = []
    _offline(monkeypatch, log, [_match("Dermatitis atópica (AEPap)", 0.17, "eccema")], [])

    verdict = await pv.preview(_A, cache={}, recording=None)
    assert verdict.cards == [] and not verdict.passed
    assert verdict.nearest[0] == ("Dermatitis atópica (AEPap)", 0.17)


async def test_a_guarded_question_searches_nothing(monkeypatch):
    async def _no(*args, **kwargs):
        raise AssertionError("a guarded question reached retrieval")

    monkeypatch.setattr(pv, "embed_with_retry", _no)
    monkeypatch.setattr(pv, "retrieve_evidence", _no)
    red = GoldenQuestion("A91", "A", "Se atragantó y no puede toser", age_months=11,
                         expect_source="x", rationale="doble")
    older = GoldenQuestion("B91", "B", "Mi hijo de 7 años no duerme", age_months=84,
                           kind="age_band", rationale="doble")
    v_red = await pv.preview(red, cache={}, recording=None)
    v_old = await pv.preview(older, cache={}, recording=None)
    assert v_red.guard == "red_flag:choking" and not v_red.passed
    assert v_old.guard == "age_scope" and v_old.passed
    assert v_red.searched == v_old.searched == []


# --- the run and its exit status -----------------------------------------------


async def test_exit_status_is_one_when_any_question_fails_and_it_pauses(monkeypatch):
    pauses: list[float] = []
    outcome = {"A90": True, "B90": False}

    async def _preview(q, *, cache, recording):
        return pv.Verdict(q.id, q.group, q.locale, q.question, passed=outcome[q.id])

    async def _pause(seconds):
        pauses.append(seconds)

    async def _dispose():
        return None

    monkeypatch.setattr(pv, "select", lambda ids: [_A, _B])
    monkeypatch.setattr(pv, "preview", _preview)
    monkeypatch.setattr(pv, "_pause", _pause)
    monkeypatch.setattr(pv, "_dispose", _dispose)
    args = argparse.Namespace(ids=None, questions=None, export=None, record=None, json=None)
    assert await pv.main_async(args) == 1
    assert pauses == [pv.PAUSE_SECONDS] and pv.PAUSE_SECONDS == 2.0
    outcome["B90"] = True
    assert await pv.main_async(args) == 0


async def test_the_recording_has_the_fixture_shape(monkeypatch, tmp_path):
    """--record writes what tests/fixtures/golden_query_embeddings.json holds
    for these ids: the question's vector, and for French or English the
    Spanish text the corpus is searched with and its vector. A guarded
    question is embedded for the recording only (the gate needs a vector for
    every A and B id, B7 and B12 included)."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    embedded: list[str] = []
    _offline(monkeypatch, [], [], embedded)

    async def _dispose():
        return None

    fr = GoldenQuestion("A92", "A", "Il a des croûtes de lait", locale="fr", age_months=2,
                        expect_source="costra láctea", rationale="doble")
    older = GoldenQuestion("B91", "B", "Mi hijo de 7 años no duerme", age_months=84,
                           kind="age_band", rationale="doble")
    monkeypatch.setattr(pv, "select", lambda ids: [_A, fr, older])
    monkeypatch.setattr(pv, "_pause", lambda s: _dispose())
    monkeypatch.setattr(pv, "_dispose", _dispose)
    out = tmp_path / "vectors.json"
    args = argparse.Namespace(ids=None, questions=None, export=None, record=str(out), json=None)
    await pv.main_async(args)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"model", "questions", "embeddings", "corpus_queries", "corpus_embeddings"}
    assert data["model"] == settings.mistral_embed_model
    assert data["questions"] == {"A90": _A.question, "A92": fr.question, "B91": older.question}
    assert all(len(v) == 1024 for v in data["embeddings"].values())
    assert data["corpus_queries"] == {"A92": "(es) Il a des croûtes de lait"}
    assert set(data["corpus_embeddings"]) == {"A92"}
    # The French question's own vector is of what she wrote, not the translation.
    assert data["embeddings"]["A92"][0] == float(len(fr.question))
    assert data["corpus_embeddings"]["A92"][0] == float(len("(es) Il a des croûtes de lait"))


async def test_a_run_that_cannot_embed_exits_two_not_one(monkeypatch, capsys):
    """No key, or the provider down: "could not measure" (2), never mistaken
    for "a question failed" (1), the same split golden_gate.sh makes."""
    from adelia.agent.graph import GraphUnavailable

    async def _down(q, *, cache, recording):
        raise GraphUnavailable("embedding failed")

    async def _dispose():
        return None

    monkeypatch.setattr(pv, "select", lambda ids: [_A, _B])
    monkeypatch.setattr(pv, "preview", _down)
    monkeypatch.setattr(pv, "_dispose", _dispose)
    args = argparse.Namespace(ids=None, questions=None, export=None, record=None, json=None)
    assert await pv.main_async(args) == 2
    assert "A90" in capsys.readouterr().out


# --- without a model (2026-11-06) ----------------------------------------------
#
# The candidate evaluation (docs/GOLDEN_GATE_DESPLIEGUE.md) runs this preview with
# and without a candidate corpus and must not spend a model call: the only call
# it made besides the embeddings was the corpus translation of a French or
# English question. With --no-model that is the translation recorded in the
# fixture (made by the production model when the vectors were recorded), or
# the question as she wrote it, said out loud.


def _explode_translation(monkeypatch):
    async def _no(*args, **kwargs):
        raise AssertionError("the preview without a model asked a model to translate")

    monkeypatch.setattr(pv, "corpus_query", _no)


_FR = GoldenQuestion("A93", "A", "Il a des croûtes de lait", locale="fr", age_months=2,
                     expect_source="costra láctea", rationale="sin modelo")


async def test_without_a_model_a_recorded_translation_is_searched(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    embedded: list[str] = []
    _offline(monkeypatch, [], [], embedded)
    _explode_translation(monkeypatch)
    monkeypatch.setattr(pv, "NO_MODEL", True)
    cache = {(_FR.question, "fr"): "Tiene costra láctea"}
    verdict = await pv.preview(_FR, cache=cache, recording=None)
    assert verdict.searched == ["Tiene costra láctea"] and not verdict.untranslated


async def test_without_a_model_an_unrecorded_question_is_searched_as_written(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    embedded: list[str] = []
    _offline(monkeypatch, [], [], embedded)
    _explode_translation(monkeypatch)
    monkeypatch.setattr(pv, "NO_MODEL", True)
    verdict = await pv.preview(_FR, cache={}, recording=None)
    assert verdict.searched == [_FR.question] and verdict.untranslated
    assert "sin traducir" in pv._fmt_verdict(_FR, verdict)


def test_the_recorded_translations_come_from_the_fixture_only_for_the_current_wording():
    gate_fr = next(q for q in GOLDEN_SET if q.locale == "fr" and q.group == "A")
    found = pv.recorded_translations([gate_fr, _FR])
    assert set(found) == {(gate_fr.question, "fr")}
    assert found[(gate_fr.question, "fr")] != gate_fr.question


async def test_main_without_a_model_fills_the_translations_and_says_so(monkeypatch, capsys):
    seen: dict = {}

    async def _preview(q, *, cache, recording):
        seen.update(cache)
        seen["no_model"] = pv.NO_MODEL
        return pv.Verdict(q.id, q.group, q.locale, q.question, passed=True)

    async def _dispose():
        return None

    gate_fr = next(q for q in GOLDEN_SET if q.locale == "fr" and q.group == "A")
    monkeypatch.setattr(pv, "NO_MODEL", False)
    monkeypatch.setattr(pv, "select", lambda ids: [gate_fr])
    monkeypatch.setattr(pv, "preview", _preview)
    monkeypatch.setattr(pv, "_dispose", _dispose)
    args = argparse.Namespace(
        ids=None, questions=None, export=None, record=None, json=None, no_model=True
    )
    assert await pv.main_async(args) == 0
    assert seen["no_model"] is True and (gate_fr.question, "fr") in seen
    assert "sin modelo" in capsys.readouterr().out
