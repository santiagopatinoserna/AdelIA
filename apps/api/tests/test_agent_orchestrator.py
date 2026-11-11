import pytest

from unittest.mock import patch
from uuid import uuid4
from adelia.agent.orchestrator import run_turn

async def _collect(gen):
    return [e async for e in gen]

def _fake_provider(steps, seen_systems=None):
    class P:
        def __init__(self): self._i = 0
        async def stream_step(self, *, system, messages, tools):
            if seen_systems is not None:
                seen_systems.append(system)
            for ev in steps[self._i]:
                yield ev
            self._i += 1
    return P()

# Until 2026-11-11 these three sent messages nobody could place («hi», «¿mi Hb?»,
# «¿es normal?»), which went to the tool loop; they now take the sourced answer
# (tests/test_conversation_graph.py). Her own data still goes to the loop, which
# is what these tests are about.
async def test_plain_answer_streams_tokens():
    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                         message="¿en qué percentil está?"))
    assert any(e.type == "token" and e.content == "Hola" for e in events)
    assert events[-1].type == "final"

async def test_read_tool_emits_card_then_final():
    steps = [
        [{"type": "tool_call", "id": "t1", "name": "evaluar_labs",
          "args": {"name": "Hb", "value": 9.0}}, {"type": "stop", "stop_reason": "tool_use"}],
        [{"type": "token", "text": "Tu Hb está baja."}, {"type": "stop", "stop_reason": "end_turn"}],
    ]
    from adelia.agent.executor import ToolOutcome
    from adelia.agent import cards
    outcome = ToolOutcome(text="Hb baja", card=cards.card_lab("l1", "Hb", 9.0, "g/dL", "low", "12-16", "Bajo"))
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)), \
         patch("adelia.agent.orchestrator.execute_tool", return_value=outcome):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                         message="¿mi Hb en la última analítica?"))
    assert any(e.type == "card" and e.card["type"] == "lab" for e in events)
    assert events[-1].type == "final"

async def test_write_tool_emits_confirm_and_stops():
    steps = [[{"type": "tool_call", "id": "t1", "name": "generar_briefing",
               "args": {"specialty": "peds"}}, {"type": "stop", "stop_reason": "tool_use"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None, message="haz el briefing"))
    confirms = [e for e in events if e.type == "card" and e.card["type"] == "confirm"]
    assert confirms and confirms[0].card["payload"]["tool_name"] == "generar_briefing"


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
async def test_agent_system_prompt_carries_the_answer_contract(locale):
    """Audit 4.1: /dashboard renders this agent, not the chat, and its whole
    system prompt used to be three persona sentences. It must now be bound by
    the same contract the chat is: cite or do not interpret, closing
    disclaimer, and the exact wording for "I do not know"."""
    from adelia.services.answer_contract import answer_contract, no_evidence_reply

    seen: list[str] = []
    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider",
               return_value=_fake_provider(steps, seen)):
        await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                      message="¿qué vacunas le tocan?", locale=locale))

    assert len(seen) == 1
    system = seen[0]
    assert answer_contract(locale) in system
    assert no_evidence_reply(locale) in system
    assert "[ev_1]" in system
    assert "buscar_en_expediente" in system


def test_agent_and_chat_share_one_contract():
    """Same clauses, one module. If these ever diverge again, the default
    screen is answering under different rules than the chat."""
    from adelia.services.answer_contract import (
        agent_system_prompt,
        answer_contract,
        chat_system_prompt,
    )

    for locale in ("es", "en", "fr"):
        clauses = answer_contract(locale)
        assert clauses in chat_system_prompt(locale)
        assert clauses in agent_system_prompt(locale)


# ---------------------------------------------------------------------------
# Red flags reach the default screen too (audit 3.3)
#
# /dashboard renders the agent, not the chat, so this is the surface where a
# frightened parent actually types. The provider below would answer if it were
# ever called; the assertion is that it is not.
# ---------------------------------------------------------------------------


def _exploding_provider():
    class P:
        async def stream_step(self, *, system, messages, tools):
            raise AssertionError("the generative model must not be called on a red flag")
            yield  # pragma: no cover
    return P()


async def test_a_red_flag_answers_without_calling_the_model():
    from adelia.enrichment.profile_service import ProfileFacts

    facts = ProfileFacts(profile_id=None, display_name="Adel", date_of_birth=None,
                         sex="F", age_months=2)
    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts):
        events = await _collect(run_turn(
            user_id=uuid4(), profile_id=None,
            message="Mi bebé tiene 38,2, ¿le doy paracetamol?"))
    text = "".join(e.content for e in events if e.type == "token")
    assert "112" in text
    assert "mg/kg" not in text and "paracetamol" not in text.lower()
    final = events[-1]
    assert final.type == "final"
    assert len(final.evidence_citations) == 1
    assert "NG143" in final.evidence_citations[0]["title"]


async def test_an_ordinary_question_still_reaches_the_model():
    """Since the graph (AGENT_GRAPH step 5) a fact question reaches the model
    through the chat's contract path, not the tool loop: what matters here
    is that the guard lets it through."""
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE
    from tests.test_chat_orchestrator import _evidence_match

    async def fake_stream(*args, **kwargs):
        yield "Claro"

    with patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE), \
         patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None), \
         patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[]), \
         patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024]), \
         patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
               return_value=[_evidence_match()]), \
         patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
        events = await _collect(run_turn(
            user_id=uuid4(), profile_id=None,
            message="¿cuándo empiezo con la alimentación complementaria?"))
    assert any(e.type == "token" and e.content == "Claro" for e in events)


# ---------------------------------------------------------------------------
# Citations ride the SSE (audit 3.7)
# ---------------------------------------------------------------------------


async def test_final_event_carries_one_citation_per_marker():
    """The audit's own criterion for 3.7: as many markers in the text as
    citations in the payload, and no orphan in either direction."""
    import re

    from adelia.agent.executor import ToolOutcome
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE

    outcome = ToolOutcome(
        text="Regurgita [1] y suele mejorar [ev_2].",
        citations=[{"chunk_id": "c1"}, {"chunk_id": "c2"}],
        evidence_citations=[
            {"tag": "ev_1", "title": "A"},
            {"tag": "ev_2", "title": "B"},
            {"tag": "ev_3", "title": "C"},
        ],
    )
    steps = [
        [{"type": "tool_call", "id": "t1", "name": "buscar_en_expediente",
          "args": {"query": "reflujo"}}],
        [{"type": "token", "text": "Regurgita [1] y suele mejorar [ev_1]."},
         {"type": "stop", "stop_reason": "end_turn"}],
    ]
    captured: list[list[dict]] = []

    class P:
        def __init__(self): self._i = 0
        async def stream_step(self, *, system, messages, tools):
            captured.append(list(messages))
            for ev in steps[self._i]:
                yield ev
            self._i += 1

    with patch("adelia.agent.orchestrator.get_provider", return_value=P()), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE), \
         patch("adelia.agent.orchestrator.execute_tool", return_value=outcome):
        # Her own record goes to the tool loop (AGENT_GRAPH step 5); a fact
        # question like "¿es normal que regurgite?" now takes the contract path.
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                         message="¿qué ponía en el último informe del pediatra?"))

    final = events[-1]
    assert final.type == "final"
    # Two markers were used, one evidence source was never cited: it is gone.
    assert len(final.citations) == 1
    assert len(final.evidence_citations) == 1
    assert final.evidence_citations[0]["title"] == "B"
    assert final.evidence_citations[0]["tag"] == "ev_1"
    # And the text handed to the model was renumbered to match.
    tool_result = captured[-1][-1]["content"][0]["content"]
    patient = re.findall(r"\[(\d+)\]", tool_result)
    evidence = re.findall(r"\[ev_(\d+)\]", tool_result)
    assert patient == ["1"] and evidence == ["1"]


async def test_a_turn_with_no_tool_call_reports_no_citations():
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE

    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None, message="hola"))
    assert events[-1].citations == [] and events[-1].evidence_citations == []


async def test_a_red_flag_answers_even_with_no_llm_key_configured():
    """Found live on 2026-08-31: `get_provider()` ran as the first statement
    of the turn, so a stack with no key returned an empty stream for a red
    flag. The one answer that needs no model was the one a missing model
    prevented."""
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE

    def _no_key():
        raise RuntimeError("No agent LLM key configured")

    with patch("adelia.agent.orchestrator.get_provider", _no_key), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE):
        events = await _collect(run_turn(
            user_id=uuid4(), profile_id=None,
            message="des taches qui ne s'effacent pas quand j'appuie", locale="fr"))
    text = "".join(e.content for e in events if e.type == "token")
    assert "112" in text
    assert not any(e.type == "error" for e in events)


async def test_a_normal_turn_still_surfaces_a_missing_key_as_an_error():
    """Lazy is not silent: without a red flag, a missing key must still be an
    error event and not an empty bubble."""
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE

    def _no_key():
        raise RuntimeError("No agent LLM key configured")

    with patch("adelia.agent.orchestrator.get_provider", _no_key), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE):
        events = await _collect(run_turn(
            user_id=uuid4(), profile_id=None, message="hola"))
    assert any(e.type == "error" for e in events)


async def test_the_agent_hands_the_profile_name_and_age_to_the_subject(monkeypatch):
    """settings.implicit_subject_expansion (agent/implicit_subject.py): the
    /dashboard agent searches through the chat's retrieval, with the active
    child's age in the prefix and her name counted as the subject."""
    from adelia.config import settings
    from adelia.enrichment.profile_service import ProfileFacts

    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    facts = ProfileFacts(profile_id=None, display_name="Nora", date_of_birth=None,
                         sex=None, age_months=7)
    texts: list[list[str]] = []

    async def fake_embed(batch):
        texts.append(list(batch))
        return [[0.1] * 1024 for _ in batch]

    async def fake_stream(*args, **kwargs):
        yield "Claro"

    for message in ("Tiene diarrea desde ayer, ¿qué hago?", "Nora tiene diarrea, ¿qué hago?"):
        with patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts), \
             patch("adelia.services.chat_orchestrator.detect_temporal_intent",
                   return_value=None), \
             patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks",
                   return_value=[]), \
             patch("adelia.services.chat_orchestrator.embed_texts", fake_embed), \
             patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
                   return_value=[]), \
             patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
            await _collect(run_turn(user_id=uuid4(), profile_id=None, message=message))
    assert texts == [
        ["Tiene diarrea desde ayer, ¿qué hago?",
         "Mi bebé de 7 meses: Tiene diarrea desde ayer, ¿qué hago?"],
        ["Nora tiene diarrea, ¿qué hago?"],
    ]


async def test_the_final_state_is_handed_to_an_observer_without_changing_the_stream():
    """The conversation battery (scripts/conversation_battery.py) runs a
    /dashboard turn through this very function and needs to know what the
    graph decided (kind, intent, the kind of turn), which the SSE frames do
    not carry. The frames stay exactly what the panel reads."""
    from adelia.enrichment.profile_service import ProfileFacts

    facts = ProfileFacts(profile_id=None, display_name="Adel", date_of_birth=None,
                         sex="F", age_months=2)
    seen: list[dict] = []
    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts):
        observed = await _collect(run_turn(
            user_id=uuid4(), profile_id=None, message="Tiene 38,5 de fiebre",
            on_final=seen.append))
        plain = await _collect(run_turn(
            user_id=uuid4(), profile_id=None, message="Tiene 38,5 de fiebre"))

    assert [(e.type, e.content) for e in observed] == [(e.type, e.content) for e in plain]
    (final,) = seen
    assert final["kind"] == "red_flag"
    assert final["conversation"].kind == "new"


async def test_the_stages_of_a_sourced_answer_reach_the_panel():
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE
    from tests.test_chat_orchestrator import _evidence_match

    async def fake_stream(*args, **kwargs):
        yield "Claro"

    with patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE), \
         patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None), \
         patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[]), \
         patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024]), \
         patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
               return_value=[_evidence_match()]), \
         patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
        events = await _collect(run_turn(
            user_id=uuid4(), profile_id=None,
            message="¿cuándo empiezo con la alimentación complementaria?"))
    stages = [(e.content, e.sources) for e in events if e.type == "status"]
    assert stages == [("searching", 0), ("writing", 1)]
    assert [e.type for e in events].index("status") < [e.type for e in events].index("token")


@pytest.mark.parametrize("effort", [None, "low"])
async def test_the_dashboard_hands_the_graphs_effort_to_the_answering_model(monkeypatch, effort):
    """settings.answer_effort_question (2026-11-11): the graph picks the effort, the
    agent's stream carries it to the provider; unset, the call is what it was."""
    from adelia.config import settings
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE
    from tests.test_chat_orchestrator import _evidence_match

    monkeypatch.setattr(settings, "answer_effort_question", effort)
    seen: list[dict] = []

    async def fake_stream(*args, **kwargs):
        seen.append(kwargs)
        yield "Claro"

    with patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE), \
         patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None), \
         patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[]), \
         patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024]), \
         patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
               return_value=[_evidence_match()]), \
         patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
        await _collect(run_turn(
            user_id=uuid4(), profile_id=None,
            message="¿cuándo empiezo con la alimentación complementaria?"))
    assert len(seen) == 1
    assert seen[0].get("effort") == effort
