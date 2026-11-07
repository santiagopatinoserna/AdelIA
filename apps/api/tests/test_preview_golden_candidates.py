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


# --- --explain (2026-11-07) ----------------------------------------------------
#
# The first measurement of the 2026-11-06 candidates on the server said which
# questions broke (A1, A5, A13, A37 lost their source; B6 got cards under the
# cut) but not which sources did it, and the next run costs a trip to the
# server. --explain prints, for the questions named, the nearest sources with
# their distance, whether each is under the cut and the file it comes from, so
# one run brings back everything needed to fix the files.


def test_origins_name_the_file_of_every_title_in_data_and_the_candidates(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "evidence_sueno.json").write_text(
        json.dumps({"sources": [{"title": "Sueño seguro (AEP)"}]}), encoding="utf-8")
    (data / "lab_reference_ranges.json").write_text(
        json.dumps({"sources": [{"title": "No es del corpus"}]}), encoding="utf-8")
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({"sources": [{"title": "Muerte en la cuna (Helsenorge)"}]}),
                    encoding="utf-8")
    origins = pv.origin_index([cand], data_dir=data)
    assert origins["Sueño seguro (AEP)"] == "data/evidence_sueno.json"
    assert origins["Muerte en la cuna (Helsenorge)"] == "candidato cand.json"
    assert "No es del corpus" not in origins
    assert pv.origin_of("Una página del crawler", origins) == "sin fichero (crawler u otra carga)"


async def test_explain_widens_the_nearest_and_keeps_the_cut_visible(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    near = [_match(f"Fuente {n}", 0.10 + n / 100, "eccema") for n in range(12)]
    _offline(monkeypatch, [], near, [])
    monkeypatch.setattr(pv, "EXPLAIN", True)
    verdict = await pv.preview(_A, cache={}, recording=None)
    assert len(verdict.nearest) == pv.EXPLAIN_K == 10
    assert verdict.nearest[0] == ("Fuente 0", 0.10)
    assert verdict.expect_source == "dermatitis atópica"
    monkeypatch.setattr(pv, "EXPLAIN", False)
    verdict = await pv.preview(_A, cache={}, recording=None)
    assert len(verdict.nearest) == pv.NEAREST_K


def test_explain_prints_distance_cut_and_file_for_every_nearest_source():
    v = pv.Verdict("A5", "A", "es", "¿Cómo debe dormir?", expect_source="sueño",
                   cards=[{"title": "Krybbedød (Helsenorge)", "distance": 0.08}],
                   nearest=[("Krybbedød (Helsenorge)", 0.08), ("Sueño seguro (AEP)", 0.10)],
                   origins={"Krybbedød (Helsenorge)": "candidato respiratorio_sueno.json",
                            "Sueño seguro (AEP)": "data/evidence_respiratorio_sueno.json"})
    q = GoldenQuestion("A5", "A", "¿Cómo debe dormir?", age_months=3, expect_source="sueño")
    text = pv._fmt_verdict(q, v)
    line = next(x for x in text.splitlines() if "Krybbedød" in x and "cercana" in x)
    assert "0.0800" in line and "bajo el corte" in line and "respiratorio_sueno.json" in line
    line = next(x for x in text.splitlines() if "Sueño seguro" in x and "cercana" in x)
    assert "esperada" in line and "data/evidence_respiratorio_sueno.json" in line
    assert "bajo el corte" not in line


def test_origins_read_a_list_of_files_as_well_as_a_glob(tmp_path):
    for name in ("seguridad.json", "neonatal.json", "salud.json"):
        (tmp_path / name).write_text('{"sources": []}', encoding="utf-8")
    got = pv._origin_files(f"{tmp_path / 'seguridad.json'}, {tmp_path / 'n*.json'}")
    assert got == [tmp_path / "neonatal.json", tmp_path / "seguridad.json"]


# --- --explain, one search at a time (2026-11-07) ------------------------------------
#
# The second server run lost A21 («Desde que nació le llora un ojo y se le llena
# de legañas») with the candidates, while its --explain showed the three
# tear-duct sources on top at 0.109 to 0.120. The nearest list merged every text
# the graph searches: her sentence, the lay lexicon's widening (which adds
# «conducto lagrimal, lagrimeo») and the implicit-subject rewrite. The gate does
# not search that way: it embeds every variant with the one vector recorded for
# her question (tests/test_rag_golden.py, _recorded_embed), so only her own
# sentence decides, and there the crying sources came first. Each search is now
# its own block with its own top, and the gate's own search is one of them.


def _by_text(monkeypatch, tops: dict[str, list[EvidenceMatch]], embedded: list[str]):
    """Retrieval that answers per text embedded: the first key found in the text."""
    from adelia.agent import graph

    log: list[list[str]] = []
    monkeypatch.setattr(pv, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(graph, "AsyncSessionLocal", lambda: _Session(log))

    async def _embed(texts):
        out = []
        for t in texts:
            embedded.append(t)
            out.append([float(len(embedded) - 1)] * 1024)
        return out

    def _top(vector):
        n = int(vector[0])
        text = "gate" if n < 0 else embedded[n]
        return next(v for k, v in tops.items() if k in text)

    async def _retrieve(session, **kwargs):
        await session.execute("SELECT evidence")
        found = [m for m in _top(kwargs["query_embedding"]) if m.distance <= kwargs["max_distance"]]
        if kwargs.get("cited_sources"):
            found = [m for m in found if m.source_id in set(kwargs["cited_sources"])]
        return found[: kwargs["top_k"]]

    monkeypatch.setattr(pv, "embed_with_retry", _embed)
    monkeypatch.setattr(pv, "retrieve_evidence", _retrieve)
    return log


_A21 = GoldenQuestion(
    "A91", "A", "Desde que nació le llora un ojo y se le llena de legañas. ¿Se le pasará solo?",
    age_months=2, expect_source="conducto lagrimal|Lagrimeo", rationale="doble",
)


async def test_explain_shows_every_search_of_the_graph_with_its_own_top(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(pv, "EXPLAIN", True)
    llanto = _match("Llanto (Kind en Gezin)", 0.1797)
    lagrimeo = _match("Lagrimeo en el lactante (AEPap)", 0.1816)
    bloqueado = _match("Conducto lagrimal bloqueado (AAP)", 0.1092)
    embedded: list[str] = []
    log = _by_text(monkeypatch, {
        "gate": [llanto, lagrimeo],
        "signos de alarma": [lagrimeo],  # first: the warning text carries the widening too
        "conducto lagrimal": [bloqueado, llanto],
        "Mi bebé de 2 meses": [lagrimeo, llanto],
        "Desde que nació": [llanto, lagrimeo],
    }, embedded)
    monkeypatch.setattr(pv, "recorded_vector", lambda q: [-1.0] * 1024)

    v = await pv.preview(_A21, cache={}, recording=None)

    assert all(s[0] == "SET TRANSACTION READ ONLY" for s in log)
    names = [b["name"] for b in v.queries]
    assert names == ["principal", "léxico de madre", "sujeto implícito", "avisos", "gate"]
    blocks = {b["name"]: b for b in v.queries}
    assert blocks["principal"]["text"] == _A21.question
    assert blocks["principal"]["top"][0] == ["Llanto (Kind en Gezin)", 0.1797]
    assert "conducto lagrimal" in blocks["léxico de madre"]["text"]
    assert blocks["léxico de madre"]["top"][0] == ["Conducto lagrimal bloqueado (AAP)", 0.1092]
    subject = blocks["sujeto implícito"]
    assert subject["text"].startswith("Mi bebé de 2 meses")
    assert subject["cut"] == min(settings.evidence_max_distance,
                                 settings.implicit_subject_max_distance)
    # The plan's warning search reads only the sources the answer already cites.
    assert "signos de alarma" in blocks["avisos"]["text"]
    assert blocks["avisos"]["top"] == [["Lagrimeo en el lactante (AEPap)", 0.1816]]
    gate = blocks["gate"]
    assert gate["top"][0] == ["Llanto (Kind en Gezin)", 0.1797]
    assert gate["cards"] == ["Llanto (Kind en Gezin)", "Lagrimeo en el lactante (AEPap)"]
    assert "mismo vector" in gate["note"]
    # The verdict is still the graph's: the merged search, untouched by the blocks.
    assert v.passed and v.cards[0]["title"] == "Conducto lagrimal bloqueado (AAP)"


async def test_explain_says_a_search_production_does_not_run_instead_of_running_it(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(settings, "implicit_subject_expansion", False)
    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    monkeypatch.setattr(pv, "EXPLAIN", True)
    embedded: list[str] = []
    _by_text(monkeypatch, {"Desde que nació": [_match("Lagrimeo en el lactante", 0.18)]},
             embedded)
    monkeypatch.setattr(pv, "recorded_vector", lambda q: None)

    v = await pv.preview(_A21, cache={}, recording=None)

    assert embedded == [_A21.question]  # nothing embedded for the explanation alone
    blocks = {b["name"]: b for b in v.queries}
    assert blocks["principal"]["top"] == [["Lagrimeo en el lactante", 0.18]]
    for name in ("léxico de madre", "sujeto implícito", "avisos"):
        assert blocks[name]["top"] == [] and "apagad" in blocks[name]["note"]
    assert blocks["gate"]["top"] == [] and "sin vector grabado" in blocks["gate"]["note"]


def test_the_recorded_vector_is_the_gate_s_own_and_only_for_the_current_wording():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "golden_query_embeddings.json")
                         .read_text(encoding="utf-8"))
    by_id = {q.id: q for q in GOLDEN_SET}
    es = by_id["A21"]
    assert pv.recorded_vector(es) == fixture["embeddings"]["A21"]
    fr = next(q for q in GOLDEN_SET if q.locale == "fr" and q.id in fixture["corpus_embeddings"])
    assert pv.recorded_vector(fr) == fixture["corpus_embeddings"][fr.id]
    reworded = GoldenQuestion("A21", "A", "Otra forma de preguntarlo", age_months=2,
                              expect_source="x", rationale="x")
    assert pv.recorded_vector(reworded) is None


def test_explain_prints_each_search_as_its_own_block():
    v = pv.Verdict("A21", "A", "es", _A21.question, expect_source="conducto lagrimal|Lagrimeo",
                   cards=[{"title": "Conducto lagrimal bloqueado (AAP)", "distance": 0.1092}],
                   nearest=[("Conducto lagrimal bloqueado (AAP)", 0.1092)],
                   origins={"Llanto (Kind en Gezin)": "candidato digestivo_piel.json"},
                   queries=[
                       {"name": "principal", "text": _A21.question, "cut": 0.19,
                        "cards": ["Llanto (Kind en Gezin)"], "note": "",
                        "top": [["Llanto (Kind en Gezin)", 0.1797],
                                ["Lagrimeo en el lactante (AEPap)", 0.1816]]},
                       {"name": "léxico de madre", "text": "", "cut": 0.19, "cards": [],
                        "top": [], "note": "apagado en este entorno"},
                   ])
    q = GoldenQuestion("A21", "A", _A21.question, age_months=2,
                       expect_source="conducto lagrimal|Lagrimeo")
    text = pv._fmt_verdict(q, v)
    head = next(x for x in text.splitlines() if "consulta principal" in x)
    assert "0.19" in head
    row = next(x for x in text.splitlines() if "0.1797" in x)
    assert "bajo el corte" in row and "candidato digestivo_piel.json" in row
    row = next(x for x in text.splitlines() if "0.1816" in x)
    assert "esperada" in row and "fuera del corte" in row
    assert any("léxico de madre" in x and "apagado" in x for x in text.splitlines())


async def test_main_with_explain_maps_the_origins_and_writes_them(monkeypatch, tmp_path, capsys):
    seen: dict = {}

    async def _preview(q, *, cache, recording):
        seen["explain"] = pv.EXPLAIN
        return pv.Verdict(q.id, q.group, q.locale, q.question, passed=True,
                          nearest=[("Sueño seguro (AEP)", 0.1)])

    async def _dispose():
        return None

    monkeypatch.setattr(pv, "select", lambda ids: [_A])
    monkeypatch.setattr(pv, "preview", _preview)
    monkeypatch.setattr(pv, "_dispose", _dispose)
    monkeypatch.setattr(pv, "origin_index",
                        lambda files, **kw: {"Sueño seguro (AEP)": f"{len(files)} ficheros"})
    out = tmp_path / "explain.json"
    args = argparse.Namespace(
        ids="A90", questions=None, export=None, record=None, json=str(out), no_model=True,
        explain=True, origins=None,
    )
    assert await pv.main_async(args) == 0
    assert seen["explain"] is True
    row = json.loads(out.read_text(encoding="utf-8"))[0]
    assert row["origins"] == {"Sueño seguro (AEP)": "0 ficheros"}
