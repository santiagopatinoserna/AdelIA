"""Experience and evidence never cross in retrieval.

The two tiers share one table and one vector index, so the only thing that
keeps a mother's forum post out of "Cuándo ir al médico", and a guideline out
of "Lo que cuentan otras madres", is the `tier` filter in the SQL. These
tests seed both tiers at known distances and prove each query sees only its
own, including when the other tier is closer and even when an experience row
is (wrongly) tagged 'pediatrics'.
"""
from __future__ import annotations

import math
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from adelia.config import settings
from adelia.enrichment.evidence_retrieval import (
    EvidenceMatch,
    evidence_citations_for_response,
    format_experience_for_prompt,
    lexical_evidence_ranking,
    retrieve_evidence,
    retrieve_experience,
)
from adelia.services.lexical import plan_lexical

from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

DIM = 1024
QUERY = [1.0] + [0.0] * (DIM - 1)
PREFIX = "EXPERIENCE-RETRIEVAL-TEST-"
MARK = "experienceprobe"


def vec_at(distance: float) -> list[float]:
    cos = 1.0 - distance
    return [cos, math.sqrt(1.0 - cos * cos)] + [0.0] * (DIM - 2)


def _m(tier: str = "evidence", distance: float = 0.05) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid4(), source_id=uuid4(), source_title="t", organization="o",
        publication_year=2024, url="https://example.org", content="c", chunk_index=0,
        distance=distance, tier=tier,
    )


def test_a_match_is_evidence_unless_said_otherwise():
    assert _m().tier == "evidence"


def test_citations_carry_the_tier_and_experience_uses_its_own_tag_namespace():
    evidence = evidence_citations_for_response([_m()])
    assert evidence[0]["tier"] == "evidence"
    assert evidence[0]["tag"] == "ev_1"
    experience = evidence_citations_for_response([_m("experience"), _m("experience")],
                                                 tag_prefix="ex", tier="experience")
    assert [c["tag"] for c in experience] == ["ex_1", "ex_2"]
    assert {c["tier"] for c in experience} == {"experience"}


def test_the_experience_prompt_block_is_labelled_and_separate():
    block = format_experience_for_prompt([_m("experience")])
    assert block.startswith("## What other parents report")
    assert "[ex_1]" in block
    assert "not medical evidence" in block
    assert format_experience_for_prompt([]) == ""


@pytest.fixture
async def two_tiers():
    """Four seeded rows: two per tier, the closest one of each being the
    OTHER tier's temptation. Removed afterwards."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk, EvidenceSource

    async def _sweep():
        async with AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM evidence_sources WHERE title LIKE :p"),
                                  {"p": f"{PREFIX}%"})
            await session.commit()

    await _sweep()
    spec = {
        # key: (tier, source_type, specialties, distance, content)
        "guideline": ("evidence", "guideline", ["pediatrics"], 0.08,
                      f"Sueño seguro {MARK} del lactante según la guía."),
        "guideline_far": ("evidence", "guideline", ["pediatrics"], 0.12,
                          f"Alimentación complementaria {MARK} según la guía."),
        "mothers": ("experience", "experience", ["experience"], 0.03,
                    f"Lo que cuentan otras madres {MARK} sobre el sueño."),
        # Mis-tagged on purpose: the tier must be the lock, not the tag.
        "mothers_mistagged": ("experience", "experience", ["pediatrics", "experience"], 0.02,
                              f"Otra madre {MARK} cuenta cómo calmó el llanto."),
    }
    ids: dict[str, UUID] = {}
    async with AsyncSessionLocal() as session:
        for key, (tier, source_type, specialties, distance, content) in spec.items():
            source = EvidenceSource(
                source_type=source_type, title=f"{PREFIX}{key}-{uuid4().hex[:6]}",
                organization="TEST", publication_year=2026, specialties=specialties,
                language="es", tier=tier, url="https://example.org/" + key,
            )
            session.add(source)
            await session.flush()
            chunk = EvidenceChunk(source_id=source.id, content=content, chunk_index=0,
                                  chunk_metadata={"section": key}, embedding=vec_at(distance),
                                  language="es")
            session.add(chunk)
            await session.flush()
            ids[key] = source.id
        await session.commit()
    try:
        yield ids
    finally:
        await _sweep()


@pytest.fixture(autouse=True)
def _vector_only(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", False)


async def _evidence(**kwargs):
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await retrieve_evidence(session, query_embedding=QUERY, specialties=["pediatrics"],
                                       top_k=4, max_distance=0.20, **kwargs)


async def _experience(**kwargs):
    from adelia.db import AsyncSessionLocal

    kwargs.setdefault("top_k", 3)
    kwargs.setdefault("max_distance", 0.20)
    async with AsyncSessionLocal() as session:
        return await retrieve_experience(session, query_embedding=QUERY, **kwargs)


@needs_pg
async def test_the_pediatric_query_never_returns_an_experience_row(two_tiers):
    got = await _evidence()
    seeded = {m.source_id: m for m in got if m.source_title.startswith(PREFIX)}
    assert two_tiers["mothers"] not in seeded
    assert two_tiers["mothers_mistagged"] not in seeded, "specialty tag must not be enough"
    assert two_tiers["guideline"] in seeded
    assert all(m.tier == "evidence" for m in got)


@needs_pg
async def test_the_experience_query_never_returns_a_guideline(two_tiers):
    got = await _experience()
    ids = {m.source_id for m in got}
    assert two_tiers["guideline"] not in ids
    assert two_tiers["guideline_far"] not in ids
    assert {two_tiers["mothers"], two_tiers["mothers_mistagged"]} <= ids
    assert all(m.tier == "experience" for m in got)


@needs_pg
async def test_the_experience_query_keeps_the_same_cut_offs_as_evidence(two_tiers):
    """0.19 absolute and the relative margin: nothing looser for the softer tier."""
    close_only = await _experience(max_distance=0.025)
    assert [m.source_id for m in close_only] == [two_tiers["mothers_mistagged"]]
    with_margin = await _experience(relative_margin=0.005)
    assert [m.source_id for m in with_margin] == [two_tiers["mothers_mistagged"]]


@needs_pg
async def test_the_lexical_half_is_filtered_by_tier_too(two_tiers, monkeypatch):
    from adelia.db import AsyncSessionLocal

    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", True)
    plan = plan_lexical(MARK, "es")
    assert plan is not None
    async with AsyncSessionLocal() as session:
        evidence_ids = await lexical_evidence_ranking(session, plan=plan, specialties=["pediatrics"],
                                                      pool=50)
        experience_ids = await lexical_evidence_ranking(session, plan=plan, specialties=None,
                                                        pool=50, tier="experience")
        rows = (await session.execute(text(
            "SELECT ec.id::text, es.tier FROM evidence_chunks ec "
            "JOIN evidence_sources es ON es.id = ec.source_id WHERE es.title LIKE :p"
        ), {"p": f"{PREFIX}%"})).all()
    tier_of = dict(rows)
    assert {tier_of[i] for i in evidence_ids if i in tier_of} == {"evidence"}
    assert {tier_of[i] for i in experience_ids if i in tier_of} == {"experience"}
