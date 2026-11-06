"""tests/record_golden_embeddings.py: the fixture the golden set runs offline from.

`--merge FILE` adds the vectors scripts/preview_golden_candidates.py recorded
in production for questions the fixture lacks, with no key: the candidates of
2026-11-06 get their vectors from the run that measured them. It never touches
an entry the fixture already has (a full re-record would re-translate every
French and English question and quietly change what they measure), and it
refuses a vector it cannot vouch for: another embedding model, another
dimension, a question whose wording changed since it was embedded.
"""
from __future__ import annotations

import json

import pytest

from adelia.clinical.golden import CANDIDATES, GOLDEN_SET, written_2026_11_06
from tests import record_golden_embeddings as rec

_DIM = 1024


def _vec(x: float = 0.0) -> list[float]:
    return [x] * _DIM


def _fixture() -> dict:
    a1 = next(q for q in GOLDEN_SET if q.id == "A1")
    a7 = next(q for q in GOLDEN_SET if q.id == "A7")
    return {
        "model": "mistral-embed",
        "questions": {"A1": a1.question, "A7": a7.question},
        "embeddings": {"A1": _vec(1.0), "A7": _vec(7.0)},
        "corpus_queries": {"A7": "¿Necesita hierro?"},
        "corpus_embeddings": {"A7": _vec(7.5)},
    }


def _recorded(*qs, model: str = "mistral-embed") -> dict:
    out = {"model": model, "questions": {}, "embeddings": {}, "corpus_queries": {},
           "corpus_embeddings": {}}
    for q in qs:
        out["questions"][q.id] = q.question
        out["embeddings"][q.id] = _vec(0.5)
        if q.locale != "es":
            out["corpus_queries"][q.id] = f"(es) {q.question}"
            out["corpus_embeddings"][q.id] = _vec(0.25)
    return out


def _cand(qid: str):
    """A 2026-11-06 question, whether it is still a candidate or in the gate."""
    return next(q for q in written_2026_11_06() if q.id == qid)


def test_the_live_recording_covers_the_gate_and_the_candidates():
    ids = [q.id for q in rec.asked_questions()]
    assert ids == [q.id for q in (*GOLDEN_SET, *CANDIDATES) if q.group in ("A", "B")]


def test_merge_adds_what_is_missing_and_leaves_the_rest_alone():
    fixture = _fixture()
    before = json.dumps(fixture, sort_keys=True)
    merged, added, _ = rec.merge(fixture, _recorded(_cand("A19"), _cand("A20")))
    assert added == ["A19", "A20"]
    assert json.dumps(fixture, sort_keys=True) == before, "the input is not modified"
    assert merged["embeddings"]["A1"] == _vec(1.0) and merged["embeddings"]["A7"] == _vec(7.0)
    assert merged["corpus_queries"]["A7"] == "¿Necesita hierro?"
    assert merged["embeddings"]["A19"] == _vec(0.5)
    assert "A19" not in merged["corpus_queries"]  # Spanish: searched as written
    assert merged["corpus_queries"]["A20"].startswith("(es) ")
    assert list(merged["questions"])[:2] == ["A1", "A7"]


def test_an_id_the_fixture_already_has_is_kept_not_replaced():
    a1 = next(q for q in GOLDEN_SET if q.id == "A1")
    merged, added, _ = rec.merge(_fixture(), _recorded(a1))
    assert added == [] and merged["embeddings"]["A1"] == _vec(1.0)


def test_a_reworded_question_is_refused():
    recorded = _recorded(_cand("A19"))
    recorded["questions"]["A19"] = "otra redacción"
    with pytest.raises(rec.MergeError, match="A19"):
        rec.merge(_fixture(), recorded)


def test_another_embedding_model_is_refused():
    with pytest.raises(rec.MergeError, match="model"):
        rec.merge(_fixture(), _recorded(_cand("A19"), model="bge-m3"))


def test_a_vector_of_another_size_is_refused():
    recorded = _recorded(_cand("A19"))
    recorded["embeddings"]["A19"] = [0.0] * 768
    with pytest.raises(rec.MergeError, match="1024"):
        rec.merge(_fixture(), recorded)


def test_an_unknown_id_is_refused():
    recorded = _recorded(_cand("A19"))
    recorded["questions"]["Z9"] = "?"
    recorded["embeddings"]["Z9"] = _vec()
    with pytest.raises(rec.MergeError, match="Z9"):
        rec.merge(_fixture(), recorded)


def test_a_translated_question_without_its_corpus_vector_is_refused():
    recorded = _recorded(_cand("A20"))
    del recorded["corpus_embeddings"]["A20"]
    with pytest.raises(rec.MergeError, match="A20"):
        rec.merge(_fixture(), recorded)


def test_a_translated_question_whose_translation_fell_back_is_left_out_by_name():
    """corpus_query returns her own words when the provider does not answer; the
    recorder does not record those, and the merge must not lose the others for it.
    Left out, the gate skips naming it until it is measured again."""
    recorded = _recorded(_cand("A19"), _cand("A20"))
    del recorded["corpus_queries"]["A20"], recorded["corpus_embeddings"]["A20"]
    merged, added, skipped = rec.merge(_fixture(), recorded)
    assert added == ["A19"] and skipped == ["A20"]
    assert "A20" not in merged["embeddings"]


def test_merging_every_2026_11_06_question_covers_them_all():
    nov6 = written_2026_11_06()
    merged, added, _ = rec.merge(_fixture(), _recorded(*nov6))
    assert added == [q.id for q in nov6]
    assert all(len(merged["embeddings"][q.id]) == _DIM for q in nov6)
    assert {q.id for q in nov6 if q.locale != "es"} == set(merged["corpus_queries"]) - {"A7"}


def test_the_merge_command_writes_the_fixture_and_needs_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    out = tmp_path / "golden_query_embeddings.json"
    out.write_text(json.dumps(_fixture(), ensure_ascii=False) + "\n", encoding="utf-8")
    src = tmp_path / "candidate_vectors.json"
    src.write_text(json.dumps(_recorded(_cand("B18"))), encoding="utf-8")
    monkeypatch.setattr(rec, "OUT", out)
    assert rec.cli(["--merge", str(src)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "B18" in data["embeddings"] and data["embeddings"]["A1"] == _vec(1.0)
    src.write_text(json.dumps(_recorded(_cand("B18"), model="bge-m3")), encoding="utf-8")
    assert rec.cli(["--merge", str(src)]) == 1
