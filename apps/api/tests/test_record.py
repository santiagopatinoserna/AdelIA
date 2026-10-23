"""`record`: what she tells the app to note, extracted, guarded, confirmed (AGENT_GRAPH step 4).

Extraction is rules first (free, deterministic, works when the small model
is rate-limited, as it was in production on 2026-10-23) and the model only
for what the rules cannot read; anything unreadable is still kept as a note.
The value goes through the guard before the card: a temperature of alarm is
never saved without the referral. What comes back from the browser on
confirm is validated again, because the browser is not trusted.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from adelia.agent import record as rec

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 23, 18, 0, tzinfo=MADRID)  # a Friday at 18:00


@pytest.mark.parametrize("text, kind, value, unit", [
    ("hoy ha tenido 37,8 a las 5 de la tarde", "temperature", 37.8, "°C"),
    ("hoy ha tenido 38 de fiebre a las 8", "temperature", 38.0, "°C"),
    ("se ha tomado 150 ml a las 4", "feed", 150.0, "ml"),
    ("ha mamado 6 veces hoy", "feed", 6.0, "count"),
    ("ha dormido 3 h seguidas esta noche", "sleep", 3.0, "h"),
    ("hoy ha hecho 2 cacas blanditas", "stool", 2.0, "count"),
    ("ha mojado 5 panales hoy", "nappy", 5.0, "count"),
    ("en la revision ha pesado 7,2 kg", "weight", 7.2, "kg"),
    ("le he dado 2,5 ml de apiretal a las 22", "medication", 2.5, "ml"),
    ("ha vomitado 1 vez despues del biberon de la noche", "symptom", 1.0, "count"),
    ("had 2 bottles of 150 ml today", "feed", 150.0, "ml"),
    ("slept 4 hours straight last night", "sleep", 4.0, "h"),
    ("a dormi 3 h cette nuit", "sleep", 3.0, "h"),
    ("elle a bu 120 ml a 16h", "feed", 120.0, "ml"),
])
def test_the_rules_read_the_diary_lines_a_mother_writes(text, kind, value, unit):
    draft = rec.extract_by_rules(text, now=NOW)
    assert draft is not None, text
    assert (draft.kind, draft.value, draft.unit) == (kind, value, unit)
    assert draft.text == text


def test_every_record_line_of_the_routing_set_is_read_by_the_rules():
    """The 12 Spanish `record` messages of the evaluation set: none falls to
    the model, so recording works with the classifier down."""
    data = json.loads((Path(__file__).parent / "data" / "routing_es.json").read_text())
    lines = [i["text"] for i in data["items"] if i["intent"] == "record"]
    assert len(lines) >= 10
    for line in lines:
        assert rec.extract_by_rules(line, now=NOW) is not None, line


@pytest.mark.parametrize("text, hour, days_back", [
    ("hoy ha tenido 37,8 a las 5 de la tarde", 17, 0),
    ("se ha tomado 150 ml a las 4", 16, 0),        # 4 at 18:00 means 16:00, not 04:00
    ("le he dado 2,5 ml de apiretal a las 22", 22, 1),  # 22:00 has not happened yet today
    ("ayer ha tenido 37,5 a las 9", 9, 1),
    ("hoy ha tenido 37,8", 18, 0),                  # no hour: now
])
def test_the_hour_she_says_is_the_hour_stored(text, hour, days_back):
    draft = rec.extract_by_rules(text, now=NOW)
    local = draft.observed_at.astimezone(MADRID)
    assert local.hour == hour
    assert local.date() == (NOW - timedelta(days=days_back)).date()


def test_a_line_the_rules_cannot_read_is_none():
    assert rec.extract_by_rules("hoy ha estado muy contento en la guarde", now=NOW) is None


async def test_the_model_fills_what_the_rules_cannot_read():
    async def _model(system, user, *, provider=None):
        return json.dumps({"kind": "symptom", "value": None, "unit": None, "time": "10:30",
                           "day": "today"})

    draft = await rec.extract_record("le ha salido un sarpullido en la tripa", locale="es",
                                     now=NOW, complete_json=_model)
    assert draft.kind == "symptom" and draft.value is None
    assert draft.observed_at.astimezone(MADRID).hour == 10


async def test_a_dead_model_still_keeps_the_line_as_a_note():
    async def _boom(system, user, *, provider=None):
        raise RuntimeError("429")

    draft = await rec.extract_record("hoy ha estado muy contento en la guarde", locale="es",
                                     now=NOW, complete_json=_boom)
    assert draft.kind == "note" and draft.value is None
    assert draft.text == "hoy ha estado muy contento en la guarde"


async def test_a_model_answer_out_of_range_is_not_trusted():
    async def _model(system, user, *, provider=None):
        return json.dumps({"kind": "temperature", "value": 378, "unit": "°C"})

    draft = await rec.extract_record("tenía treinta y siete ocho", locale="es", now=NOW,
                                     complete_json=_model)
    assert draft.kind == "note"


# --- the guard on the value -------------------------------------------------------


def test_a_fever_under_three_months_is_a_red_flag_whatever_the_wording():
    draft = rec.RecordDraft("temperature", 38.2, "°C", NOW, "treinta y ocho dos")
    flag = rec.value_flag(draft, age_months=2)
    assert flag is not None and flag.code == "fever_under_3_months"


@pytest.mark.parametrize("age, value", [(5, 38.2), (2, 37.6), (None, 38.5)])
def test_no_flag_outside_the_rule(age, value):
    draft = rec.RecordDraft("temperature", value, "°C", NOW, "x")
    assert rec.value_flag(draft, age_months=age) is None


# --- the card and the write --------------------------------------------------------


def test_the_card_shows_the_entry_exactly_as_it_will_be_saved():
    draft = rec.RecordDraft("temperature", 37.8, "°C", NOW.replace(hour=16, minute=10),
                            "hoy ha tenido 37,8")
    card = rec.confirm_card(draft, locale="es", now=NOW)
    assert card["type"] == "confirm"
    assert card["payload"]["tool_name"] == rec.RECORD_TOOL
    assert card["payload"]["title"] == "¿Lo anoto así?"
    assert card["payload"]["body"] == "Temperatura: 37,8 °C, hoy a las 16:10"
    args = card["payload"]["tool_args"]
    assert rec.validate_args(args, now=NOW) == draft


@pytest.mark.parametrize("bad", [
    {"kind": "horoscope"},
    {"value": 378},
    {"unit": "kg"},
    {"observed_at": "2026-09-01T10:00:00+02:00"},   # older than a week
    {"observed_at": "2026-10-24T10:00:00+02:00"},   # tomorrow
    {"text": "x" * 501},
    {"observed_at": "not a date"},
])
def test_args_back_from_the_browser_are_validated_again(bad):
    draft = rec.RecordDraft("temperature", 37.8, "°C", NOW, "hoy ha tenido 37,8")
    args = {**rec.draft_args(draft), **bad}
    assert rec.validate_args(args, now=NOW) is None


@pytest.mark.parametrize("locale, previous, expected", [
    ("es", None, "Anotado: 37,8 °C, hoy a las 16:10."),
    ("es", ("yesterday", 37.2), "Anotado: 37,8 °C, hoy a las 16:10. La anterior: ayer, 37,2 °C."),
    ("en", ("yesterday", 37.2), "Noted: 37.8 °C, today at 16:10. The one before: yesterday, 37.2 °C."),
])
def test_the_reply_is_one_line_with_the_comparison(locale, previous, expected):
    draft = rec.RecordDraft("temperature", 37.8, "°C", NOW.replace(hour=16, minute=10), "x")
    prev = None
    if previous is not None:
        prev = rec.RecordDraft("temperature", previous[1], "°C",
                               NOW.replace(hour=20, minute=0) - timedelta(days=1), "y")
    reply = rec.recorded_reply(draft, prev, locale=locale, now=NOW)
    assert reply.replace(" ", " ") == expected
    assert "\n" not in reply and "—" not in reply
