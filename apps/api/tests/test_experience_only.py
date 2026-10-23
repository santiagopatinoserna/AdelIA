"""No evidence, but other mothers have something to say (AGENT_GRAPH, decision 3).

When the clinical corpus has nothing and the experience tier has a match, the
demo no longer refuses outright: it says so in one fixed sentence and shows
only "Lo que cuentan otras madres". That is a new `kind`, `experience_only`,
never `answer`, and it is fenced on every side:

  * a red flag still fires first and never gets here;
  * evidence present keeps the plan path untouched (`answer` / `evidence_only`);
  * the model writes the bullets under its own, narrower contract, and the
    code throws the whole thing away and refuses as before if the output
    carries any other section or any citation that is not [ex_N].
"""
from __future__ import annotations

import pytest

from adelia.services.answer_contract import (
    CONTRACTS,
    PLAN_HEADINGS,
    experience_only_contract,
    experience_only_opening,
)


@pytest.mark.parametrize("locale, opening", [
    ("es", "No he encontrado guías ni estudios sobre esto. Otras madres cuentan:"),
    ("en", "I found no guidelines or studies on this. Other mothers say:"),
    ("fr", "Je n’ai trouvé ni recommandation ni étude sur ce sujet. D’autres mères racontent :"),
])
def test_the_opening_sentence_is_fixed_per_locale(locale, opening):
    assert experience_only_opening(locale) == opening
    assert "—" not in opening


def test_an_unknown_locale_opens_in_spanish():
    assert experience_only_opening("de") == experience_only_opening("es")


@pytest.mark.parametrize("locale, required", [
    ("es", ("[ex_N]", "1 a 3 viñetas", "nunca una dosis", "nunca un medicamento",
            "nunca interpretes", "nunca una señal de alarma", "nunca una urgencia")),
    ("en", ("[ex_N]", "1 to 3 bullets", "never a dose", "never a medicine",
            "never interpret", "never a warning sign", "never an urgency")),
    ("fr", ("[ex_N]", "1 à 3 puces", "jamais de dose", "jamais de médicament",
            "n’interprète jamais", "jamais de signe d’alerte", "jamais d’urgence")),
])
def test_the_experience_only_contract_names_what_it_may_never_carry(locale, required):
    rule = experience_only_contract(locale).lower()
    for clause in required:
        assert clause.lower() in rule, clause


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_experience_only_contract_allows_exactly_the_mothers_section(locale):
    rule = experience_only_contract(locale)
    h = PLAN_HEADINGS[locale]
    assert f"## {h['mothers']}" in rule
    for key in ("today", "watch", "doctor", "remember"):
        assert f"## {h[key]}" not in rule
    # The plan rule and the refusal text do not belong in this prompt: there
    # is no evidence to plan on and the code, not the model, decides to refuse.
    assert "[ev_" not in rule
    assert CONTRACTS[locale].refusal not in rule
    assert "—" not in rule


# ---------------------------------------------------------------------------
# The demo route
# ---------------------------------------------------------------------------

import uuid  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from adelia.enrichment.evidence_retrieval import EvidenceMatch  # noqa: E402
from adelia.services.answer_contract import interface_disclaimer, no_evidence_reply  # noqa: E402

from tests.pg_gate import PG_AVAILABLE  # noqa: E402

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


def _match(tier: str, title: str, distance: float = 0.12) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title=title,
        organization="Org", publication_year=2024, url=f"https://example.org/{tier}",
        content=f"{tier} fragment", chunk_index=0, distance=distance, tier=tier,
    )


EVIDENCE = _match("evidence", "A real guideline")
EXPERIENCE = _match("experience", "A blog post by a mother")
GOOD_BULLETS = "## Lo que cuentan otras madres\n- A una madre le funcionó el baño antes de cenar [ex_1]."


async def _ask(client, *, evidence, experience, model_output=GOOD_BULLETS, locale="es",
               question="¿El baño antes o después de la cena?"):
    calls: dict = {}

    async def _retrieve(session, **kwargs):
        return list(evidence)

    async def _retrieve_experience(session, **kwargs):
        calls["experience_kwargs"] = kwargs
        return list(experience)

    async def _generate(system_prompt, user_message, **kwargs):
        calls["system"] = system_prompt
        calls["user"] = user_message
        if isinstance(model_output, Exception):
            raise model_output
        return model_output

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.retrieve_experience", _retrieve_experience), patch(
        "adelia.routers.demo.generate_answer", _generate
    ):
        resp = await client.post("/demo/ask", json={"question": question, "locale": locale})
    assert resp.status_code == 200, resp.text
    return resp.json(), calls


@pg_only
async def test_no_evidence_with_experience_answers_experience_only(client):
    body, calls = await _ask(client, evidence=[], experience=[EXPERIENCE])
    assert body["kind"] == "experience_only"
    assert body["answer"] == experience_only_opening("es") + "\n\n" + GOOD_BULLETS
    assert [(c["tag"], c["tier"]) for c in body["evidence_citations"]] == [("ex_1", "experience")]
    assert body["evidence_citations"][0]["title"] == "A blog post by a mother"
    assert body["disclaimer"] == interface_disclaimer("es")


@pg_only
async def test_the_bullets_are_written_under_the_experience_only_contract(client):
    _, calls = await _ask(client, evidence=[], experience=[EXPERIENCE])
    assert calls["system"] == experience_only_contract("es")
    assert "[ex_1]" in calls["user"] and "not medical evidence" in calls["user"]
    assert "## Clinical evidence" not in calls["user"]
    # Same cut as the clinical retrieval: the tier is not reached more loosely
    # just because nothing clinical came back.
    from adelia.config import settings

    kw = calls["experience_kwargs"]
    assert kw["max_distance"] == settings.evidence_max_distance
    assert kw["relative_margin"] == settings.evidence_relative_margin


@pg_only
async def test_no_evidence_and_no_experience_is_still_no_evidence(client):
    body, calls = await _ask(client, evidence=[], experience=[])
    assert body["kind"] == "no_evidence"
    assert body["answer"] == no_evidence_reply("es")
    assert body["evidence_citations"] == []
    assert "user" not in calls, "the model was called with nothing to read"


@pytest.mark.parametrize("stray", [
    "## Lo que cuentan otras madres\n- Truco [ex_1].\n\n## Cuándo ir al médico\n- Si tiene fiebre, urgencias.",
    "## Hoy\n- Dale un baño [ex_1].",
    "## Lo que cuentan otras madres\n- Según la guía, es normal [ev_1].",
    "## Lo que cuentan otras madres\n- Pesa 6 kg [1] y eso es poco [ex_1].",
    "Mi consejo: baño templado.\n\n## Lo que cuentan otras madres\n- Truco [ex_1].",
    "## Lo que cuentan otras madres\n- Una madre dice que le ayudó.",
    "",
])
@pg_only
async def test_a_stray_section_or_citation_discards_the_bullets_and_refuses(client, stray):
    """The model is told the shape; the code checks it. Anything beyond one
    mothers section with [ex_N] bullets is thrown away whole, not trimmed."""
    body, _ = await _ask(client, evidence=[], experience=[EXPERIENCE], model_output=stray)
    assert body["kind"] == "no_evidence"
    assert body["answer"] == no_evidence_reply("es")
    assert body["evidence_citations"] == []


@pg_only
async def test_a_model_failure_in_experience_only_refuses_as_before(client):
    body, _ = await _ask(client, evidence=[], experience=[EXPERIENCE],
                         model_output=RuntimeError("llm down"))
    assert body["kind"] == "no_evidence"
    assert body["evidence_citations"] == []


@pg_only
async def test_a_red_flag_never_reaches_experience_only(client):
    exp_mock = AsyncMock(return_value=[EXPERIENCE])
    gen_mock = AsyncMock(return_value=GOOD_BULLETS)
    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", AsyncMock(return_value=[])
    ), patch("adelia.routers.demo.retrieve_experience", exp_mock), patch(
        "adelia.routers.demo.generate_answer", gen_mock
    ):
        resp = await client.post(
            "/demo/ask",
            json={"question": "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?", "locale": "es"},
        )
    body = resp.json()
    assert body["kind"] == "red_flag"
    exp_mock.assert_not_called()
    gen_mock.assert_not_called()
    assert all(c.get("tier", "evidence") == "evidence" for c in body["evidence_citations"])


@pg_only
async def test_experience_with_clinical_evidence_is_still_a_plan_answer(client):
    plan = "Plan [ev_1].\n\n## Hoy\n- Algo [ev_1].\n\n## Lo que cuentan otras madres\n- Truco [ex_1]."
    body, calls = await _ask(client, evidence=[EVIDENCE], experience=[EXPERIENCE],
                             model_output=plan)
    assert body["kind"] == "answer"
    assert body["answer"] == plan
    assert calls["system"] != experience_only_contract("es")
    assert [(c["tag"], c["tier"]) for c in body["evidence_citations"]] == [
        ("ev_1", "evidence"), ("ex_1", "experience"),
    ]


@pg_only
@pytest.mark.parametrize("locale, heading", [
    ("en", "What other mothers say"), ("fr", "Ce que racontent d’autres mères"),
])
async def test_experience_only_speaks_the_parents_language(client, locale, heading):
    bullets = f"## {heading}\n- One mother [ex_1]."
    body, calls = await _ask(client, evidence=[], experience=[EXPERIENCE],
                             model_output=bullets, locale=locale, question="Bath before dinner?")
    assert body["kind"] == "experience_only"
    assert body["answer"].startswith(experience_only_opening(locale))
    assert calls["system"] == experience_only_contract(locale)


@pg_only
async def test_a_mothers_heading_in_another_language_is_a_stray_section(client):
    body, _ = await _ask(client, evidence=[], experience=[EXPERIENCE],
                         model_output="## What other mothers say\n- One [ex_1].", locale="es")
    assert body["kind"] == "no_evidence"


# ---------------------------------------------------------------------------
# The web catalogues (drift lock, like test_answer_plan)
# ---------------------------------------------------------------------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402

WEB_MESSAGES = Path(__file__).resolve().parents[2] / "web" / "messages"


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_web_title_for_experience_only_is_the_mothers_heading(locale):
    demo = json.loads((WEB_MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))["demo"]
    assert demo["experienceOnlyTitle"] == PLAN_HEADINGS[locale]["mothers"]
    assert demo["experienceOnlyTitle"] != demo["answerTitle"]
    fold = demo["readMoreTitleExperience"]
    assert fold.strip() and fold != demo["readMoreTitle"]
    for key in ("experienceOnlyTitle", "readMoreTitleExperience"):
        assert "—" not in demo[key]
