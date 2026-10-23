"""The agent graph, build step 2 (docs/specs/AGENT_GRAPH.md).

guard -> admit -> route -> retrieve -> decide -> plan | answer | experience_only -> compose

Every path is run end to end with fakes for the four things that cost money
or need a network (route, embed, retrieval, generation), so these tests need
neither a database nor a key. What they pin:

  * the guard runs first and a red flag reaches nothing else, not even the
    spending gate;
  * the route decision picks the CONTRACT: `question` gets the short answer
    and never the plan, `plan` gets the plan with the experience section;
  * `kind` is decided by the evidence alone, experience is read only after it;
  * a model failure costs the answer, not the sources (`evidence_only`).
"""
from __future__ import annotations

import os
import uuid

import pytest

from adelia.agent.graph import GraphDeps, GraphUnavailable, run_graph
from adelia.agent.route import RouteDecision
from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import (
    chat_system_prompt,
    experience_only_contract,
    no_evidence_reply,
)


def _match(tier: str, title: str) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title=title,
        organization="Org", publication_year=2024, url="https://example.org/x",
        content="fragment", chunk_index=0, distance=0.07, tier=tier,
    )


EVIDENCE = _match("evidence", "A real guideline")
EXPERIENCE = _match("experience", "A blog post by a mother")
CLEAN_BULLETS = "## Lo que cuentan otras madres\n- Le funcionó el baño antes de cenar [ex_1]."


class Fakes:
    def __init__(self, *, intent="plan", via="rule", evidence=(EVIDENCE,), experience=(),
                 output="Respuesta [ev_1].", embed_error=None, generate_error=None,
                 admit_error=None):
        self.decision = RouteDecision(intent=intent, confidence=0.9, via=via)
        self.evidence, self.experience = list(evidence), list(experience)
        self.output, self.embed_error = output, embed_error
        self.generate_error, self.admit_error = generate_error, admit_error
        self.calls: list[tuple] = []

    async def route(self, message, **kwargs):
        self.calls.append(("route", message, kwargs))
        return self.decision

    async def admit(self):
        self.calls.append(("admit",))
        if self.admit_error is not None:
            raise self.admit_error

    async def embed(self, texts):
        self.calls.append(("embed", list(texts)))
        if self.embed_error is not None:
            raise self.embed_error
        return [[0.0] * 1024]

    async def retrieve_evidence(self, session, **kwargs):
        self.calls.append(("evidence", kwargs))
        return list(self.evidence)

    async def retrieve_experience(self, session, **kwargs):
        self.calls.append(("experience", kwargs))
        return list(self.experience)

    async def generate(self, system_prompt, user_message):
        self.calls.append(("generate", system_prompt, user_message))
        if self.generate_error is not None:
            raise self.generate_error
        return self.output

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def deps(self, **overrides) -> GraphDeps:
        kwargs = dict(
            route=self.route, embed=self.embed, retrieve_evidence=self.retrieve_evidence,
            retrieve_experience=self.retrieve_experience, generate=self.generate,
            admit=self.admit, patient_context="- Revisión de los 4 meses [1]",
            retrieval_text=lambda q: q.replace("Lucía", "el bebé"),
        )
        kwargs.update(overrides)
        return GraphDeps(**kwargs)


async def _run(fakes: Fakes, message: str, *, locale="es", **deps_overrides):
    return await run_graph(
        {"surface": "demo", "locale": locale, "message": message, "account": False,
         "facts": ProfileFacts(None, None, None, None, 5)},
        fakes.deps(**deps_overrides),
    )


def test_importing_the_graph_switches_langsmith_tracing_off():
    """langgraph pulls in langsmith; a trace of this state is a baby's health
    question leaving the EU. Off by construction, whatever the environment says."""
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"


async def test_a_red_flag_stops_at_the_guard():
    fakes = Fakes()
    out = await _run(fakes, "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?")
    assert out["kind"] == "red_flag"
    assert out["answer"].startswith("Esto no puede esperar")
    assert out["evidence_citations"] and out["evidence_citations"][0]["title"]
    assert fakes.calls == [], "no gate, no route, no embedding, no model"


async def test_a_question_gets_the_short_answer_and_never_the_plan():
    fakes = Fakes(intent="question", experience=[EXPERIENCE])
    out = await _run(fakes, "¿Es normal que Lucía regurgite tras cada toma?")
    assert out["kind"] == "answer" and out["intent"] == "question"
    assert out["answer"] == "Respuesta [ev_1]."
    (_, system, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert system == chat_system_prompt("es", shape="question")
    assert "## Clinical evidence" in user and "Revisión de los 4 meses" in user
    # Experience belongs to the plan only (principle 4): not read, not cited.
    assert "experience" not in fakes.names()
    assert [c["tier"] for c in out["evidence_citations"]] == ["evidence"]


async def test_a_plan_gets_the_plan_and_reads_experience_after_the_evidence():
    fakes = Fakes(intent="plan", experience=[EXPERIENCE])
    out = await _run(fakes, "Le cuesta dormirse, ¿cómo le ayudo?")
    assert out["kind"] == "answer" and out["intent"] == "plan"
    (_, system, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert system == chat_system_prompt("es")
    assert user.index("## Clinical evidence") < user.index("## What other parents report")
    names = fakes.names()
    assert names.index("evidence") < names.index("experience") < names.index("generate")
    assert [(c["tag"], c["tier"]) for c in out["evidence_citations"]] == [
        ("ev_1", "evidence"), ("ex_1", "experience"),
    ]


async def test_the_order_is_guard_gate_route_then_retrieval():
    fakes = Fakes(intent="question")
    await _run(fakes, "¿A qué edad gatean?")
    assert fakes.names()[:4] == ["admit", "route", "embed", "evidence"]
    route_call = fakes.calls[1]
    assert route_call[1] == "¿A qué edad gatean?"
    assert route_call[2]["has_account"] is False and route_call[2]["locale"] == "es"
    assert route_call[2]["facts"].age_months == 5


async def test_the_embedding_carries_the_retrieval_text_not_the_message():
    fakes = Fakes(intent="question")
    await _run(fakes, "¿Es normal que Lucía estornude?")
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts == ["¿Es normal que el bebé estornude?"]


async def test_a_dead_classifier_falls_back_to_the_plan_path():
    fakes = Fakes(intent="plan", via="fallback")
    out = await _run(fakes, "hola, una cosa")
    assert out["intent"] == "plan" and out["kind"] == "answer"
    (_, system, _), = [c for c in fakes.calls if c[0] == "generate"]
    assert system == chat_system_prompt("es")


@pytest.mark.parametrize("intent", ["question", "plan"])
async def test_no_evidence_and_no_experience_is_the_coded_refusal(intent):
    fakes = Fakes(intent=intent, evidence=[], experience=[])
    out = await _run(fakes, "¿Qué opinas de la fibrilación auricular?")
    assert out["kind"] == "no_evidence"
    assert out["answer"] == no_evidence_reply("es")
    assert out["evidence_citations"] == []
    assert "generate" not in fakes.names()


@pytest.mark.parametrize("intent", ["question", "plan"])
async def test_no_evidence_with_experience_is_experience_only(intent):
    fakes = Fakes(intent=intent, evidence=[], experience=[EXPERIENCE], output=CLEAN_BULLETS)
    out = await _run(fakes, "¿El baño antes o después de la cena?")
    assert out["kind"] == "experience_only"
    assert out["answer"].startswith("No he encontrado guías ni estudios sobre esto.")
    (_, system, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert system == experience_only_contract("es")
    assert "Revisión de los 4 meses" not in user, "no patient data without evidence"
    assert [c["tier"] for c in out["evidence_citations"]] == ["experience"]


async def test_a_stray_experience_only_output_is_discarded_for_the_refusal():
    stray = CLEAN_BULLETS + "\n\n## Cuándo ir al médico\n- Si empeora [ex_1]."
    fakes = Fakes(intent="plan", evidence=[], experience=[EXPERIENCE], output=stray)
    out = await _run(fakes, "¿El baño antes o después de la cena?")
    assert out["kind"] == "no_evidence"


@pytest.mark.parametrize("intent", ["question", "plan"])
async def test_a_generation_failure_shows_only_the_clinical_sources(intent):
    fakes = Fakes(intent=intent, experience=[EXPERIENCE], generate_error=RuntimeError("down"))
    out = await _run(fakes, "Le cuesta dormirse, ¿cómo le ayudo?")
    assert out["kind"] == "evidence_only" and out["answer"] == ""
    assert [c["tier"] for c in out["evidence_citations"]] == ["evidence"]


async def test_an_experience_lookup_failure_costs_the_section_not_the_answer():
    async def _boom(session, **kwargs):
        raise RuntimeError("experience tier down")

    fakes = Fakes(intent="plan")
    out = await _run(fakes, "Le cuesta dormirse, ¿cómo le ayudo?", retrieve_experience=_boom)
    assert out["kind"] == "answer"
    assert [c["tier"] for c in out["evidence_citations"]] == ["evidence"]


async def test_an_embedding_failure_is_unavailable_not_an_answer():
    fakes = Fakes(intent="question", embed_error=RuntimeError("no key"))
    with pytest.raises(GraphUnavailable):
        await _run(fakes, "¿A qué edad gatean?")
    assert "generate" not in fakes.names()


async def test_the_spending_gate_refusal_reaches_the_caller_before_any_paid_call():
    class Closed(Exception):
        pass

    fakes = Fakes(admit_error=Closed())
    with pytest.raises(Closed):
        await _run(fakes, "¿A qué edad gatean?")
    assert fakes.names() == ["admit"]


async def test_retrieval_carries_the_production_cut_offs():
    from adelia.config import settings

    fakes = Fakes(intent="plan", experience=[EXPERIENCE])
    await _run(fakes, "Le cuesta dormirse, ¿cómo le ayudo?")
    (_, ev), = [c for c in fakes.calls if c[0] == "evidence"]
    (_, ex), = [c for c in fakes.calls if c[0] == "experience"]
    assert ev["specialties"] == ["pediatrics"] and ev["top_k"] == 4
    for kwargs in (ev, ex):
        assert kwargs["max_distance"] == settings.evidence_max_distance
        assert kwargs["relative_margin"] == settings.evidence_relative_margin


@pytest.mark.parametrize("locale, opening", [
    ("en", "I found no guidelines or studies on this."),
    ("fr", "Je n’ai trouvé ni recommandation ni étude sur ce sujet."),
])
async def test_the_graph_answers_in_the_parents_language(locale, opening):
    heading = {"en": "What other mothers say", "fr": "Ce que racontent d’autres mères"}[locale]
    fakes = Fakes(evidence=[], experience=[EXPERIENCE], output=f"## {heading}\n- Tip [ex_1].")
    out = await _run(fakes, "Bath before dinner?", locale=locale)
    assert out["kind"] == "experience_only" and out["answer"].startswith(opening)


async def test_the_suite_never_reaches_the_routing_provider():
    """The demo now awaits the classifier on the request path. With a key in
    the environment (server-verify with VERIFY_LIVE=1) an ambiguous question
    in any test would route by whatever the provider said that day. Only
    tests marked live_routing, or modules that drive the model layer with
    their own fakes, reach it (tests/conftest.py)."""
    from adelia.agent import route as r

    with pytest.raises(RuntimeError, match="disabled in tests"):
        await r._complete_json("system", "user")
