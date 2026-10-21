"""What the public demo searches the corpus with.

Measured on production on 2026-10-14: the demo's own first suggested question,
"¿Es normal que Lucía regurgite después de casi todas las tomas?", was refused
("No tengo evidencia clínica sobre esto") while the same sentence about "mi
bebé" reached the reflux guideline. The invented baby's name moved the
embedding from 0.154 to 0.261, past the 0.19 relevance cut-off. A first name is
not clinical content, so the search must not carry it. The model still reads the
original question: the patient record in the prompt is what makes "Lucía" mean
something there.

The cut-off itself is NOT part of this fix. Group B of the golden set has
questions that must be refused at 0.13 and group A questions that must be answered
at 0.17, so loosening it to make a demo sentence pass would admit questions the
product refuses today.
"""
from __future__ import annotations

import pytest

from adelia.demo.fixture import DEMO_LOCALES, demo_profile, retrieval_query


@pytest.mark.parametrize(
    ("locale", "question", "expected"),
    [
        (
            "es",
            "¿Es normal que Lucía regurgite después de casi todas las tomas?",
            "¿Es normal que mi bebé regurgite después de casi todas las tomas?",
        ),
        ("en", "Does Lucía need an iron supplement?", "Does my baby need an iron supplement?"),
        ("fr", "Est-ce que Lucía a besoin de fer ?", "Est-ce que mon bébé a besoin de fer ?"),
    ],
)
def test_the_babys_name_is_replaced_by_a_neutral_subject(locale, question, expected):
    assert retrieval_query(question, locale) == expected


@pytest.mark.parametrize("typed", ["lucia", "LUCÍA", "Lucia", "lucía"])
def test_a_visitor_who_types_the_name_any_way_gets_the_same_treatment(typed):
    out = retrieval_query(f"¿Cuándo duerme mejor {typed}?", "es")
    assert "luc" not in out.lower()
    assert "mi bebé" in out


def test_a_question_without_the_name_is_returned_untouched():
    q = "¿Cuándo conviene empezar la alimentación complementaria?"
    assert retrieval_query(q, "es") == q


def test_an_unknown_locale_falls_back_to_spanish_like_the_rest_of_the_demo():
    assert retrieval_query("¿Lucía duerme bien?", "de") == "¿mi bebé duerme bien?"


@pytest.mark.parametrize("locale", DEMO_LOCALES)
def test_no_suggested_question_searches_with_the_name(locale):
    """Whatever wording a suggestion has, the sentence that reaches the embedding
    must not carry the baby's name."""
    profile = demo_profile(locale)
    assert len(profile["suggested"]) == 3
    for question in profile["suggested"]:
        assert profile["baby_name"].lower() not in retrieval_query(question, locale).lower()


async def test_the_router_embeds_the_neutral_question_and_the_model_reads_the_original(
    client, monkeypatch
):
    """The embedding must not carry the baby's name; the generation prompt must."""
    import uuid
    from unittest.mock import patch

    from adelia.enrichment.evidence_retrieval import EvidenceMatch
    from tests.pg_gate import PG_AVAILABLE

    if not PG_AVAILABLE:
        pytest.skip("needs Postgres for the demo budget counter")

    match = EvidenceMatch(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        source_title="Guideline",
        organization="NICE",
        publication_year=2019,
        url="https://example.org/g",
        content="Regurgitation is common in infants.",
        chunk_index=0,
        distance=0.07,
    )
    embedded: list[str] = []
    prompts: list[str] = []

    async def _embed(texts):
        embedded.extend(texts)
        return [[0.0] * 1024]

    async def _retrieve(session, **kwargs):
        return [match]

    async def _generate(system_prompt, user_message, **kwargs):
        prompts.append(user_message)
        return "Respuesta [ev_1]."

    with patch("adelia.routers.demo.embed_texts", _embed), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.generate_answer", _generate):
        resp = await client.post(
            "/demo/ask",
            json={"question": "¿Es normal que Lucía regurgite tras las tomas?", "locale": "es"},
        )

    assert resp.status_code == 200, resp.text
    assert embedded == ["¿Es normal que mi bebé regurgite tras las tomas?"]
    assert "Lucía regurgite" in prompts[0]
