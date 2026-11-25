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
from datetime import date, datetime, timedelta
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


# --- the day she names, from birth (2026-11-24) ---------------------------------------
# Until then only "hoy", "ayer" and a clock were read: «al nacer pesó 3,2 kg» was
# stored as today's weight, a fall of four kilos on her curve, and the card could not
# go back more than a week. AdelIA keeps everything from birth (ADELIA_SIMPLE.md).

BORN = date(2026, 3, 2)  # seven months old on NOW


@pytest.mark.parametrize("text, kind, value, day", [
    ("al nacer pesó 3,2 kg", "weight", 3.2, BORN),
    ("at birth she weighed 3.2 kg", "weight", 3.2, BORN),
    ("à la naissance il pesait 3,2 kg", "weight", 3.2, BORN),
    ("a los 2 meses pesaba 5,1 kg", "weight", 5.1, date(2026, 5, 2)),
    ("con 4 meses pesó 6,3 kg", "weight", 6.3, date(2026, 7, 2)),
    ("at 2 months she weighed 5.1 kg", "weight", 5.1, date(2026, 5, 2)),
    ("à 2 mois il pesait 5,1 kg", "weight", 5.1, date(2026, 5, 2)),
    ("el 12 de octubre pesó 7,1 kg", "weight", 7.1, date(2026, 10, 12)),
    ("on 12 October she weighed 7.1 kg", "weight", 7.1, date(2026, 10, 12)),
    ("on October 12 she weighed 7.1 kg", "weight", 7.1, date(2026, 10, 12)),
    ("le 12 octobre il pesait 7,1 kg", "weight", 7.1, date(2026, 10, 12)),
    ("el 12/10 pesó 7,1 kg", "weight", 7.1, date(2026, 10, 12)),
    ("el 2/3/2026 pesó 3,3 kg", "weight", 3.3, BORN),
    ("hace 3 semanas pesó 6,8 kg", "weight", 6.8, date(2026, 10, 2)),
    ("hace un mes tuvo 38,5 de fiebre", "temperature", 38.5, date(2026, 9, 23)),
    ("2 weeks ago she weighed 6.9 kg", "weight", 6.9, date(2026, 10, 9)),
    ("il y a 2 jours elle a bu 120 ml", "feed", 120.0, date(2026, 10, 21)),
    ("anteayer se tomó 150 ml", "feed", 150.0, date(2026, 10, 21)),
])
def test_a_day_she_names_is_the_day_stored(text, kind, value, day):
    draft = rec.extract_by_rules(text, now=NOW, born=BORN)
    assert draft is not None, text
    assert (draft.kind, draft.value) == (kind, value), text
    assert draft.observed_at.astimezone(MADRID).date() == day, text
    assert draft.timed is False, text  # she said the day, not the hour


def test_a_day_without_an_hour_sits_at_midday_and_reads_without_one():
    draft = rec.extract_by_rules("al nacer pesó 3,2 kg", now=NOW, born=BORN)
    local = draft.observed_at.astimezone(MADRID)
    assert (local.hour, local.minute) == (12, 0)
    assert rec.summary(draft, locale="es", now=NOW) == "Peso: 3,2 kg, el 02/03"
    assert rec.recorded_reply(draft, None, locale="es", now=NOW) == "Anotado: 3,2 kg, el 02/03."


def test_a_day_and_an_hour_are_both_kept():
    draft = rec.extract_by_rules("el 12 de octubre a las 10 de la noche tuvo 38,5 de fiebre",
                                 now=NOW, born=BORN)
    local = draft.observed_at.astimezone(MADRID)
    assert (draft.kind, local.date(), local.hour, draft.timed) == (
        "temperature", date(2026, 10, 12), 22, True)


def test_a_day_of_another_year_says_the_year():
    january = datetime(2027, 1, 10, 9, 0, tzinfo=MADRID)
    draft = rec.extract_by_rules("el 12 de octubre pesó 7,1 kg", now=january, born=BORN)
    assert draft.observed_at.astimezone(MADRID).date() == date(2026, 10, 12)
    assert rec.summary(draft, locale="es", now=january) == "Peso: 7,1 kg, el 12/10/26"


def test_today_named_by_its_date_in_the_morning_is_not_put_in_the_afternoon():
    morning = datetime(2026, 10, 23, 9, 0, tzinfo=MADRID)
    draft = rec.extract_by_rules("el 23 de octubre pesó 7,3 kg", now=morning, born=BORN)
    assert draft.kind == "weight" and draft.observed_at <= morning
    assert rec.summary(draft, locale="es", now=morning) == "Peso: 7,3 kg, hoy"


@pytest.mark.parametrize("text, born", [
    ("el 12/10/2025 pesó 3 kg", BORN),       # before she was born
    ("hace 2 años pesó 3 kg", BORN),          # the same
    ("el 30 de octubre pesó 7 kg", BORN),     # not yet this year, and last year is before birth
    ("al nacer pesó 3,2 kg", None),           # the profile has no date of birth
    ("el 12 de octubre pesó 7,1 kg", None),   # no date of birth: the week that always held
])
def test_a_day_the_record_cannot_hold_keeps_her_words_and_no_number(text, born):
    """A number at a wrong date is worse than no number: it lands on her curve."""
    draft = rec.extract_by_rules(text, now=NOW, born=born)
    assert (draft.kind, draft.value, draft.unit) == ("note", None, None)
    assert draft.text == text and draft.observed_at == NOW


def test_fractions_are_not_dates():
    draft = rec.extract_by_rules("se ha tomado 1/2 biberón de 120 ml", now=NOW, born=BORN)
    assert draft.kind == "feed" and draft.observed_at == NOW and draft.timed


async def test_the_day_she_names_wins_over_the_models_today():
    async def _model(system, user, *, provider=None):
        return json.dumps({"kind": "vaccine", "value": None, "unit": None, "time": None,
                           "day": "today"})

    draft = await rec.extract_record("a los 2 meses le pusieron la vacuna del rotavirus",
                                     locale="es", now=NOW, complete_json=_model, born=BORN)
    assert draft.kind == "vaccine"
    assert draft.observed_at.astimezone(MADRID).date() == date(2026, 5, 2)
    assert draft.timed is False


async def test_a_note_keeps_the_day_she_named():
    async def _boom(system, user, *, provider=None):
        raise RuntimeError("429")

    draft = await rec.extract_record("el 12 de octubre empezó la guarde", locale="es", now=NOW,
                                     complete_json=_boom, born=BORN)
    assert draft.kind == "note"
    assert draft.observed_at.astimezone(MADRID).date() == date(2026, 10, 12)


def test_with_her_date_of_birth_the_card_goes_back_to_birth_and_no_further():
    birth = rec.extract_by_rules("al nacer pesó 3,2 kg", now=NOW, born=BORN)
    args = rec.draft_args(birth)
    assert args["timed"] is False
    assert rec.validate_args(args, now=NOW, born=BORN) == birth
    # Without the date of birth, the week that always held still holds.
    assert rec.validate_args(args, now=NOW) is None
    the_day_before = {**args, "observed_at": "2026-03-01T12:00:00+01:00"}
    assert rec.validate_args(the_day_before, now=NOW, born=BORN) is None
    assert rec.validate_args({**args, "timed": "no"}, now=NOW, born=BORN) is None
