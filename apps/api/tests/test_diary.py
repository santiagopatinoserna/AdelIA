"""What she noted, read back (agent/diary, owner's direction of 2026-11-21).

AdelIA starts by doing one simple thing well: everything about the baby is
kept, and any question is looked up there, trends included. Until this module
the notes were write-only: «¿cuánto ha comido hoy?» had no path to them.

What these tests hold the module to: counting is code, a day with nothing
noted is not a day of zero, her words never turn into Markdown, a sibling's
notes never answer, a birth weight from a report sits at birth, and a
question the rules can read is answered without any model.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from adelia.agent import diary
from adelia.agent.diary import ALL, Note, NotesAsk, ask_from_args, parse_question, summarize
from adelia.agent.graph import LOCAL_TZ
from adelia.enrichment.profile_service import ProfileFacts

from tests.pg_gate import PG_AVAILABLE

NOW = datetime(2026, 11, 21, 18, 0, tzinfo=LOCAL_TZ)
LUCIA = ProfileFacts(None, "Lucía", date(2026, 7, 10), "F", 4)


def _at(days_ago: int, hour: int, minute: int = 0) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=minute)


def _feed(days_ago, hour, value, unit="ml", minute=0):
    return Note("feed", value, unit, _at(days_ago, hour, minute), "toma")


# --- the question ------------------------------------------------------------


@pytest.mark.parametrize("message, kinds, days", [
    ("¿Cuánto ha comido hoy?", ("feed",), 1),
    ("¿cuántas tomas lleva hoy?", ("feed",), 1),
    ("¿Cómo va su peso?", ("weight",), None),
    ("¿cuándo fue la última fiebre?", ("temperature",), None),
    ("¿Cuándo le di la última dosis de apiretal?", ("medication",), None),
    ("¿cuántos ml de apiretal le he dado hoy?", ("medication",), 1),
    ("¿cuánto ha comido y dormido esta semana?", ("feed", "sleep"), 7),
    ("¿qué he anotado hoy?", (ALL,), 1),
    ("how much has she eaten in the last 3 days?", ("feed",), 3),
    ("combien de biberons aujourd'hui ?", ("feed",), 1),
])
def test_the_rules_read_which_notes_and_how_far_back(message, kinds, days):
    ask = parse_question(message)
    assert ask is not None
    assert ask.kinds == kinds and ask.days == days


@pytest.mark.parametrize("message", [
    "¿cuánto debe comer un bebé de 4 meses?",   # a rule of thumb: sourced answer
    "hoy ha comido poco, ¿es normal?",
    "¿cuántas veces ha vomitado?",              # no kind the rules can sum: the model
    "¿cuántas veces ha vomitado? estoy preocupada",
    "ha tomado 120 ml a las 4",                 # a note to save, not a question
    # Her report may hold it in its text: the tool loop, which reads documents.
    "cuanto pesaba en la revision de los 4 meses",
])
def test_what_is_not_a_question_about_her_notes_goes_elsewhere(message):
    assert parse_question(message) is None


def test_a_question_with_no_time_takes_the_kind_default():
    assert NotesAsk(("temperature",)).window("temperature") == 3
    assert NotesAsk(("feed",)).window("feed") == 7
    assert NotesAsk(("weight",)).window("weight") is None
    assert parse_question("¿cómo va su peso desde que nació?").window("weight") is None


def test_the_tool_arguments_are_checked():
    assert ask_from_args({"kind": "biberones"}) is None
    assert ask_from_args({}) == NotesAsk((ALL,))
    assert ask_from_args({"kind": "feed", "days": 5000}).days == diary.MAX_DAYS
    assert ask_from_args({"kind": "feed", "days": 0}).days == 1
    assert ask_from_args({"kind": "feed", "days": True}).days is None


# --- the summaries -------------------------------------------------------------


def test_feeds_are_summed_per_day_newest_first():
    notes = [_feed(2, 9, 120), _feed(2, 13, 100), _feed(1, 8, 15, "min"), _feed(1, 12, 130),
             _feed(0, 9, 120), _feed(0, 15, 110, minute=10)]
    r = summarize("feed", notes, days=7, now=NOW, locale="es")
    assert r.text.splitlines()[:4] == [
        "**Tomas, últimos 7 días**",
        "- hoy: 2 tomas, 230 ml",
        "- ayer: 2 tomas, 130 ml, 15 min",
        "- 19/11: 2 tomas, 220 ml",
    ]
    assert r.text.endswith("Lo último: hoy a las 15:10, 110 ml.")
    assert r.card["type"] == "trend" and r.card["payload"]["style"] == "bars"
    assert [p["value"] for p in r.card["payload"]["points"]] == [220, 130, 230]


def test_a_day_with_nothing_noted_is_not_a_day_of_zero():
    """A week with feeds noted on two days draws two bars, not seven."""
    r = summarize("feed", [_feed(6, 9, 120), _feed(0, 9, 110)], days=7, now=NOW, locale="es")
    assert [p["label"] for p in r.card["payload"]["points"]] == ["15/11", "21/11"]
    assert "0 tomas" not in r.text


def test_one_reading_is_a_number_not_a_chart():
    r = summarize("feed", [_feed(0, 9, 110)], days=1, now=NOW, locale="es")
    assert r.card is None
    assert "- hoy: 1 toma, 110 ml" in r.text


def test_temperatures_list_every_reading_and_the_highest():
    notes = [Note("temperature", 38.4, "°C", _at(1, 15), "x"),
             Note("temperature", 38.9, "°C", _at(1, 21), "x"),
             Note("temperature", 38.2, "°C", _at(0, 7), "x")]
    r = summarize("temperature", notes, days=3, now=NOW, locale="es")
    lines = r.text.splitlines()
    assert lines[1] == "- hoy a las 07:00, 38,2 °C"
    assert lines[-1] == "La más alta: 38,9 °C, ayer a las 21:00."
    assert r.card["payload"]["style"] == "line"
    assert [p["value"] for p in r.card["payload"]["points"]] == [38.4, 38.9, 38.2]


def test_a_weight_curve_says_the_change_and_its_rate():
    notes = [Note("weight", 3.2, "kg", datetime(2026, 7, 10, 12, tzinfo=LOCAL_TZ), "Peso al nacer",
                  from_report=True),
             Note("weight", 5.1, "kg", _at(51, 10), "pesa 5,1"),
             Note("weight", 6.2, "kg", _at(3, 10), "pesa 6,2")]
    r = summarize("weight", notes, days=None, now=NOW, locale="es", facts=LUCIA)
    assert "- 10/07: 3,2 kg (informe)" in r.text
    assert "Desde el 10/07: +3 kg en 131 días (+23 g al día)." in r.text
    # The WHO table has no row at 4 months: no percentile is said, and above all
    # not the one at birth, which would read as today's.
    assert "Percentil" not in r.text


def test_a_percentile_is_said_when_the_last_weighing_has_one():
    born = date(2026, 9, 21)  # two months old on NOW
    facts = ProfileFacts(None, "Lucía", born, "F", 2)
    notes = [Note("weight", 3.2, "kg", datetime(2026, 9, 21, 12, tzinfo=LOCAL_TZ), "x"),
             Note("weight", 5.1, "kg", _at(0, 10), "x")]
    r = summarize("weight", notes, days=None, now=NOW, locale="es", facts=facts)
    assert "Percentil OMS: " in r.text and r.text.rstrip().endswith("hoy.")


def test_a_day_she_named_without_an_hour_reads_without_one():
    """«el 12 tuvo 38,5» (agent/record, 2026-11-24) is kept at midday with timed
    false: her notes read back say the day, never a 12:00 she did not say."""
    notes = [Note("temperature", 38.5, "°C", datetime(2026, 11, 12, 12, tzinfo=LOCAL_TZ),
                  "el 12 tuvo 38,5", timed=False),
             Note("temperature", 37.9, "°C", _at(0, 7), "x")]
    r = summarize("temperature", notes, days=30, now=NOW, locale="es")
    assert "- el 12/11, 38,5 °C" in r.text
    assert "La más alta: 38,5 °C, el 12/11." in r.text
    assert "12:00" not in r.text and "- hoy a las 07:00, 37,9 °C" in r.text


def test_nothing_noted_says_so_and_offers_the_last_one():
    earlier = Note("feed", 120, "ml", _at(3, 9), "x")
    assert summarize("feed", [], days=1, now=NOW, locale="es", earlier=earlier).text == (
        "Tomas: nada anotado hoy. Lo último: el 18/11 a las 09:00, 120 ml.")
    assert summarize("stool", [], days=7, now=NOW, locale="es").text == (
        "Deposiciones: nada anotado en los últimos 7 días. Cuéntamelo cuando pase y lo anoto.")
    assert summarize(ALL, [], days=1, now=NOW, locale="en").text == "Nothing noted today."


def test_her_words_are_quoted_and_never_become_markdown():
    import re

    note = Note("medication", 2.5, "ml", _at(0, 8), "le he dado 2,5 ml de apiretal ![x](http://e.vil)")
    r = summarize("medication", [note], days=7, now=NOW, locale="es")
    assert "«le he dado 2,5 ml de apiretal \\!\\[x\\]\\(http://e.vil\\)»" in r.text
    assert re.search(r"(?<!\\)\]\(", r.text) is None


def test_everything_noted_today_keeps_the_name_of_the_medicine():
    notes = [Note("medication", 2.5, "ml", _at(0, 8), "le he dado apiretal"),
             _feed(0, 15, 110, minute=10)]
    r = summarize(ALL, notes, days=1, now=NOW, locale="es")
    assert r.text.splitlines() == [
        "**Lo anotado, hoy**",
        "- Toma: 110 ml, hoy a las 15:10",
        "- Medicación: 2,5 ml, hoy a las 08:00, «le he dado apiretal»",
    ]


@pytest.mark.parametrize("locale, heading", [
    ("en", "**Feeds, last 7 days**"), ("fr", "**Repas, 7 derniers jours**"),
])
def test_the_summary_speaks_her_language(locale, heading):
    r = summarize("feed", [_feed(1, 9, 120), _feed(0, 9, 110)], days=7, now=NOW, locale=locale)
    assert r.text.splitlines()[0] == heading


# --- her record: scope, reports, and the agent turn ----------------------------

pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


async def _child(user_id, name, *, dob=date(2026, 7, 10), default=True):
    from adelia.db import AsyncSessionLocal
    from adelia.models import Profile

    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child",
                          date_of_birth=dob, sex="F", is_default=default)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


async def _note(user_id, profile_id, kind, value, unit, at, text="x"):
    from adelia.db import AsyncSessionLocal
    from adelia.services.observations import add_observation

    async with AsyncSessionLocal() as session:
        await add_observation(session, user_id=user_id, profile_id=profile_id, kind=kind,
                              value=value, unit=unit, text=text, observed_at=at, source="agent")
        await session.commit()


async def _report_weight(user_id, profile_id, name, value, unit, day):
    """A weight her report carries. `processed_at` set: a boot must not requeue it."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import Document, Entity

    async with AsyncSessionLocal() as session:
        doc_id = uuid.uuid4()
        session.add(Document(id=doc_id, user_id=user_id, profile_id=profile_id, source="web",
                             mime_type="application/pdf", s3_key=f"users/{user_id}/{doc_id}.pdf",
                             raw_text="informe", processed_at=datetime.now(LOCAL_TZ)))
        await session.flush()
        session.add(Entity(user_id=user_id, profile_id=profile_id, document_id=doc_id,
                           entity_type="observation", name=name,
                           value={"value": value, "unit": unit}, event_date=day,
                           status="final", provenance="extracted_from_clinician_doc"))
        await session.commit()


@pg
async def test_a_sibling_notes_never_answer():
    from adelia.services.scope import Scope
    from tests.db_helpers import make_user

    user_id = await make_user()
    nora = await _child(user_id, "Nora")
    adel = await _child(user_id, "Adel", default=False)
    await _note(user_id, nora.id, "feed", 120, "ml", _at(0, 9))
    await _note(user_id, adel.id, "feed", 200, "ml", _at(0, 10))
    await _note(user_id, adel.id, "feed", 210, "ml", _at(0, 11))

    readings = await diary.read_notes(Scope(user_id, nora.id), NotesAsk(("feed",), 1),
                                      now=NOW, locale="es")
    assert "- hoy: 1 toma, 120 ml" in readings[0].text
    assert "200" not in readings[0].text and "210" not in readings[0].text


@pg
async def test_the_weight_curve_starts_at_birth_from_her_report():
    """The discharge report was read months later; its birth weight is dated at birth."""
    from adelia.services.scope import Scope
    from tests.db_helpers import make_user

    user_id = await make_user()
    lucia = await _child(user_id, "Lucía")
    facts = ProfileFacts(lucia.id, "Lucía", lucia.date_of_birth, "F", 4)
    await _report_weight(user_id, lucia.id, "Peso al nacer", 3200, "g", date(2026, 10, 1))
    await _report_weight(user_id, lucia.id, "Peso", 5.1, "kg", date(2026, 10, 1))
    await _report_weight(user_id, lucia.id, "Peso percentil", 50, "p", date(2026, 10, 1))
    await _note(user_id, lucia.id, "weight", 5.1, "kg", datetime(2026, 10, 1, 9, tzinfo=LOCAL_TZ))
    await _note(user_id, lucia.id, "weight", 6.2, "kg", _at(3, 10))

    readings = await diary.read_notes(Scope(user_id, lucia.id), NotesAsk(("weight",)),
                                      now=NOW, locale="es", facts=facts)
    text = readings[0].text
    assert "- 10/07: 3,2 kg (informe)" in text
    assert text.count("5,1 kg") == 1  # her note and the report, the same day: once
    assert "50 kg" not in text
    assert [p["value"] for p in readings[0].card["payload"]["points"]] == [3.2, 5.1, 6.2]


@pg
async def test_the_tool_reads_the_same_notes_for_the_model():
    from adelia.agent.executor import execute_tool
    from tests.db_helpers import make_user

    user_id = await make_user()
    nora = await _child(user_id, "Nora")
    facts = ProfileFacts(nora.id, "Nora", nora.date_of_birth, "F", 4)
    now = datetime.now(LOCAL_TZ)
    await _note(user_id, nora.id, "temperature", 38.1, "°C", now - timedelta(seconds=2))
    await _note(user_id, nora.id, "temperature", 38.6, "°C", now - timedelta(seconds=1))

    out = await execute_tool("consultar_anotaciones", {"kind": "temperature", "days": 1},
                             user_id=user_id, profile_id=nora.id, locale="es", facts=facts)
    assert "38,6 °C" in out.text and "La más alta: 38,6 °C" in out.text
    assert out.card is not None and out.card["type"] == "trend"
    unknown = await execute_tool("consultar_anotaciones", {"kind": "baños"},
                                 user_id=user_id, profile_id=nora.id, locale="es", facts=facts)
    assert unknown.card is None and "desconocido" in unknown.text


def _exploding_provider():
    class P:
        async def stream_step(self, *, system, messages, tools):
            raise AssertionError("a question about her notes must not call the model")
            yield  # pragma: no cover
    return P()


@pg
async def test_the_agent_answers_from_her_notes_without_a_model():
    """«¿Cuántas tomas lleva hoy?» on the panel: her numbers, in code, and the chart."""
    from adelia.agent.orchestrator import run_turn
    from tests.db_helpers import make_user

    user_id = await make_user()
    nora = await _child(user_id, "Nora")
    now = datetime.now(LOCAL_TZ)
    await _note(user_id, nora.id, "feed", 130, "ml", now - timedelta(days=1))
    await _note(user_id, nora.id, "feed", 110, "ml", now - timedelta(seconds=2))
    await _note(user_id, nora.id, "feed", 90, "ml", now - timedelta(seconds=1))

    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider):
        events = [e async for e in run_turn(user_id=user_id, profile_id=nora.id,
                                            message="¿Cuántas tomas lleva esta semana?")]
    text = "".join(e.content or "" for e in events if e.type == "token")
    assert "- hoy: 2 tomas, 200 ml" in text
    assert "- ayer: 1 toma, 130 ml" in text
    trend = [e.card for e in events if e.type == "card"]
    assert len(trend) == 1 and trend[0]["type"] == "trend"
    assert events[-1].type == "final"
    assert events[-1].citations == [] and events[-1].evidence_citations == []
