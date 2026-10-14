"""Unit tests for evidence_retrieval formatting + seed loader structure.

PG-gated retrieval tests deferred (need real pgvector index). Pure logic tested here.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from adelia.config import settings
from adelia.enrichment.evidence_retrieval import (
    EVIDENCE_CANDIDATE_CAP,
    EvidenceMatch,
    dedupe_by_source,
    evidence_citations_for_response,
    format_evidence_for_prompt,
    retrieve_evidence,
    within_relative_margin,
)


def _fake_match(i: int) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_title=f"Sample Guideline {i}",
        organization="ADA",
        publication_year=2024,
        url=f"https://example.com/g{i}",
        content=f"Clinical evidence snippet number {i}. " * 5,
        chunk_index=0,
        distance=0.2 + (i * 0.05),
    )


def test_format_evidence_empty_returns_empty_string():
    assert format_evidence_for_prompt([]) == ""


def test_format_evidence_has_citation_tags():
    matches = [_fake_match(1), _fake_match(2)]
    out = format_evidence_for_prompt(matches)
    assert "[ev_1]" in out
    assert "[ev_2]" in out
    assert "ADA" in out
    assert "Clinical evidence snippet number 1" in out


def test_format_evidence_preserves_year():
    matches = [_fake_match(1)]
    out = format_evidence_for_prompt(matches)
    assert "2024" in out


def test_citations_for_response_returns_list_of_dicts():
    matches = [_fake_match(1), _fake_match(2)]
    citations = evidence_citations_for_response(matches)
    assert len(citations) == 2
    assert citations[0]["tag"] == "ev_1"
    assert citations[1]["tag"] == "ev_2"
    assert citations[0]["organization"] == "ADA"
    assert citations[0]["url"].startswith("https://")
    assert citations[0]["distance"] >= 0


def test_citations_snippet_truncated():
    """Snippets should be ≤ 280 chars to keep response payload light."""
    matches = [_fake_match(1)]
    citations = evidence_citations_for_response(matches)
    assert len(citations[0]["snippet"]) <= 280


def test_evidence_seed_json_loadable_and_valid():
    """Seed file should parse + have at least 5 sources covering core specialties."""
    seed_path = Path(__file__).parent.parent / "adelia" / "enrichment" / "data" / "evidence_seed.json"
    with seed_path.open() as f:
        data = json.load(f)
    sources = data.get("sources", [])
    assert len(sources) >= 8
    specialties_seen = set()
    for src in sources:
        assert "title" in src
        assert "source_type" in src
        assert src["source_type"] in {"guideline", "paper", "protocol", "reference"}
        assert "chunks" in src
        assert len(src["chunks"]) >= 1
        for chunk_text in src["chunks"]:
            assert len(chunk_text) > 20
        specialties_seen.update(src.get("specialties", []))
    # Core specialties covered in seed
    assert "endocrinology" in specialties_seen
    assert "cardiology" in specialties_seen
    assert "pediatrics" in specialties_seen


def test_evidence_seed_sources_have_urls():
    """Every source must have a URL for citation purposes."""
    seed_path = Path(__file__).parent.parent / "adelia" / "enrichment" / "data" / "evidence_seed.json"
    with seed_path.open() as f:
        data = json.load(f)
    for src in data.get("sources", []):
        assert src.get("url", "").startswith("http")


# ---------------------------------------------------------------------------
# One citation per source, and no filler (public demo, 2026-10-14)
#
# Pure logic: no key, no database. The same behaviour against Postgres, with
# vectors placed at chosen distances, is in test_evidence_threshold_integration.
# ---------------------------------------------------------------------------


def _m(source: UUID, distance: float, label: str = "", title: str = "T") -> EvidenceMatch:
    """A match for `source` at `distance`; `label` makes its text unique."""
    return EvidenceMatch(
        chunk_id=uuid4(),
        source_id=source,
        source_title=title,
        organization="ORG",
        publication_year=2022,
        url=None,
        content=f"fragment {label or distance}",
        chunk_index=0,
        distance=distance,
    )


A, B, C, D, E = (uuid4() for _ in range(5))


def test_dedupe_keeps_the_best_fragment_of_each_source_in_order():
    a1, a2, a3 = _m(A, 0.05), _m(A, 0.06), _m(A, 0.07)
    b1 = _m(B, 0.08)
    assert dedupe_by_source([a1, a2, a3, b1], top_k=4) == [a1, b1]


def test_dedupe_keeps_going_down_the_list_until_top_k_distinct_sources():
    """Three fragments of one guideline must not eat three of the four slots."""
    ranked = [
        _m(A, 0.05), _m(A, 0.06), _m(A, 0.07), _m(B, 0.08), _m(C, 0.09), _m(D, 0.10), _m(E, 0.11),
    ]
    kept = dedupe_by_source(ranked, top_k=4)
    assert [m.source_id for m in kept] == [A, B, C, D]
    assert kept[0] is ranked[0]


def test_dedupe_returns_fewer_rather_than_repeating_a_source():
    """Four cards from two sources say more than the evidence does."""
    ranked = [_m(A, 0.05), _m(A, 0.06), _m(B, 0.07), _m(B, 0.08), _m(A, 0.09)]
    kept = dedupe_by_source(ranked, top_k=4)
    assert [m.source_id for m in kept] == [A, B]


def test_dedupe_keys_on_source_id_never_on_the_title():
    """The corpus has titles shared by different sources; both are real."""
    title = "La adaptación a la escuela"
    same_title = [_m(A, 0.05, title=title), _m(B, 0.06, title=title)]
    assert len(dedupe_by_source(same_title, top_k=4)) == 2
    # And one source under two titles (a retitled fragment) is still one source.
    one_source = [_m(A, 0.05, title="x"), _m(A, 0.06, title="y")]
    assert len(dedupe_by_source(one_source, top_k=4)) == 1


def test_dedupe_edges():
    assert dedupe_by_source([], top_k=4) == []
    assert dedupe_by_source([_m(A, 0.05)], top_k=0) == []
    assert dedupe_by_source([_m(A, 0.05)], top_k=-1) == []
    only = _m(A, 0.05)
    assert dedupe_by_source([only], top_k=10) == [only]


def test_the_margin_drops_what_is_too_far_behind_the_best():
    near, edge, far = _m(A, 0.25), _m(B, 0.375), _m(C, 0.5)
    # 0.25 + 0.125 = 0.375 exactly: a match exactly one margin behind stays.
    assert within_relative_margin([near, edge, far], 0.125) == [near, edge]


def test_the_margin_is_anchored_to_the_minimum_not_to_the_first_element():
    best, mid, far = _m(A, 0.05), _m(B, 0.10), _m(C, 0.20)
    unsorted = [far, mid, best]
    # Order kept, best found anywhere: 0.05 + 0.08 = 0.13 keeps best and mid.
    assert within_relative_margin(unsorted, 0.08) == [mid, best]


def test_a_single_match_is_always_within_its_own_margin():
    only = _m(A, 0.18)
    assert within_relative_margin([only], 0.0) == [only]


def test_the_margin_can_be_switched_off_and_handles_nothing():
    ranked = [_m(A, 0.01), _m(B, 0.19)]
    assert within_relative_margin(ranked, None) == ranked
    assert within_relative_margin([], 0.08) == []


def test_the_default_margin_is_no_tighter_than_the_measured_same_topic_spread():
    """0.0557 is the widest gap, behind the best, of any of the 2nd to 4th
    same-topic sources in the dev corpus (see the comment in config.py). A
    tidy-up that tightens the margin below it starts dropping sources a
    question legitimately has. It must also stay inside the absolute cut-off,
    or it does nothing."""
    assert 0.0557 <= settings.evidence_relative_margin < settings.evidence_max_distance


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _VectorOnlySession:
    """Answers the vector statement from `matches`, honouring `LIMIT :k`.

    It records every `k` it was asked for, which is how the tests see whether a
    second, wider statement was issued.
    """

    def __init__(self, matches):
        self.rows = [
            {
                "chunk_id": m.chunk_id, "source_id": m.source_id, "source_title": m.source_title,
                "organization": m.organization, "publication_year": m.publication_year,
                "url": m.url, "content": m.content, "chunk_index": m.chunk_index,
                "distance": m.distance,
            }
            for m in matches
        ]
        self.limits: list[int] = []

    async def execute(self, stmt, params):
        self.limits.append(params["k"])
        return _Result(self.rows[: params["k"]])


@pytest.fixture(autouse=True)
def _vector_path_only(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", False)


async def _retrieve(matches, **kwargs):
    session = _VectorOnlySession(matches)
    kwargs.setdefault("top_k", 4)
    kwargs.setdefault("max_distance", 0.19)
    kwargs.setdefault("relative_margin", 0.08)
    return session, await retrieve_evidence(session, query_embedding=[0.0], **kwargs)


async def test_distinct_sources_cost_one_statement_for_exactly_top_k_rows():
    rows = [_m(A, 0.05), _m(B, 0.06), _m(C, 0.07), _m(D, 0.08), _m(E, 0.09)]
    session, got = await _retrieve(rows)
    assert session.limits == [4]
    assert [m.source_id for m in got] == [A, B, C, D]


async def test_a_repeated_source_widens_once_and_fills_with_distinct_sources():
    rows = [_m(A, 0.05, "a-best"), _m(A, 0.06), _m(A, 0.07), _m(B, 0.08), _m(C, 0.09), _m(D, 0.10)]
    session, got = await _retrieve(rows)
    assert session.limits == [4, EVIDENCE_CANDIDATE_CAP]
    assert [m.source_id for m in got] == [A, B, C, D]
    assert got[0].content == "fragment a-best"


async def test_the_sleep_question_shape_one_good_source_is_one_citation():
    """Three fragments of the safe-sleep guideline and a fourth thing at 0.17.

    0.17 is inside the absolute cut-off (0.19), which is how it reached the
    parent on 2026-10-14. It is 0.12 behind the best, so the margin removes it,
    and with nothing more to find the answer is ONE card.
    """
    rows = [_m(A, 0.05), _m(A, 0.06), _m(A, 0.07), _m(B, 0.17)]
    session, got = await _retrieve(rows)
    assert [m.source_id for m in got] == [A]
    assert session.limits == [4], "the margin already cut the tail: nothing farther can pass"


async def test_an_exhausted_cutoff_does_not_widen_and_returns_fewer():
    session, got = await _retrieve([_m(A, 0.05), _m(B, 0.06)])
    assert session.limits == [4]
    assert [m.source_id for m in got] == [A, B]


async def test_fewer_distinct_sources_than_top_k_is_fewer_cards_not_repeats():
    rows = [_m(A, 0.05), _m(A, 0.06), _m(A, 0.07), _m(B, 0.08)]
    session, got = await _retrieve(rows)
    assert session.limits == [4, EVIDENCE_CANDIDATE_CAP]
    assert [m.source_id for m in got] == [A, B]


async def test_the_widening_is_capped():
    rows = [_m(A, 0.05 + i * 0.0001) for i in range(EVIDENCE_CANDIDATE_CAP + 36)]
    session, got = await _retrieve(rows)
    assert session.limits == [4, EVIDENCE_CANDIDATE_CAP]
    assert [m.source_id for m in got] == [A]


async def test_no_candidates_is_no_citations_and_one_statement():
    session, got = await _retrieve([])
    assert got == [] and session.limits == [4]


async def test_top_k_zero_returns_nothing():
    _, got = await _retrieve([_m(A, 0.05)], top_k=0)
    assert got == []


async def test_without_a_margin_only_the_cut_off_and_the_dedup_apply(monkeypatch):
    """None is "no relative criterion", whatever the setting says: the callers
    opt in by passing settings.evidence_relative_margin (tested at each call
    site), so a stored vector used as a query, which matches itself at 0.0,
    still sees its neighbours."""
    rows = [_m(A, 0.0), _m(B, 0.12)]
    monkeypatch.setattr(settings, "evidence_relative_margin", 0.01)
    bare = await retrieve_evidence(
        _VectorOnlySession(rows), query_embedding=[0.0], top_k=4, max_distance=0.19
    )
    assert [m.source_id for m in bare] == [A, B]
    with_margin = await retrieve_evidence(
        _VectorOnlySession(rows), query_embedding=[0.0], top_k=4, max_distance=0.19,
        relative_margin=settings.evidence_relative_margin,
    )
    assert [m.source_id for m in with_margin] == [A]


async def test_the_model_and_the_parent_read_the_same_fragment_after_dedup():
    """The literal quote is the guarantee: prompt and card come from one list."""
    rows = [_m(A, 0.05, "a1"), _m(A, 0.06, "a2"), _m(B, 0.07, "b1"), _m(B, 0.08, "b2")]
    _, got = await _retrieve(rows)
    prompt = format_evidence_for_prompt(got)
    cards = evidence_citations_for_response(got)
    assert [c["chunk_id"] for c in cards] == [str(m.chunk_id) for m in got]
    assert [c["source_id"] for c in cards] == [str(A), str(B)]
    for tag, match, card in zip(("ev_1", "ev_2"), got, cards, strict=True):
        assert card["tag"] == tag
        # The text under [ev_N] in the prompt is the text the card quotes.
        block = prompt.split(f"[{tag}] ", 1)[1].split("\n")[1]
        assert block == match.content and card["snippet"] == match.content[:280]
    assert "fragment a1" in prompt and "fragment a2" not in prompt
