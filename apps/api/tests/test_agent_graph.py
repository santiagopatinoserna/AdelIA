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
from adelia.clinical.golden import GOLDEN_SET, is_refusal
from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import (
    chat_system_prompt,
    experience_only_contract,
    no_evidence_reply,
    out_of_scope_age_reply,
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


async def test_a_child_of_three_or_more_stops_at_the_guard_with_the_refusal():
    """Handoff 4.1: golden B12 named a 7-year-old and reached an infant sleep
    fragment under the cut. The guard refuses in code, before the gate, the
    router and the embedding, and the gate counts the answer as a refusal."""
    fakes = Fakes()
    out = await _run(fakes, "How many hours of sleep does my 7-year-old need?", locale="en")
    assert out["kind"] == "no_evidence"
    assert out["answer"] == out_of_scope_age_reply("en")
    assert is_refusal(out["answer"], "en")
    assert out["evidence_citations"] == [] and out["citations"] == []
    assert fakes.calls == [], "no gate, no route, no embedding, no model"


async def test_a_red_flag_about_an_older_child_still_gets_the_referral():
    """The red flags run first: a choking child is a referral at any age."""
    fakes = Fakes()
    out = await _run(fakes, "Mi hijo de 5 años se atragantó con una canica y no puede toser")
    assert out["kind"] == "red_flag"
    assert fakes.calls == []


async def test_an_older_sibling_next_to_the_baby_reaches_retrieval():
    fakes = Fakes(intent="question")
    out = await _run(fakes, "Mi hijo de 4 años tiene muchos celos del bebé, ¿qué hago?")
    assert out["kind"] == "answer"
    assert "embed" in fakes.names()


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


async def test_an_answer_carries_only_the_cards_it_cites_with_their_tags():
    """Audit 3.7, measured on 2026-11-03: Claude cited two of four fragments
    and the other two went out as cards under an answer that never names
    them (23 orphans on the prod corpus). The tags stay as the model wrote
    them, because a streamed answer has already sent its markers."""
    second, third = _match("evidence", "Second"), _match("evidence", "Third")
    fakes = Fakes(intent="question", evidence=[EVIDENCE, second, third],
                  output="Sí [ev_1], y conviene vigilarlo [ev_3].")
    out = await _run(fakes, "¿Es normal que regurgite tras cada toma?")
    assert out["kind"] == "answer"
    assert [(c["tag"], c["title"]) for c in out["evidence_citations"]] == [
        ("ev_1", "A real guideline"), ("ev_3", "Third"),
    ]


async def test_an_answer_that_cites_nothing_shows_no_clinical_card():
    """A card under an uncited answer is the "looks sourced" shape itself:
    better no card than one the parent cannot trace to a sentence."""
    fakes = Fakes(intent="question", output="Una respuesta sin ninguna cita.")
    out = await _run(fakes, "¿Es normal que regurgite tras cada toma?")
    assert out["kind"] == "answer"
    assert out["evidence_citations"] == []


MOTHERS = [_match("experience", t) for t in ("Mordedores", "Llanto", "Porteo")]


async def test_a_refusal_with_evidence_retrieved_goes_out_with_no_card():
    """B8 in prod (2026-11-05): the model refused the jaundice question and a
    colic post from the mothers tier still went out under "No tengo evidencia"."""
    fakes = Fakes(intent="plan", experience=[MOTHERS[1]], output=no_evidence_reply("es"))
    out = await _run(fakes, "Mi bebé de 4 meses tiene la piel amarilla, ¿es la ictericia?")
    assert out["kind"] == "answer"
    assert out["answer"] == no_evidence_reply("es")
    assert out["evidence_citations"] == [] and out["citations"] == []


async def test_a_refusal_in_english_carries_no_mothers_cards():
    """B17 in prod: the tongue-tie refusal came with teethers, crying and
    babywearing underneath."""
    fakes = Fakes(intent="plan", experience=MOTHERS, output=no_evidence_reply("en"))
    out = await _run(fakes, "My 6-month-old seems tongue-tied, does it need cutting?",
                     locale="en")
    assert out["evidence_citations"] == [] and out["citations"] == []


async def test_a_refusal_in_another_language_than_the_locale_is_still_a_refusal():
    fakes = Fakes(intent="plan", experience=MOTHERS, output=no_evidence_reply("en"))
    out = await _run(fakes, "Is it tongue-tie?", locale="es")
    assert out["evidence_citations"] == [] and out["citations"] == []


async def test_a_refusal_that_cites_her_record_keeps_that_citation():
    """Prod, neonatal jaundice: "el perfil es el de Lucía, de 5 meses [1]",
    then the refusal. The [1] is a fact from her record, cited, and its card
    stays; the guideline the text never cites does not."""
    from adelia.agent.graph import Retrieved

    record = {"chunk_id": "c1", "raw_quote": "Lucía, 5 meses"}

    async def _retrieve(state):
        return Retrieved(evidence=[EVIDENCE], patient_context="[1] Lucía, 5 meses",
                         citations=[record])

    fakes = Fakes(intent="question",
                  output=f"Lucía tiene 5 meses [1]. {no_evidence_reply('es')}")
    out = await _run(fakes, "¿Es normal que esté amarillo?", retrieve=_retrieve)
    assert out["citations"] == [record]
    assert out["evidence_citations"] == []


B9_MIXED = (
    "Ofrécele la verdura sin presionarla: hasta 10-15 ofertas [ev_1][ev_2].\n\n"
    f"**Dosis de melatonina:** {no_evidence_reply('es')}\n\n"
    "## Hoy\n- Vuelve a ofrecérsela unos días después [ev_2].\n\n"
    "## No olvides\n- La pediatra recomendó empezar a los 6 meses [1]."
)


async def test_a_mixed_answer_keeps_its_evidence_and_drops_mothers_it_does_not_use():
    """B9 in prod: half answered with sources, half refused, and three sleep
    posts under a vegetables-and-melatonin answer that cites none of them."""
    second = _match("evidence", "Second")
    fakes = Fakes(intent="plan", evidence=[EVIDENCE, second], experience=MOTHERS,
                  output=B9_MIXED)
    out = await _run(fakes, "Rechaza la verdura, ¿y qué dosis de melatonina le doy?")
    assert [(c["tag"], c["tier"]) for c in out["evidence_citations"]] == [
        ("ev_1", "evidence"), ("ev_2", "evidence"),
    ]


async def test_a_mixed_answer_keeps_the_mothers_it_cites():
    cited = B9_MIXED + "\n\n## Lo que cuentan otras madres\n- Probó con el puré [ex_2]."
    fakes = Fakes(intent="plan", experience=MOTHERS, output=cited)
    out = await _run(fakes, "Rechaza la verdura, ¿y qué dosis de melatonina le doy?")
    assert [(c["tag"], c["title"]) for c in out["evidence_citations"]] == [
        ("ev_1", "A real guideline"), ("ex_2", "Llanto"),
    ]


async def test_a_mixed_short_answer_keeps_its_evidence():
    """B11 in prod: what the AAP says about gas drops, cited, then the coded
    refusal for the dose. The source is the answer to the first half."""
    output = (
        "The AAP notes that gas drops have never been shown to work [ev_1].\n\n"
        f"**Simethicone dose:** {no_evidence_reply('en')}"
    )
    fakes = Fakes(intent="question", output=output)
    out = await _run(fakes, "How many drops of simethicone for trapped wind?", locale="en")
    assert [c["tag"] for c in out["evidence_citations"]] == ["ev_1"]


async def test_the_umbilical_cord_refusal_is_the_model_not_the_code():
    """Diagnosis of "¿Cuándo se le cae el cordón umbilical y cómo lo cuido?"
    (prod 2026-11-05, docs/specs/RECHAZOS_Y_TARJETAS.md): retrieval found
    three cord sources and kind stayed "answer". No node replaces a cited
    answer: given one, the graph sends it verbatim with its three cards. The
    refusal came from the model, which reads the contract's clause on a
    source for another age next to a demo baby of 5 months."""
    from adelia.demo.fixture import demo_patient_context

    cord = [_match("evidence", t) for t in ("Cuidados del cordón", "Cordón AAP", "KidsDoc")]
    cited = "Se cae entre los 5 y los 15 días [ev_1]. Mantenlo limpio y seco [ev_2][ev_3]."
    fakes = Fakes(intent="question", evidence=cord, output=cited)
    question = "¿Cuándo se le cae el cordón umbilical y cómo lo cuido?"
    out = await _run(fakes, question, patient_context=demo_patient_context("es"))
    assert out["kind"] == "answer" and out["answer"] == cited
    assert [c["tag"] for c in out["evidence_citations"]] == ["ev_1", "ev_2", "ev_3"]
    (_, system, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert "guía de recién nacidos" in system, "the clause the model obeyed"
    assert "5 meses" in user, "the demo baby's age the model reads"


async def test_evidence_only_still_shows_every_fragment():
    """No answer to cite them: the fragments ARE the answer (unchanged)."""
    second = _match("evidence", "Second")
    fakes = Fakes(evidence=[EVIDENCE, second], generate_error=RuntimeError("down"))
    out = await _run(fakes, "Le cuesta dormirse, ¿cómo le ayudo?")
    assert out["kind"] == "evidence_only"
    assert [c["tag"] for c in out["evidence_citations"]] == ["ev_1", "ev_2"]


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


async def test_the_corpus_is_searched_with_the_corpus_text_and_the_model_reads_the_original():
    """agent/corpus_query.py: a French question is embedded in Spanish, after
    the name is neutralised, and the model still answers what she wrote."""
    fakes = Fakes(intent="question")
    seen: list = []

    async def _corpus_text(text, locale):
        seen.append((text, locale))
        return "¿Es normal que el bebé estornude? (es)"

    await _run(fakes, "Est-ce normal que Lucía éternue ?", locale="fr", corpus_text=_corpus_text)
    assert seen == [("Est-ce normal que el bebé éternue ?", "fr")]
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts == ["¿Es normal que el bebé estornude? (es)"]
    (_, _, user_message), = [c for c in fakes.calls if c[0] == "generate"]
    assert "Est-ce normal que Lucía éternue ?" in user_message


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


# --- her words, rendered for the corpus (agent/lay_terms.py) ----------------------
#
# Measured in production on 2026-11-05: "Tiene el culito muy rojo del pañal" was
# refused while the corpus holds diaper dermatitis. Behind
# settings.lay_query_expansion the retrieve step also searches her sentence
# plus the corpus's clinical terms, and keeps the better distance of each
# fragment. Off by default; off means the exact calls of before.

LAY = "Tiene el culito muy rojo del pañal"


class VectorFakes(Fakes):
    """One vector per text (vector i is all i), and evidence by vector, so a
    test can tell which of the two searches found what."""

    def __init__(self, *, by_vector=None, **kwargs):
        super().__init__(**kwargs)
        self.by_vector = by_vector or {}

    async def embed(self, texts):
        self.calls.append(("embed", list(texts)))
        return [[float(i)] * 1024 for i in range(len(texts))]

    async def retrieve_evidence(self, session, **kwargs):
        self.calls.append(("evidence", kwargs))
        return list(self.by_vector.get(kwargs["query_embedding"][0], self.evidence))


def _retrieval_calls(fakes) -> list[tuple]:
    return [c for c in fakes.calls if c[0] in ("embed", "evidence", "experience")]


def test_the_expansion_is_off_by_default():
    from adelia.config import Settings

    assert Settings.model_fields["lay_query_expansion"].default is False


async def test_with_the_expansion_off_retrieval_is_exactly_what_it_was(monkeypatch):
    """The lexicon is not even read, and the calls are the calls of before."""
    from adelia.agent import lay_terms
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", False)

    def _never(*args, **kwargs):
        raise AssertionError("the lexicon is read with the expansion off")

    monkeypatch.setattr(lay_terms, "expanded_query", _never)
    monkeypatch.setattr(lay_terms, "clinical_terms", _never)
    fakes = Fakes(intent="plan", experience=[EXPERIENCE])
    out = await _run(fakes, LAY)
    cuts = {
        "max_distance": settings.evidence_max_distance,
        "relative_margin": settings.evidence_relative_margin,
    }
    assert _retrieval_calls(fakes) == [
        ("embed", [LAY]),
        ("evidence", {"query_embedding": [0.0] * 1024, "specialties": ["pediatrics"],
                      "top_k": 4, **cuts}),
        ("experience", {"query_embedding": [0.0] * 1024, "top_k": 3, **cuts}),
    ]
    assert out["kind"] == "answer"


async def test_with_the_expansion_on_her_sentence_and_the_terms_are_both_searched(monkeypatch):
    from adelia.agent.lay_terms import expanded_query
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    fakes = VectorFakes(intent="plan", experience=[EXPERIENCE])
    await _run(fakes, LAY)
    calls = _retrieval_calls(fakes)
    assert calls[0] == ("embed", [LAY, expanded_query(LAY)])
    assert "dermatitis del pañal" in calls[0][1][1]
    searches = [kwargs for name, kwargs in calls if name == "evidence"]
    assert [s["query_embedding"][0] for s in searches] == [0.0, 1.0]
    for s in searches:
        assert s["specialties"] == ["pediatrics"] and s["top_k"] == 4
        assert s["max_distance"] == settings.evidence_max_distance
        assert s["relative_margin"] == settings.evidence_relative_margin
    (_, experience), = [c for c in calls if c[0] == "experience"]
    assert experience["query_embedding"][0] == 0.0, "other mothers: her sentence only"


async def test_what_only_the_clinical_terms_found_is_an_answer_not_a_refusal(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [], 1.0: [EVIDENCE]})
    out = await _run(fakes, LAY)
    assert out["kind"] == "answer"
    assert [c["title"] for c in out["evidence_citations"]] == [EVIDENCE.source_title]


async def test_with_the_expansion_on_a_sentence_without_lay_words_is_searched_once(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    fakes = VectorFakes(intent="question")
    await _run(fakes, "¿Cuánto tiempo de pantalla puede ver?")
    calls = _retrieval_calls(fakes)
    assert calls[0] == ("embed", ["¿Cuánto tiempo de pantalla puede ver?"])
    assert [c[0] for c in calls].count("evidence") == 1


async def test_a_red_flag_never_reaches_the_lexicon(monkeypatch):
    """The guard reads her original words first; a referral costs no search."""
    from adelia.agent import lay_terms
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    read: list[str] = []
    monkeypatch.setattr(lay_terms, "expanded_query", lambda text: read.append(text))
    fakes = VectorFakes()
    out = await _run(fakes, "Tiene 2 meses, 38,5 de fiebre y granitos en el culito")
    assert out["kind"] == "red_flag"
    assert fakes.calls == [] and read == []


async def test_the_lexicon_reads_the_spanish_corpus_text_of_a_french_question(monkeypatch):
    from adelia.agent.lay_terms import expanded_query
    from adelia.config import settings

    monkeypatch.setattr(settings, "lay_query_expansion", True)

    async def _corpus_text(text, locale):
        return LAY

    fakes = VectorFakes(intent="plan")
    await _run(fakes, "Elle a les fesses toutes rouges", locale="fr", corpus_text=_corpus_text)
    assert _retrieval_calls(fakes)[0] == ("embed", [LAY, expanded_query(LAY)])


# --- when to see a doctor, from the library (agent/warning_signs.py) --------------
#
# Measured in prod on 2026-11-06 (demo, Claude): the croup plan cited AEP, AEPap
# and SEUP and then said it had no evidence on when to go to the emergency
# room. The guides say it; the paragraph was not among the four retrieved.
# Behind settings.warning_signs_retrieval, a plan whose main search found
# evidence searches the same topic plus the warning-sign words, under the same
# cut-offs, and keeps up to two new fragments. Off means the exact calls of before.

CROUP = "Tiene tos de perro por la noche, ¿qué puedo hacer en casa?"


def _with(source_of, distance, label):
    return EvidenceMatch(**{**source_of.__dict__, "chunk_id": uuid.uuid4(),
                            "content": label, "distance": distance})


MAIN = _match("evidence", "Laringitis (AEPap)")
ALARM = _with(MAIN, 0.12, "Acude a urgencias si respira con ruido en reposo")


def test_the_warning_signs_search_is_off_by_default():
    from adelia.config import Settings

    assert Settings.model_fields["warning_signs_retrieval"].default is False


async def test_with_the_warning_search_off_retrieval_is_exactly_what_it_was(monkeypatch):
    from adelia.agent import warning_signs
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    monkeypatch.setattr(settings, "lay_query_expansion", False)

    def _never(*args, **kwargs):
        raise AssertionError("the warning query is built with the setting off")

    monkeypatch.setattr(warning_signs, "warning_query", _never)
    fakes = Fakes(intent="plan", experience=[EXPERIENCE])
    out = await _run(fakes, CROUP)
    cuts = {
        "max_distance": settings.evidence_max_distance,
        "relative_margin": settings.evidence_relative_margin,
    }
    assert _retrieval_calls(fakes) == [
        ("embed", [CROUP]),
        ("evidence", {"query_embedding": [0.0] * 1024, "specialties": ["pediatrics"],
                      "top_k": 4, **cuts}),
        ("experience", {"query_embedding": [0.0] * 1024, "top_k": 3, **cuts}),
    ]
    assert out["evidence"] == [EVIDENCE]


async def test_a_plan_with_evidence_also_searches_its_warning_signs(monkeypatch):
    """One embedding call for both texts, the same cut-offs, the new fragment last."""
    from adelia.agent.warning_signs import warning_query
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN], 1.0: [MAIN, ALARM]})
    out = await _run(fakes, CROUP)
    calls = _retrieval_calls(fakes)
    assert [c for c in calls if c[0] == "embed"] == [("embed", [CROUP, warning_query(CROUP, "es")])]
    searches = [kwargs for name, kwargs in calls if name == "evidence"]
    assert [s["query_embedding"][0] for s in searches] == [0.0, 1.0]
    for s in searches:
        assert s["specialties"] == ["pediatrics"] and s["top_k"] == 4
        assert s["max_distance"] == settings.evidence_max_distance
        assert s["relative_margin"] == settings.evidence_relative_margin
    assert out["evidence"] == [MAIN, ALARM]
    (_, experience), = [c for c in calls if c[0] == "experience"]
    assert experience["query_embedding"][0] == 0.0, "other mothers: her sentence only"
    (_, _, prompt), = [c for c in fakes.calls if c[0] == "generate"]
    assert "[ev_2]" in prompt and ALARM.content in prompt


async def test_the_warning_terms_follow_the_language_of_the_question(monkeypatch):
    from adelia.agent.warning_signs import warning_query
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    question = "My baby has a barking cough at night, what can I do at home?"
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN], 1.0: [ALARM]})
    await _run(fakes, question, locale="en")
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts[-1] == warning_query(question, "en")
    assert "when to see a doctor" in texts[-1]


async def test_a_short_answer_never_runs_the_warning_search(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    fakes = VectorFakes(intent="question", by_vector={0.0: [MAIN], 1.0: [ALARM]})
    out = await _run(fakes, "¿A qué edad suelen empezar a gatear?")
    calls = _retrieval_calls(fakes)
    assert calls[0] == ("embed", ["¿A qué edad suelen empezar a gatear?"])
    assert [c[0] for c in calls].count("evidence") == 1
    assert out["evidence"] == [MAIN]


@pytest.mark.parametrize("question", [
    # B4 of the golden set, and a question the corpus does not hold either.
    next(q.question for q in GOLDEN_SET if q.id == "B4"),
    "¿Qué marca de cochecito plegable es la más ligera?",
])
async def test_without_main_evidence_the_warning_search_never_answers(monkeypatch, question):
    """The warning vector would find fragments; it is never searched, the code refuses."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [], 1.0: [ALARM]})
    out = await _run(fakes, question)
    assert out["kind"] == "no_evidence"
    assert out["answer"] == no_evidence_reply("es")
    assert [c[0] for c in _retrieval_calls(fakes)].count("evidence") == 1
    assert "generate" not in fakes.names()


async def test_a_red_flag_never_reaches_the_warning_search(monkeypatch):
    from adelia.agent import warning_signs
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    built: list[str] = []
    monkeypatch.setattr(warning_signs, "warning_query", lambda t, loc: built.append(t) or t)
    fakes = VectorFakes()
    out = await _run(fakes, "Tiene 2 meses, 38,5 de fiebre y tos de perro")
    assert out["kind"] == "red_flag"
    assert fakes.calls == [] and built == []


async def test_with_both_searches_on_the_warning_query_widens_the_lay_one(monkeypatch):
    """Her words, the corpus's terms and the warning words: three texts, one call."""
    from adelia.agent.lay_terms import expanded_query
    from adelia.agent.warning_signs import warning_query
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", True)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN], 1.0: [], 2.0: [ALARM]})
    out = await _run(fakes, CROUP)
    widened = expanded_query(CROUP)
    assert widened is not None
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts == [CROUP, widened, warning_query(widened, "es")]
    searches = [kw["query_embedding"][0] for n, kw in _retrieval_calls(fakes) if n == "evidence"]
    assert searches == [0.0, 1.0, 2.0]
    assert out["evidence"] == [MAIN, ALARM]


# The warning search returned one fragment per source, so a guideline the plan
# already cited only showed its best fragment for the warning words, a general
# one: the croup plan of 2026-11-06 never saw "cuándo acudir a urgencias".

SECOND = _match("evidence", "Laringitis, información para padres (SEUP)")


async def test_the_warning_search_is_told_which_sources_and_fragments_the_plan_holds(
    monkeypatch,
):
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN, SECOND], 1.0: []})
    await _run(fakes, CROUP)
    main, warning = [kw for name, kw in _retrieval_calls(fakes) if name == "evidence"]
    assert "cited_sources" not in main and "cited_chunks" not in main
    assert list(warning["cited_sources"]) == [MAIN.source_id, SECOND.source_id]
    assert list(warning["cited_chunks"]) == [MAIN.chunk_id, SECOND.chunk_id]


async def test_the_urgency_paragraph_of_a_cited_guideline_reaches_the_plan(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    general = _with(MAIN, 0.10, "Laringitis (AEPap). Tema: síntomas y evolución. Hallazgo: x.")
    urgent = _with(MAIN, 0.15, "Laringitis (AEPap). Tema: cuándo acudir a urgencias. "
                               "Hallazgo: si respira con ruido en reposo.")
    stranger = _with(_match("evidence", "Cómo manejar la tos"), 0.09, "Tema: qué es la tos.")
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN], 1.0: [stranger, general, urgent]})
    out = await _run(fakes, CROUP)
    assert out["evidence"] == [MAIN, urgent, general]
    (_, _, prompt), = [c for c in fakes.calls if c[0] == "generate"]
    assert "[ev_2] " in prompt and urgent.content in prompt


async def test_with_the_warning_search_off_nothing_is_told_about_cited_sources(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    fakes = VectorFakes(intent="plan", by_vector={0.0: [MAIN, SECOND]})
    out = await _run(fakes, CROUP)
    (search,) = [kw for name, kw in _retrieval_calls(fakes) if name == "evidence"]
    assert "cited_sources" not in search and "cited_chunks" not in search
    assert out["evidence"] == [MAIN, SECOND]


# --- the baby she does not name (agent/implicit_subject.py) ----------------------
#
# Measured in production on 2026-11-06: "Tiene 38,3 de fiebre desde esta mañana,
# ¿qué hago?" was refused with three fever sources at 0.197-0.205, just past the
# 0.19 cut-off, while the same worry with "Mi bebé de 10 meses" found five at
# 0.12-0.14. Behind settings.implicit_subject_expansion the retrieve step also
# searches her sentence with the baby put back ("Mi bebé de 5 meses: ..."), under
# the same cut-offs, and keeps the better distance of each fragment.

NO_SUBJECT = "Tiene 38,3 de fiebre desde esta mañana, ¿qué hago?"


def _subject_off(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "implicit_subject_expansion", False)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    monkeypatch.setattr(settings, "warning_signs_retrieval", False)


def _subject_on(monkeypatch):
    from adelia.config import settings

    _subject_off(monkeypatch)
    monkeypatch.setattr(settings, "implicit_subject_expansion", True)


async def test_with_the_subject_off_retrieval_is_exactly_what_it_was(monkeypatch):
    """The rules are not even read, and the calls are the calls of before."""
    from adelia.agent import implicit_subject
    from adelia.config import settings

    _subject_off(monkeypatch)

    def _never(*args, **kwargs):
        raise AssertionError("the subject rules are read with the setting off")

    monkeypatch.setattr(implicit_subject, "subject_query", _never)
    monkeypatch.setattr(implicit_subject, "names_someone", _never)
    fakes = Fakes(intent="plan", experience=[EXPERIENCE])
    out = await _run(fakes, NO_SUBJECT)
    cuts = {
        "max_distance": settings.evidence_max_distance,
        "relative_margin": settings.evidence_relative_margin,
    }
    assert _retrieval_calls(fakes) == [
        ("embed", [NO_SUBJECT]),
        ("evidence", {"query_embedding": [0.0] * 1024, "specialties": ["pediatrics"],
                      "top_k": 4, **cuts}),
        ("experience", {"query_embedding": [0.0] * 1024, "top_k": 3, **cuts}),
    ]
    assert out["kind"] == "answer"


async def test_with_the_subject_on_her_sentence_and_the_baby_are_both_searched(monkeypatch):
    """One embedding call, the same cut-offs on both searches, the demo's age."""
    from adelia.config import settings

    _subject_on(monkeypatch)
    fakes = VectorFakes(intent="plan", experience=[EXPERIENCE])
    await _run(fakes, NO_SUBJECT)
    calls = _retrieval_calls(fakes)
    assert calls[0] == ("embed", [NO_SUBJECT, f"Mi bebé de 5 meses: {NO_SUBJECT}"])
    searches = [kwargs for name, kwargs in calls if name == "evidence"]
    assert [s["query_embedding"][0] for s in searches] == [0.0, 1.0]
    for s in searches:
        assert s["specialties"] == ["pediatrics"] and s["top_k"] == 4
        assert s["max_distance"] == settings.evidence_max_distance
        assert s["relative_margin"] == settings.evidence_relative_margin
    (_, experience), = [c for c in calls if c[0] == "experience"]
    assert experience["query_embedding"][0] == 0.0, "other mothers: her sentence only"


async def test_what_only_the_baby_found_is_an_answer_and_the_better_distance_wins(monkeypatch):
    _subject_on(monkeypatch)
    far = _with(EVIDENCE, 0.18, "fiebre")
    near = EvidenceMatch(**{**far.__dict__, "distance": 0.13})
    fakes = VectorFakes(intent="plan", by_vector={0.0: [far], 1.0: [near]})
    out = await _run(fakes, NO_SUBJECT)
    assert out["kind"] == "answer"
    assert [m.distance for m in out["evidence"]] == [0.13]
    nothing = VectorFakes(intent="plan", by_vector={0.0: [], 1.0: [EVIDENCE]})
    assert (await _run(nothing, NO_SUBJECT))["kind"] == "answer"


async def test_with_the_subject_on_a_sentence_that_names_the_baby_is_searched_once(monkeypatch):
    _subject_on(monkeypatch)
    question = "Mi bebé de 10 meses tiene 38,5 de fiebre pero juega, ¿qué hago?"
    fakes = VectorFakes(intent="plan")
    await _run(fakes, question)
    calls = _retrieval_calls(fakes)
    assert calls[0] == ("embed", [question])
    assert [c[0] for c in calls].count("evidence") == 1


async def test_the_demo_baby_s_name_is_already_the_baby(monkeypatch):
    """retrieval_text put "el bebé" where "Lucía" was: no second search."""
    _subject_on(monkeypatch)
    fakes = VectorFakes(intent="plan")
    await _run(fakes, "Lucía tiene diarrea desde ayer")
    assert _retrieval_calls(fakes)[0] == ("embed", ["el bebé tiene diarrea desde ayer"])


async def test_a_red_flag_never_reaches_the_subject_rules(monkeypatch):
    """The guard reads her original words first; a referral costs no search."""
    from adelia.agent import implicit_subject

    _subject_on(monkeypatch)
    read: list[str] = []
    monkeypatch.setattr(implicit_subject, "subject_query",
                        lambda text, **kwargs: read.append(text))
    fakes = VectorFakes()
    out = await _run(fakes, "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?")
    assert out["kind"] == "red_flag"
    assert fakes.calls == [] and read == []


async def test_a_french_question_gets_the_baby_in_the_corpus_s_spanish(monkeypatch):
    _subject_on(monkeypatch)

    async def _corpus_text(text, locale):
        return "Tiene fiebre desde esta mañana, ¿qué hago?"

    fakes = VectorFakes(intent="plan")
    await _run(fakes, "Il a de la fièvre depuis ce matin, que faire ?", locale="fr",
               corpus_text=_corpus_text)
    assert _retrieval_calls(fakes)[0] == ("embed", [
        "Tiene fiebre desde esta mañana, ¿qué hago?",
        "Mi bebé de 5 meses: Tiene fiebre desde esta mañana, ¿qué hago?",
    ])


async def test_with_the_lexicon_on_too_each_variant_is_its_own_search(monkeypatch):
    """Her words, her words plus the terms, her words with the baby: three
    searches merged by best distance, so each flag keeps what its own
    measurement saw. The warning query still widens the lay text only."""
    from adelia.agent.lay_terms import expanded_query
    from adelia.agent.warning_signs import warning_query
    from adelia.config import settings

    _subject_on(monkeypatch)
    monkeypatch.setattr(settings, "lay_query_expansion", True)
    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    lay = "Tiene diarrea y vomita desde ayer"
    widened = expanded_query(lay)
    assert widened is not None
    fakes = VectorFakes(intent="plan", by_vector={0.0: [], 1.0: [], 2.0: [MAIN], 3.0: [ALARM]})
    out = await _run(fakes, lay)
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts == [lay, widened, f"Mi bebé de 5 meses: {lay}", warning_query(widened, "es")]
    searches = [kw["query_embedding"][0] for n, kw in _retrieval_calls(fakes) if n == "evidence"]
    assert searches == [0.0, 1.0, 2.0, 3.0]
    assert out["evidence"] == [MAIN, ALARM]


async def test_a_fever_answered_through_the_button_is_searched_with_the_baby(monkeypatch):
    """The clarify flow, both turns. "Tiene fiebre, ¿qué hago?" gets the
    thermometer question; her button comes back as a line of the message,
    which still names nobody. Off, that message is searched alone (in
    production its sources sit past the cut, so she is told there is no
    evidence); on, the baby is put back for a second search."""
    first = "Tiene fiebre, ¿qué hago?"
    absorbed = f"{first}\nTemperatura: 38 a 38,9 °C"
    turn_two = {"surface": "demo", "locale": "es", "message": first, "account": False,
                "facts": ProfileFacts(None, None, None, None, 5),
                "clarification": {"field": "temperature", "value": "38-38.9"}}

    asking = Fakes()
    asking.decision = RouteDecision(intent="clarify", confidence=0.9, via="rule",
                                    missing=["temperature"])
    _subject_on(monkeypatch)
    out = await _run(asking, first)
    assert out["kind"] == "clarify" and "embed" not in asking.names()

    _subject_off(monkeypatch)
    off = VectorFakes(intent="plan", by_vector={0.0: []})
    out = await run_graph(dict(turn_two), off.deps())
    assert _retrieval_calls(off)[0] == ("embed", [absorbed])
    assert out["kind"] == "no_evidence"

    _subject_on(monkeypatch)
    on = VectorFakes(intent="plan", by_vector={0.0: [], 1.0: [EVIDENCE]})
    out = await run_graph(dict(turn_two), on.deps())
    assert _retrieval_calls(on)[0] == ("embed", [absorbed, f"Mi bebé de 5 meses: {absorbed}"])
    assert out["kind"] == "answer"
