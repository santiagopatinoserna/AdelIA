"""The experience tier in the public demo: a layer under the plan, never a lever.

What other mothers say may add one optional section at the end of an
answer. It must not change what the code decides: a red flag still fires
before anything, a question with experience hits and no clinical evidence
never becomes an `answer` (it may become `experience_only`, fenced in
tests/test_experience_only.py), and a failure in the experience lookup costs
the section, not the answer.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.schemas import EvidenceCitation

from tests.pg_gate import PG_AVAILABLE

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


def _match(tier: str, title: str) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title=title,
        organization="Org", publication_year=2024, url=f"https://example.org/{tier}",
        content=f"{tier} fragment", chunk_index=0, distance=0.07, tier=tier,
    )


EVIDENCE = _match("evidence", "A real guideline")
EXPERIENCE = _match("experience", "A blog post by a mother")


def test_a_citation_is_evidence_unless_the_api_says_otherwise():
    """Older clients and the red-flag citation never send a tier."""
    c = EvidenceCitation(tag="ev_1", source_id="s", chunk_id="c", title="t", snippet="x")
    assert c.tier == "evidence"
    e = EvidenceCitation(tag="ex_1", source_id="s", chunk_id="c", title="t", snippet="x",
                         tier="experience")
    assert e.tier == "experience"


async def _ask(client, *, evidence, experience, generate=None):
    prompt: dict = {}

    async def _retrieve(session, **kwargs):
        return list(evidence)

    async def _retrieve_experience(session, **kwargs):
        if isinstance(experience, Exception):
            raise experience
        return list(experience)

    async def _generate(system_prompt, user_message, **kwargs):
        prompt["user"] = user_message
        if generate is not None:
            raise generate
        if "## Clinical evidence" not in user_message:
            return "## Lo que cuentan otras madres\n- Truco [ex_1]."
        return "Plan de prueba [ev_1].\n\n## Lo que cuentan otras madres\n- Truco [ex_1]."

    exp_mock = AsyncMock(side_effect=_retrieve_experience)
    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.retrieve_experience", exp_mock), patch(
        "adelia.routers.demo.generate_answer", _generate
    ):
        resp = await client.post(
            "/demo/ask", json={"question": "¿Cómo le ayudo a dormir mejor?", "locale": "es"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json(), prompt, exp_mock


@pg_only
async def test_experience_citations_come_after_the_evidence_and_say_what_they_are(client):
    body, prompt, _ = await _ask(client, evidence=[EVIDENCE], experience=[EXPERIENCE])
    assert body["kind"] == "answer"
    tags = [(c["tag"], c["tier"]) for c in body["evidence_citations"]]
    assert tags == [("ev_1", "evidence"), ("ex_1", "experience")]
    assert body["evidence_citations"][1]["title"] == "A blog post by a mother"
    # The model reads the two blocks apart, clinical first, and the experience
    # block is labelled as such in the prompt itself.
    user = prompt["user"]
    assert "## Clinical evidence" in user and "## What other parents report" in user
    assert user.index("## Clinical evidence") < user.index("## What other parents report")
    assert "[ex_1]" in user and "not medical evidence" in user


@pg_only
async def test_experience_alone_is_experience_only_never_an_answer(client):
    """The `kind` decision is still the evidence tier's: with nothing clinical
    there is no plan and no `answer`. What experience alone may do (AGENT_GRAPH,
    decision 3) is replace the bare refusal with `experience_only`, which
    tests/test_experience_only.py fences; the plan contract is never used."""
    body, prompt, exp_mock = await _ask(client, evidence=[], experience=[EXPERIENCE])
    assert body["kind"] == "experience_only"
    assert body["kind"] != "answer"
    assert [c["tier"] for c in body["evidence_citations"]] == ["experience"]
    assert "## Clinical evidence" not in prompt["user"]
    exp_mock.assert_called_once()


@pg_only
async def test_a_red_flag_never_consults_experience(client):
    exp_mock = AsyncMock(return_value=[EXPERIENCE])
    with patch("adelia.routers.demo.embed_texts") as embed, patch(
        "adelia.routers.demo.retrieve_experience", exp_mock
    ):
        resp = await client.post(
            "/demo/ask",
            json={"question": "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?", "locale": "es"},
        )
    assert resp.json()["kind"] == "red_flag"
    embed.assert_not_called()
    exp_mock.assert_not_called()
    assert all(c.get("tier", "evidence") == "evidence" for c in resp.json()["evidence_citations"])


@pg_only
async def test_an_experience_lookup_failure_costs_the_section_not_the_answer(client):
    body, prompt, _ = await _ask(client, evidence=[EVIDENCE], experience=RuntimeError("down"))
    assert body["kind"] == "answer"
    assert [c["tier"] for c in body["evidence_citations"]] == ["evidence"]
    assert "What other parents report" not in prompt["user"]


@pg_only
async def test_when_the_model_fails_only_the_clinical_sources_are_shown(client):
    """evidence_only shows "the sources we found for your question" with no
    answer around them to say which is which; a blog post in that list would
    read as a guideline."""
    body, _, _ = await _ask(client, evidence=[EVIDENCE], experience=[EXPERIENCE],
                            generate=RuntimeError("llm down"))
    assert body["kind"] == "evidence_only"
    assert [c["tier"] for c in body["evidence_citations"]] == ["evidence"]
