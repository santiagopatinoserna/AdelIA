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
    merge_by_best_distance,
    retrieve_evidence,
    within_relative_margin,
)

from tests.pg_gate import PG_AVAILABLE


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


# --- two queries, the better distance wins (agent/lay_terms.py) -----------------
#
# With settings.lay_query_expansion on, the retrieve step searches her sentence
# and her sentence plus the corpus's clinical terms. The merge is what makes
# the expansion unable to lose a fragment the original found, and unable to
# admit anything past the cut-offs both searches already applied.


def test_the_merge_keeps_each_fragment_at_its_better_distance():
    plain = _m(A, 0.17, "a")
    widened = EvidenceMatch(**{**plain.__dict__, "distance": 0.09})
    merged = merge_by_best_distance([[plain], [widened]], top_k=4, relative_margin=0.08)
    assert merged == [widened]


def test_the_merge_never_loses_what_the_original_found():
    a, b = _m(A, 0.10, "a"), _m(B, 0.12, "b")
    assert merge_by_best_distance([[a, b], []], top_k=4, relative_margin=0.08) == [a, b]


def test_the_merge_ranks_by_distance_and_keeps_one_fragment_per_source():
    a_far, b = _m(A, 0.16, "a-far"), _m(B, 0.12, "b")
    a_near, c = _m(A, 0.08, "a-near"), _m(C, 0.15, "c")
    merged = merge_by_best_distance([[b, a_far], [a_near, c]], top_k=4, relative_margin=0.08)
    assert merged == [a_near, b, c]


def test_the_merge_anchors_the_margin_to_the_best_of_both():
    """What the expansion found well can push a lateral original match out."""
    lateral, good = _m(A, 0.185, "lateral"), _m(B, 0.07, "good")
    merged = merge_by_best_distance([[lateral], [good]], top_k=4, relative_margin=0.08)
    assert merged == [good]


def test_the_merge_honours_top_k_and_no_margin():
    ranked = [_m(s, 0.05 + i / 100, str(i)) for i, s in enumerate((A, B, C, D, E))]
    merged = merge_by_best_distance([ranked[:3], ranked[3:]], top_k=4, relative_margin=None)
    assert [m.source_id for m in merged] == [A, B, C, D]
    assert merge_by_best_distance([[], []], top_k=4, relative_margin=0.08) == []


# --- the warning-signs search adds, it never replaces (agent/warning_signs.py) ---
#
# With settings.warning_signs_retrieval on, a plan whose main search found
# evidence runs a second search for the same topic plus the warning-sign terms.
# What it brings is appended after what the main search found: the main list,
# its order and its [ev_N] numbering are untouched; at most two new fragments,
# never one already there, those of the sources already retrieved first.


def test_warning_fragments_go_after_the_main_ones_and_never_repeat_a_fragment():
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    a, b = _m(A, 0.08, "a"), _m(B, 0.10, "b")
    a_alarm = _m(A, 0.12, "a-alarm")
    assert add_warning_fragments([a, b], [a, a_alarm]) == [a, b, a_alarm]


def test_warning_fragments_prefer_the_sources_already_retrieved():
    """The croup plan cited AEPap; the AEPap paragraph on when to go wins over a
    closer paragraph of a source the plan never used."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    a, b = _m(A, 0.08, "a"), _m(B, 0.10, "b")
    stranger, a_alarm, b_alarm = _m(C, 0.05, "c"), _m(A, 0.15, "a-alarm"), _m(B, 0.11, "b-al")
    got = add_warning_fragments([a, b], [stranger, a_alarm, b_alarm])
    assert got == [a, b, b_alarm, a_alarm]


def test_warning_fragments_are_at_most_two_and_fill_with_other_sources():
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    a = _m(A, 0.08, "a")
    a_alarm, c, d = _m(A, 0.12, "a-alarm"), _m(C, 0.06, "c"), _m(D, 0.07, "d")
    assert add_warning_fragments([a], [c, a_alarm, d]) == [a, a_alarm, c]
    assert add_warning_fragments([a], [c, a_alarm, d], limit=1) == [a, a_alarm]


def test_warning_fragments_add_nothing_to_an_empty_main_search():
    """No evidence stays no evidence: the warning search cannot answer a question."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    assert add_warning_fragments([], [_m(A, 0.05, "a")]) == []
    a = _m(A, 0.08, "a")
    assert add_warning_fragments([a], []) == [a]


# --- the paragraph on when to go, of a guideline already cited -------------------
#
# Measured in prod on 2026-11-06 (demo retrieve node, warning search on): "Tiene
# tos de perro por la noche, ¿qué puedo hacer en casa?" cited AEPap, AEP and SEUP,
# and the warning search added only "síntomas y evolución de la laringitis". The
# SEUP "cuidados en casa y cuándo ir a urgencias" and the AEPap "cuándo acudir a
# urgencias" paragraphs were inside the cut-off, but retrieve_evidence returns one
# fragment per source, so a cited guideline only ever showed its best fragment for
# the warning words, a general one. The croup plan then had no «Cuándo ir al médico».


def _topic(source: UUID, distance: float, topic: str) -> EvidenceMatch:
    """A fragment shaped like the corpus: title, "Tema:", then "Hallazgo:"."""
    return EvidenceMatch(
        chunk_id=uuid4(), source_id=source, source_title="Laringitis", organization="ORG",
        publication_year=2017, url=None, chunk_index=0, distance=distance,
        content=f"Laringitis (Familia y Salud, AEPap, 2017). Tema: {topic}. Hallazgo: texto.",
    )


@pytest.mark.parametrize("topic", [
    "cuándo acudir a urgencias con un niño con laringitis",
    "cuidados en casa y cuándo ir a urgencias",
    "signos de empeoramiento por los que consultar",
    "qué hacer, qué no hacer y cuándo llamar al 112",
    "evolución y signos de alarma",
    "when to call for emergency help",
    "when to see a doctor urgently",
    "quand consulter en urgence",
    "signes d’alerte et quand appeler le 15",
])
def test_a_topic_on_when_to_go_is_recognised_in_three_languages(topic):
    from adelia.enrichment.evidence_retrieval import says_when_to_go

    assert says_when_to_go(_topic(A, 0.1, topic).content)


@pytest.mark.parametrize("content", [
    _topic(A, 0.1, "síntomas y evolución de la laringitis").content,
    _topic(A, 0.1, "qué hacer en casa y qué remedios no sirven").content,
    # The finding mentions a doctor, as most do; only the topic line counts.
    "Laringitis (AEPap). Tema: qué es. Hallazgo: si empeora, consulte a urgencias.",
    # No topic line at all (a paper abstract): no preference, plain distance.
    "Emergency department visits for croup fell after 2020.",
    "",
])
def test_a_general_fragment_is_not_taken_for_one_on_when_to_go(content):
    from adelia.enrichment.evidence_retrieval import says_when_to_go

    assert not says_when_to_go(content)


def test_the_urgency_paragraph_of_a_cited_source_wins_over_its_closer_general_one():
    """The croup case: AEPap's best fragment for the warning words is "síntomas y
    evolución"; its paragraph on when to go is farther and is the one she needs."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    home = _topic(A, 0.08, "qué hacer en casa y qué remedios no sirven")
    seup = _topic(B, 0.09, "qué es la laringitis y cómo se manifiesta")
    general = _topic(A, 0.11, "síntomas y evolución de la laringitis")
    a_urgent = _topic(A, 0.15, "cuándo acudir a urgencias con un niño con laringitis")
    b_urgent = _topic(B, 0.135, "cuidados en casa y cuándo ir a urgencias")
    got = add_warning_fragments([home, seup], [general, a_urgent, b_urgent])
    assert got == [home, seup, b_urgent, a_urgent]
    assert add_warning_fragments([home, seup], [general, a_urgent], limit=1) == [
        home, seup, a_urgent]


def test_the_urgency_paragraph_of_a_cited_source_wins_over_a_new_source():
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    home = _topic(A, 0.08, "qué hacer en casa y qué remedios no sirven")
    stranger = _topic(C, 0.05, "qué es la tos y por qué aparece")
    a_urgent = _topic(A, 0.15, "cuándo acudir a urgencias con un niño con laringitis")
    assert add_warning_fragments([home], [stranger, a_urgent], limit=1) == [home, a_urgent]


def test_a_new_source_is_ranked_by_distance_alone():
    """Outside the cited guidelines the preference does not apply: another
    illness's "cuándo llamar" (the fever guide for a croup question) must not
    jump over a closer fragment."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    home = _topic(A, 0.08, "qué hacer en casa")
    near = _topic(C, 0.07, "qué es la laringitis")
    fever = _topic(D, 0.12, "la fiebre y cuándo llamar al pediatra")
    assert add_warning_fragments([home], [fever, near], limit=1) == [home, near]


def test_one_fragment_found_by_both_warning_searches_is_added_once():
    """The restricted search and the global one can both return a fragment of a
    cited source; it is one paragraph and takes one slot."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    home = _topic(A, 0.08, "qué hacer en casa")
    urgent = _topic(A, 0.12, "cuándo acudir a urgencias")
    other = _topic(C, 0.10, "qué es")
    assert add_warning_fragments([home], [urgent, urgent, other]) == [home, urgent, other]


# --- the same, against Postgres: the restricted search's SQL ----------------------

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

DIM = 1024
QUERY = [1.0] + [0.0] * (DIM - 1)
#: A specialty no real source carries, so the shared dev corpus never answers.
SPECIALTY = "warning-paragraph-test"
PREFIX = "WARNING-PARAGRAPH-TEST-"


def _vec_at(distance: float) -> list[float]:
    import math

    cos = 1.0 - distance
    return [cos, math.sqrt(1.0 - cos * cos)] + [0.0] * (DIM - 2)


@pytest.fixture
async def croup_corpus():
    """Two cited guidelines with several paragraphs each, and one new source.

    Distances from the warning query, chosen like the croup measurement: each
    cited guideline's best fragment for the warning words is a general one.
    """
    from sqlalchemy import text

    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk, EvidenceSource

    async def _sweep():
        async with AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM evidence_sources WHERE title LIKE :p"),
                                  {"p": f"{PREFIX}%"})
            await session.commit()

    await _sweep()
    spec = {
        "aepap": [("qué hacer en casa y qué remedios no sirven", 0.13),
                  ("síntomas y evolución de la laringitis", 0.10),
                  ("cuándo acudir a urgencias con un niño con laringitis", 0.15),
                  ("la tos que dura semanas", 0.25)],
        "seup": [("qué es la laringitis y cómo se manifiesta", 0.11),
                 ("cuidados en casa y cuándo ir a urgencias", 0.135)],
        "new": [("qué es la tos y por qué aparece", 0.09)],
        "adult": [("cuándo ir a urgencias con disnea", 0.05)],
    }
    ids: dict[str, object] = {}
    async with AsyncSessionLocal() as session:
        for key, chunks in spec.items():
            source = EvidenceSource(
                source_type="guideline", title=f"{PREFIX}{key}-{uuid4().hex[:6]}",
                organization="TEST", publication_year=2026, language="es", tier="evidence",
                specialties=["adult"] if key == "adult" else [SPECIALTY],
            )
            session.add(source)
            await session.flush()
            ids[key] = source.id
            for i, (topic, distance) in enumerate(chunks):
                chunk = EvidenceChunk(
                    source_id=source.id, chunk_index=i, language="es", embedding=_vec_at(distance),
                    content=f"{key} (TEST). Tema: {topic}. Hallazgo: texto.",
                )
                session.add(chunk)
                await session.flush()
                ids[(key, topic)] = chunk.id
        await session.commit()
    try:
        yield ids
    finally:
        await _sweep()


async def _warning_search(**kwargs):
    from adelia.db import AsyncSessionLocal

    kwargs.setdefault("specialties", [SPECIALTY])
    kwargs.setdefault("max_distance", 0.19)
    kwargs.setdefault("relative_margin", 0.08)
    async with AsyncSessionLocal() as session:
        return await retrieve_evidence(session, query_embedding=QUERY, top_k=4, **kwargs)


def _main(ids):
    """What the croup question's main search held: AEPap's home care, SEUP's "qué es"."""
    return {
        "cited_sources": [ids["aepap"], ids["seup"]],
        "cited_chunks": [ids[("aepap", "qué hacer en casa y qué remedios no sirven")],
                         ids[("seup", "qué es la laringitis y cómo se manifiesta")]],
    }


@needs_pg
async def test_without_cited_sources_the_search_is_one_fragment_per_source(croup_corpus):
    got = await _warning_search()
    assert [m.distance for m in got] == pytest.approx([0.09, 0.10, 0.11], abs=1e-4)
    assert len({m.source_id for m in got}) == len(got)


@needs_pg
async def test_the_restricted_search_returns_several_fragments_of_one_source(croup_corpus):
    ids = croup_corpus
    got = await _warning_search(**_main(ids))
    of_aepap = [m.chunk_id for m in got if m.source_id == ids["aepap"]]
    assert ids[("aepap", "síntomas y evolución de la laringitis")] in of_aepap
    assert ids[("aepap", "cuándo acudir a urgencias con un niño con laringitis")] in of_aepap
    assert ids[("seup", "cuidados en casa y cuándo ir a urgencias")] in {m.chunk_id for m in got}


@needs_pg
async def test_the_restricted_search_never_returns_a_fragment_the_plan_holds(croup_corpus):
    """The restricted half excludes them in SQL; the global half may still return
    one (as it always did) and add_warning_fragments drops it."""
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment.evidence_retrieval import fragments_of_sources

    ids = croup_corpus
    main = _main(ids)
    async with AsyncSessionLocal() as session:
        restricted = await fragments_of_sources(
            session, query_embedding=QUERY, source_ids=main["cited_sources"],
            exclude_chunk_ids=main["cited_chunks"], specialties=[SPECIALTY], max_distance=0.19,
        )
    assert [m.distance for m in restricted] == pytest.approx([0.10, 0.135, 0.15], abs=1e-4)
    assert not {m.chunk_id for m in restricted} & set(main["cited_chunks"])
    assert {m.source_id for m in restricted} == {ids["aepap"], ids["seup"]}


@needs_pg
async def test_the_restricted_search_admits_nothing_past_the_cut_off(croup_corpus):
    ids = croup_corpus
    got = await _warning_search(**_main(ids))
    assert ids[("aepap", "la tos que dura semanas")] not in {m.chunk_id for m in got}
    assert all(m.distance < 0.19 for m in got)
    tight = await _warning_search(**_main(ids), max_distance=0.12)
    assert all(m.distance < 0.12 for m in tight)
    assert ids[("aepap", "cuándo acudir a urgencias con un niño con laringitis")] not in {
        m.chunk_id for m in tight}


@needs_pg
async def test_the_restricted_search_keeps_the_relative_margin_of_the_warning_query(croup_corpus):
    """Anchored to the warning query's best fragment (0.09, the new source), as the
    global search is: at a 0.03 margin the 0.135 and 0.15 paragraphs are out."""
    ids = croup_corpus
    got = await _warning_search(**_main(ids), relative_margin=0.03)
    assert all(m.distance <= 0.09 + 0.03 + 1e-6 for m in got)


@needs_pg
async def test_the_restricted_search_keeps_the_specialty_filter(croup_corpus):
    """An adult source passed as cited still never answers a question about a baby."""
    ids = croup_corpus
    main = _main(ids)
    main["cited_sources"].append(ids["adult"])
    got = await _warning_search(**main)
    assert ids["adult"] not in {m.source_id for m in got}


@needs_pg
async def test_the_urgency_paragraphs_of_the_cited_guidelines_reach_the_plan(croup_corpus):
    """End to end in the retrieval module: the croup shape of 2026-11-06."""
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    ids = croup_corpus
    main_ids = _main(ids)
    main = [
        EvidenceMatch(chunk_id=chunk, source_id=source, source_title="t", organization=None,
                      publication_year=None, url=None, content="c", chunk_index=0, distance=0.1)
        for source, chunk in zip(main_ids["cited_sources"], main_ids["cited_chunks"])
    ]
    got = add_warning_fragments(main, await _warning_search(**main_ids))
    assert got[: len(main)] == main
    added = {m.chunk_id for m in got[len(main):]}
    assert added == {ids[("aepap", "cuándo acudir a urgencias con un niño con laringitis")],
                     ids[("seup", "cuidados en casa y cuándo ir a urgencias")]}


@needs_pg
async def test_an_empty_main_list_stays_empty_with_the_restricted_search(croup_corpus):
    from adelia.enrichment.evidence_retrieval import add_warning_fragments

    assert add_warning_fragments([], await _warning_search(**_main(croup_corpus))) == []
