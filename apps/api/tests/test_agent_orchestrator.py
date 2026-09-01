import pytest

from unittest.mock import patch
from uuid import uuid4
from adelia.agent.orchestrator import run_agent_turn

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

async def test_plain_answer_streams_tokens():
    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="hi"))
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
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="¿mi Hb?"))
    assert any(e.type == "card" and e.card["type"] == "lab" for e in events)
    assert events[-1].type == "final"

async def test_write_tool_emits_confirm_and_stops():
    steps = [[{"type": "tool_call", "id": "t1", "name": "generar_briefing",
               "args": {"specialty": "peds"}}, {"type": "stop", "stop_reason": "tool_use"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="haz el briefing"))
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
        await _collect(run_agent_turn(user_id=uuid4(), profile_id=None,
                                      message="¿es normal?", locale=locale))

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
        events = await _collect(run_agent_turn(
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
    from adelia.enrichment.profile_service import UNKNOWN_PROFILE

    steps = [[{"type": "token", "text": "Claro"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=UNKNOWN_PROFILE):
        events = await _collect(run_agent_turn(
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
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None,
                                               message="¿es normal que regurgite?"))

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
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="hola"))
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
        events = await _collect(run_agent_turn(
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
        events = await _collect(run_agent_turn(
            user_id=uuid4(), profile_id=None, message="hola"))
    assert any(e.type == "error" for e in events)
