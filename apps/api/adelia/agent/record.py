"""The `record` node's logic: read a diary line, guard it, confirm it, write it.

AGENT_GRAPH build step 4. A mother writes "hoy ha tenido 37,8 a las 5 de la
tarde" to leave it noted, not to get a plan. The graph routes that to
`record` (only with an account) and this module turns it into one
observation (migration 0023):

1. Extraction. Rules first: free, deterministic, and the only layer that
   worked in production on 2026-10-23, when the small Mistral model answered
   429 to every call. They read every `record` line of the routing set. The
   model (strict JSON, same provider choice as the route node) fills what
   the rules cannot, and is validated against plausible ranges; a line
   nobody can read is still kept, as a note.
2. Guard on the VALUE (principle 1). The message already went through
   `clinical/red_flags`, but a value the model read from words ("treinta y
   ocho dos") did not, so the reading is checked again on its own.
3. A confirmation card with the entry exactly as it will be saved
   (principle 3). What comes back from the browser on confirm is validated
   again: the browser is not trusted.
4. One line back, with the previous comparable reading when there is one:
   "Anotado: 37,8 °C, hoy a las 16:10. La anterior: ayer, 37,2 °C."

The day she names (2026-11-24). AdelIA keeps everything from birth
(docs/specs/ADELIA_SIMPLE.md), and until then only "hoy", "ayer" and a clock
were read: «al nacer pesó 3,2 kg» went in as today's weight, a fall of four
kilos on her curve, and the card refused anything older than a week. The rules
now read the day in the line (at birth, at N months, N weeks ago, 12 October,
12/10), the floor is the day she was born, and a day this record cannot hold
(before the birth, not yet come) keeps her words as a note with no number:
a number at the wrong date is worse than none.
"""
from __future__ import annotations

import calendar
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from adelia.agent import cards
from adelia.clinical import red_flags
from adelia.clinical.red_flags import normalize, temperature_in
from adelia.models import OBSERVATION_KINDS
from adelia.services import usage

logger = logging.getLogger(__name__)

#: The write tool the confirmation card carries (agent canvas -> card_action).
RECORD_TOOL = "registrar_observacion"

#: (kind, unit) -> plausible range. A value outside it is not stored as that
#: kind: a typo, a misread unit or a model that invented a number.
RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("temperature", "°C"): (34.0, 43.0),
    ("feed", "ml"): (1, 400),
    ("feed", "min"): (1, 120),
    ("feed", "count"): (1, 20),
    ("feed", "spoon"): (1, 30),
    ("sleep", "h"): (0.1, 24),
    ("sleep", "min"): (1, 600),
    ("sleep", "h_awake"): (0.1, 12),
    ("stool", "count"): (0, 20),
    ("nappy", "count"): (0, 30),
    ("weight", "kg"): (1.5, 30),
    ("medication", "ml"): (0.1, 30),
    ("medication", "mg"): (1, 2000),
    ("symptom", "count"): (0, 50),
}
#: Kinds that may be stored with no value at all.
VALUELESS = {"symptom", "medication", "vaccine", "note"}
#: How far back a note may be dated when the profile has no date of birth (with
#: one, the floor is the day she was born), and how far ahead (clock skew).
MAX_AGE = timedelta(days=7)
MAX_AHEAD = timedelta(minutes=15)
MAX_TEXT = 500
#: A day named without an hour is stored at midday, away from both midnights, so
#: no time zone moves it to another day. It reads as the day alone (`timed`).
MIDDAY = time(12, 0)


@dataclass(frozen=True)
class RecordDraft:
    kind: str
    value: float | None
    unit: str | None
    observed_at: datetime
    text: str
    #: False when she named the day but not the hour (migration 0029).
    timed: bool = True


# --- extraction: rules ---------------------------------------------------------

_NUM = r"(\d{1,4}(?:[.,]\d{1,3})?)"


def _num(raw: str) -> float:
    return float(raw.replace(",", "."))


_MEDICATION = re.compile(
    r"\b(?:le he dado|le di|le hemos dado|le ha dado|le han dado|gave (?:her|him|it)|"
    r"(?:je )?lui ai donne|on lui a donne)\b.*?" + _NUM + r"\s*(ml|mg)\b"
)
_WEIGHT_KG = re.compile(_NUM + r"\s*(?:kg|kilos?)\b")
_FEED_ML = re.compile(_NUM + r"\s*(?:ml|cc|mililitros?)\b")
_SLEEP_VERB = re.compile(r"\b(?:dormid\w*|duerme|siestas?|slept|sleep|naps?|napped|dormi|dort|sieste)\b")
_AWAKE = re.compile(r"\b(?:despiert\w*|awake|eveille\w*|reveille\w*)\b")
_HOURS = re.compile(_NUM + r"\s*(?:h|horas?|hours?|hrs?|heures?)\b")
_MINUTES = re.compile(_NUM + r"\s*(?:min|minutos?|minutes?)\b")
_STOOL = re.compile(r"(\d{1,2})\s*(?:cacas?|deposiciones|poops?|stools?|selles)\b")
_NAPPY = re.compile(r"(\d{1,2})\s*(?:panales|pañales|nappies|diapers|couches)\b")
_FEED_WORD = re.compile(r"\b(?:mamado|mamar|tomas?|biberon(?:es)?|bottles?|feeds?|fed|tetee?s?|biberons?)\b")
_TIMES = re.compile(r"(\d{1,2})\s*(?:veces|vez|times|fois|tomas|biberones|bottles|feeds)\b")
_VOMIT = re.compile(r"\b(?:vomitado|vomita|vomited|threw up|vomi)\b")
_SPOONS = re.compile(r"(\d{1,2})\s*(?:cucharadas?|cucharaditas?|spoons?|spoonfuls?|cuilleres?)\b")

# Time of day: "a las 5 de la tarde", "a las 22", "at 4 pm", "a 16h".
_CLOCK = re.compile(
    r"\b(?:a las|a la|at|a)\s+(\d{1,2})(?:(?::|\.|h\s*)(\d{2}))?\s*h?\b"
    r"(?:\s*(de la tarde|de la noche|de la madrugada|de la manana|pm|am|du soir|du matin|"
    r"de l'apres-midi))?"
)
_LATER_HALF = {"de la tarde", "de la noche", "pm", "du soir", "de l'apres-midi"}
_YESTERDAY = re.compile(r"\b(?:ayer|yesterday|hier)\b")


def _when(n: str, now: datetime) -> datetime:
    """The moment she means, in `now`'s time zone. Defaults to now."""
    day = now - timedelta(days=1) if _YESTERDAY.search(n) else now
    m = _CLOCK.search(n)
    if m is None:
        return day
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return day
    period = m.group(3)
    if period in _LATER_HALF and hour < 12:
        hour += 12
    candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if period is not None or day is not now:
        # Said with a period, or about yesterday: the hour as written.
        return candidate if candidate <= now + MAX_AHEAD else candidate - timedelta(days=1)
    # Today with a bare hour: "a las 4" at six in the evening is 16:00. Take
    # the latest of h and h+12 that has already happened; if neither has,
    # she means yesterday (a dose "a las 22" noted the next morning).
    options = [candidate]
    if hour < 12:
        options.append(candidate.replace(hour=hour + 12))
    past = [o for o in options if o <= now + MAX_AHEAD]
    return max(past) if past else max(options) - timedelta(days=1)


# --- the day she names --------------------------------------------------------------
# Patterns are accent-free, like everything `normalize` hands them.

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
_COUNTS = {
    "un": 1, "una": 1, "uno": 1, "une": 1, "a": 1, "an": 1, "one": 1,
    "dos": 2, "two": 2, "deux": 2, "tres": 3, "three": 3, "trois": 3,
    "cuatro": 4, "four": 4, "quatre": 4, "cinco": 5, "five": 5, "cinq": 5,
    "seis": 6, "six": 6, "siete": 7, "seven": 7, "sept": 7, "ocho": 8, "eight": 8,
    "huit": 8, "nueve": 9, "nine": 9, "neuf": 9, "diez": 10, "ten": 10, "dix": 10,
    "once": 11, "eleven": 11, "onze": 11, "doce": 12, "twelve": 12, "douze": 12,
}
#: Unit -> (days, months) per one of it.
_UNITS = {
    "dia": (1, 0), "dias": (1, 0), "day": (1, 0), "days": (1, 0), "jour": (1, 0),
    "jours": (1, 0), "semana": (7, 0), "semanas": (7, 0), "week": (7, 0), "weeks": (7, 0),
    "semaine": (7, 0), "semaines": (7, 0), "mes": (0, 1), "meses": (0, 1), "month": (0, 1),
    "months": (0, 1), "mois": (0, 1), "ano": (0, 12), "anos": (0, 12), "year": (0, 12),
    "years": (0, 12), "an": (0, 12), "ans": (0, 12),
}


def _alternation(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_COUNT = rf"(\d{{1,3}}|{_alternation(_COUNTS)})"
_UNIT = rf"({_alternation(_UNITS)})"
_MONTH = rf"({_alternation(_MONTHS)})"
_AT_BIRTH = re.compile(
    r"\b(?:al nacer|nada mas nacer|al nacimiento|en el nacimiento|cuando nacio|at birth|"
    r"when (?:she|he|they) was born|a la naissance|quand (?:il|elle) est nee?)\b"
)
# An age, so a day after birth: "a los 2 meses", "con 4 meses", "at 2 months", "à 2 mois".
# "con" only with months («con 2 días de fiebre» is how long, not when), and never
# "il a 2 mois": he IS two months old, which is today.
_AT_AGE = re.compile(
    rf"\b(?:a los|a las|at|(?<!il )(?<!elle )(?<!on )a)\s+{_COUNT}\s+{_UNIT}\b"
    rf"|\bcon\s+{_COUNT}\s+(mes(?:es)?)\b")
_AGO = re.compile(rf"\b(?:hace|il y a)\s+{_COUNT}\s+{_UNIT}\b|\b{_COUNT}\s+{_UNIT}\s+ago\b")
_TWO_DAYS_AGO = re.compile(
    r"\b(?:anteayer|antes de ayer|the day before yesterday|avant-hier|avant hier)\b")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:er|st|nd|rd|th)?\s+(?:de\s+|of\s+)?{_MONTH}\b"
    rf"(?:,?\s+(?:de\s+|del\s+)?(\d{{4}}))?")
_MONTH_DAY = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")
# 12/10 only after an article ("el 12/10"), or with its year: "1/2 biberón" is half.
_NUMERIC = re.compile(
    r"\b(?:el|del|dia|on|the|le|du)\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b"
    r"|\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

class _Out:
    """A day she named that this record cannot hold: before the birth, not come
    yet, or "al nacer" on a profile with no date of birth."""


OUT = _Out()


def _count(word: str) -> int:
    return int(word) if word.isdigit() else _COUNTS[word]


def _shift(day: date, count: int, unit: str) -> date:
    days, months = _UNITS[unit]
    if months:
        year, month = divmod(day.month - 1 + count * months, 12)
        year, month = day.year + year, month + 1
        return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    return day + timedelta(days=count * days)


def _calendar_day(day: int, month: int, year: str | None, today: date) -> date | None:
    """12 October with its year, or the latest 12 October that is not after today."""
    if year:
        try:
            return date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        except ValueError:
            return None
    for back in range(5):  # 29 February waits for its leap year
        try:
            candidate = date(today.year - back, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def _pair(m: re.Match) -> tuple[str, str]:
    """(count, unit) from a pattern with two alternatives of two groups each."""
    return (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))


def _day_named(n: str, today: date, born: date | None) -> tuple[date, str] | _Out | None:
    """The day the line names and the line without those words, None when it names
    none, or OUT. The words go before the clock is read: «à 2 mois» is no 02:00.
    "Ago" before "at": «il y a 2 jours» also holds «a 2 jours»."""
    def found(day: date | None, m: re.Match) -> tuple[date, str] | _Out:
        return OUT if day is None else (day, f"{n[:m.start()]} {n[m.end():]}")

    if (m := _AT_BIRTH.search(n)) is not None:
        return found(born, m)
    if (m := _AGO.search(n)) is not None:
        count, unit = _pair(m)
        return found(_shift(today, -_count(count), unit), m)
    if (m := _AT_AGE.search(n)) is not None:
        count, unit = _pair(m)
        return found(_shift(born, _count(count), unit) if born else None, m)
    if (m := _TWO_DAYS_AGO.search(n)) is not None:
        return found(today - timedelta(days=2), m)
    if (m := _DAY_MONTH.search(n)) is not None:
        return found(_calendar_day(int(m.group(1)), _MONTHS[m.group(2)], m.group(3), today), m)
    if (m := _MONTH_DAY.search(n)) is not None:
        return found(_calendar_day(int(m.group(2)), _MONTHS[m.group(1)], m.group(3), today), m)
    if (m := _NUMERIC.search(n)) is not None:
        day, month, year = m.group(1, 2, 3) if m.group(1) else m.group(4, 5, 6)
        if not 1 <= int(month) <= 12:
            return OUT
        return found(_calendar_day(int(day), int(month), year, today), m)
    return None


def _floor(now: datetime, born: date | None) -> datetime:
    if born is None:
        return now - MAX_AGE
    return datetime.combine(born, time.min, tzinfo=now.tzinfo)


def _holds(at: datetime, now: datetime, born: date | None) -> bool:
    """Whether this record can hold a moment: from birth (a week back when the date
    of birth is unknown) to now. The card and the write check the same thing."""
    return _floor(now, born) <= at <= now + MAX_AHEAD


def _clock_on(rest: str) -> tuple[int, int] | None:
    """The hour written in the line, as written ("a las 10 de la noche": 22:00)."""
    m = _CLOCK.search(rest)
    if m is None:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    if m.group(3) in _LATER_HALF and hour < 12:
        hour += 12
    return hour, minute


def _moment(n: str, now: datetime, born: date | None) -> tuple[datetime, bool, bool] | _Out:
    """(when, timed, named): the moment the line means. `named` when she said the
    day herself. OUT for a day this record cannot hold."""
    named = _day_named(n, now.date(), born)
    if named is None:
        return _when(n, now), True, False
    if isinstance(named, _Out):
        return OUT
    day, rest = named
    clock = _clock_on(rest)
    if clock is not None:
        at, timed = datetime.combine(day, time(*clock), tzinfo=now.tzinfo), True
    else:
        # Today named by its date before midday stays in the past.
        at, timed = min(datetime.combine(day, MIDDAY, tzinfo=now.tzinfo), now), False
    return (at, timed, True) if _holds(at, now, born) else OUT


def _reading(n: str, message: str) -> tuple[str, float, str] | None:
    """(kind, value, unit) the rules read in a line, range not checked yet."""
    if (m := _MEDICATION.search(n)) is not None:
        return "medication", _num(m.group(1)), m.group(2)
    if (t := temperature_in(message)) is not None:
        return "temperature", t, "°C"
    if (m := _WEIGHT_KG.search(n)) is not None:
        return "weight", _num(m.group(1)), "kg"
    if (m := _FEED_ML.search(n)) is not None:
        return "feed", _num(m.group(1)), "ml"
    if _AWAKE.search(n) and (m := _HOURS.search(n)) is not None:
        return "sleep", _num(m.group(1)), "h_awake"
    if _SLEEP_VERB.search(n):
        if (m := _HOURS.search(n)) is not None:
            return "sleep", _num(m.group(1)), "h"
        if (m := _MINUTES.search(n)) is not None:
            return "sleep", _num(m.group(1)), "min"
    if (m := _STOOL.search(n)) is not None:
        return "stool", _num(m.group(1)), "count"
    if (m := _NAPPY.search(n)) is not None:
        return "nappy", _num(m.group(1)), "count"
    if _VOMIT.search(n) and (m := _TIMES.search(n)) is not None:
        return "symptom", _num(m.group(1)), "count"
    if (m := _SPOONS.search(n)) is not None:
        return "feed", _num(m.group(1)), "spoon"
    if _FEED_WORD.search(n) and (m := _TIMES.search(n)) is not None:
        return "feed", _num(m.group(1)), "count"
    return None


def extract_by_rules(message: str, *, now: datetime,
                     born: date | None = None) -> RecordDraft | None:
    """One observation read without a model, or None when the rules cannot tell."""
    n = normalize(message)
    text = message.strip()[:MAX_TEXT]
    moment = _moment(n, now, born)
    if isinstance(moment, _Out):
        return RecordDraft("note", None, None, now, text)
    at, timed, _ = moment
    reading = _reading(n, message)
    if reading is None:
        return None
    kind, value, unit = reading
    if not _in_range(kind, value, unit):
        return None
    return RecordDraft(kind, value, unit, at, text, timed)


def dated_reading(message: str) -> bool:
    """A reading the rules can store, said with its own day: «al nacer pesó 3,2 kg»,
    «hace 3 semanas pesó 6,8». The route node sends such a line to `record` by
    rule: the past tense there is the preterite («pesó», «tomó»), which its
    compound-past rule («ha tenido») does not read."""
    n = normalize(message)
    return _day_named(n, date.today(), None) is not None and _reading(n, message) is not None


def _in_range(kind: str, value: float, unit: str | None) -> bool:
    bounds = RANGES.get((kind, unit or ""))
    return bounds is not None and bounds[0] <= value <= bounds[1]


# --- extraction: model ------------------------------------------------------------

_MODEL_PROMPT = """A parent writes ONE line to note something about their baby.
Return a single JSON object and nothing else:
{{"kind": "<one of {kinds}>", "value": <number or null>, "unit": "<one of {units} or null>",
  "time": "<HH:MM 24h or null>", "day": "<today|yesterday>"}}
temperature in °C; feed in ml, min, count or spoon; sleep in h, min or h_awake;
stool, nappy and symptom episodes as count; weight in kg; medication in ml or mg.
If nothing fits, kind "note" with value null. Never explain. JSON only."""


class _ModelRecord(BaseModel):
    kind: str
    value: float | None = None
    unit: str | None = None
    time: str | None = None
    day: str | None = None


CompleteJson = Callable[..., Awaitable[str]]


async def extract_by_model(
    message: str, *, locale: str, now: datetime, complete_json: CompleteJson,
    provider: str | None = None, born: date | None = None,
) -> RecordDraft | None:
    units = sorted({u for (_, u) in RANGES})
    system = _MODEL_PROMPT.format(kinds=", ".join(OBSERVATION_KINDS), units=", ".join(units))
    raw = await complete_json(system, f"[{locale}] {message.strip()}", provider=provider)
    try:
        data = _ModelRecord.model_validate(json.loads(raw.strip().strip("`")))
    except (ValueError, ValidationError, TypeError):
        return None
    if data.kind not in OBSERVATION_KINDS:
        return None
    # The day she named is read by the rules, the same way for every line: the
    # model only says today or yesterday.
    moment = _moment(normalize(message), now, born)
    if isinstance(moment, _Out):
        return None
    at, timed, named = moment
    if not named:
        day = now - timedelta(days=1) if data.day == "yesterday" else now
        at, timed = day, True
        if data.time and re.fullmatch(r"\d{1,2}:\d{2}", data.time):
            hour, minute = (int(x) for x in data.time.split(":"))
            if hour < 24 and minute < 60:
                at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    text = message.strip()[:MAX_TEXT]
    if data.value is None:
        if data.kind not in VALUELESS:
            return None
        return RecordDraft(data.kind, None, None, at, text, timed)
    if not _in_range(data.kind, data.value, data.unit):
        return None
    return RecordDraft(data.kind, float(data.value), data.unit, at, text, timed)


async def extract_record(
    message: str, *, locale: str, now: datetime, complete_json: CompleteJson | None = None,
    provider: str | None = None, born: date | None = None,
) -> RecordDraft:
    """Rules, then the model, then a note: never None, never an invented number.
    `born` is the child's date of birth: the floor of the day she may name."""
    draft = extract_by_rules(message, now=now, born=born)
    if draft is not None:
        return draft
    if complete_json is None:
        from adelia.agent.route import _complete_json as complete_json
    try:
        with usage.json_purpose("record"):
            draft = await extract_by_model(
                message, locale=locale, now=now, complete_json=complete_json, provider=provider,
                born=born,
            )
    except Exception as exc:  # noqa: BLE001 - a dead model costs the structure, not the note
        logger.info("record: model extraction unavailable (%s)", type(exc).__name__)
        draft = None
    if draft is not None:
        return draft
    moment = _moment(normalize(message), now, born)
    at, timed = (now, True) if isinstance(moment, _Out) else moment[:2]
    return RecordDraft("note", None, None, at, message.strip()[:MAX_TEXT], timed)


# --- the guard on the value ------------------------------------------------------


def value_flag(draft: RecordDraft, *, age_months: int | None):
    """The red flag a recorded value raises on its own, or None.

    The synthetic line carries the number and its unit and nothing else: the
    word "fiebre" alone fires the under-3-months rule (NG143 1.1.6), and
    here the question is what THIS reading means.
    """
    if draft.kind != "temperature" or draft.value is None:
        return None
    return red_flags.detect(f"{draft.value:.1f} °C", age_months=age_months)


# --- the card, the args, the reply ---------------------------------------------------

_KIND_LABEL = {
    "es": {"temperature": "Temperatura", "feed": "Toma", "sleep": "Sueño",
           "stool": "Deposiciones", "nappy": "Pañales mojados", "weight": "Peso",
           "symptom": "Síntoma", "medication": "Medicación", "vaccine": "Vacuna",
           "note": "Nota"},
    "en": {"temperature": "Temperature", "feed": "Feed", "sleep": "Sleep", "stool": "Stools",
           "nappy": "Wet nappies", "weight": "Weight", "symptom": "Symptom",
           "medication": "Medicine", "vaccine": "Vaccine", "note": "Note"},
    "fr": {"temperature": "Température", "feed": "Repas", "sleep": "Sommeil",
           "stool": "Selles", "nappy": "Couches mouillées", "weight": "Poids",
           "symptom": "Symptôme", "medication": "Médicament", "vaccine": "Vaccin",
           "note": "Note"},
}
_UNIT_WORD = {
    "es": {"count": "", "spoon": "cucharadas", "h_awake": "h despierto"},
    "en": {"count": "", "spoon": "spoons", "h_awake": "h awake"},
    "fr": {"count": "", "spoon": "cuillères", "h_awake": "h éveillé"},
}
_CARD_TITLE = {"es": "¿Lo anoto así?", "en": "Shall I note it like this?",
               "fr": "Je le note comme ça ?"}
_NOTED = {"es": "Anotado: ", "en": "Noted: ", "fr": "C’est noté : "}
_BEFORE = {"es": " La anterior: ", "en": " The one before: ", "fr": " La précédente : "}


def _lang(locale: str) -> str:
    return locale if locale in _KIND_LABEL else "es"


def _number(value: float, lang: str) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if lang in ("es", "fr") else text


def _value_text(draft: RecordDraft, lang: str) -> str | None:
    if draft.value is None:
        return None
    unit = _UNIT_WORD[lang].get(draft.unit or "", draft.unit or "")
    space = " " if lang == "fr" else " "
    return f"{_number(draft.value, lang)}{space}{unit}".strip()


def _clock(at: datetime, lang: str) -> str:
    if lang == "fr":
        return f"{at.hour} h {at.minute:02d}"
    return f"{at.hour:02d}:{at.minute:02d}"


def _when_text(at: datetime, now: datetime, lang: str, *, with_time: bool = True) -> str:
    at = at.astimezone(now.tzinfo)
    days = (now.date() - at.date()).days
    clock = _clock(at, lang)
    if days == 0:
        day = {"es": "hoy", "en": "today", "fr": "aujourd’hui"}[lang]
        if not with_time:
            return day
        return f"{day} {({'es': 'a las', 'en': 'at', 'fr': 'à'})[lang]} {clock}"
    if days == 1:
        day = {"es": "ayer", "en": "yesterday", "fr": "hier"}[lang]
    else:
        # The year once it is not this one, as agent/diary writes it: a record from
        # birth spans two of them.
        year = f"/{at.year % 100:02d}" if at.year != now.year else ""
        day = {"es": "el", "en": "on", "fr": "le"}[lang] + f" {at.day:02d}/{at.month:02d}{year}"
    if not with_time:
        return day
    return f"{day} {({'es': 'a las', 'en': 'at', 'fr': 'à'})[lang]} {clock}"


def summary(draft: RecordDraft, *, locale: str, now: datetime) -> str:
    """The entry as the card shows it: "Temperatura: 37,8 °C, hoy a las 16:10"."""
    lang = _lang(locale)
    label = _KIND_LABEL[lang][draft.kind]
    value = _value_text(draft, lang)
    when = _when_text(draft.observed_at, now, lang, with_time=draft.timed)
    colon = " : " if lang == "fr" else ": "
    return f"{label}{colon}{value}, {when}" if value else f"{label}, {when}"


def entry_text(draft: RecordDraft, *, locale: str) -> str:
    """The entry without its moment, as Historial lists it under its day:
    "Temperatura: 37,8 °C". With no number, her own words ("Síntoma: tos por la
    noche"): the label alone ("Síntoma") would keep the note and lose what it says."""
    lang = _lang(locale)
    colon = " : " if lang == "fr" else ": "
    what = _value_text(draft, lang) or " ".join(draft.text.split())
    return f"{_KIND_LABEL[lang][draft.kind]}{colon}{what}"


def draft_args(draft: RecordDraft) -> dict:
    args = {
        "kind": draft.kind, "value": draft.value, "unit": draft.unit,
        "observed_at": draft.observed_at.isoformat(), "text": draft.text,
    }
    if not draft.timed:
        args["timed"] = False
    return args


def confirm_card(draft: RecordDraft, *, locale: str, now: datetime) -> dict:
    card = cards.card_confirm(uuid4().hex[:12], _CARD_TITLE[_lang(locale)], RECORD_TOOL,
                              draft_args(draft))
    card["payload"]["body"] = summary(draft, locale=locale, now=now)
    return card


def validate_args(args: dict, *, now: datetime, born: date | None = None) -> RecordDraft | None:
    """The card's args as they came back from the browser, or None if anything is off.
    The moment must be one this record holds: from birth when `born` is known."""
    if not isinstance(args, dict):
        return None
    kind, value, unit = args.get("kind"), args.get("value"), args.get("unit")
    text, at_raw, timed = args.get("text"), args.get("observed_at"), args.get("timed", True)
    if kind not in OBSERVATION_KINDS or not isinstance(timed, bool):
        return None
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return None
    try:
        at = datetime.fromisoformat(str(at_raw))
    except ValueError:
        return None
    if at.tzinfo is None or not _holds(at, now, born):
        return None
    if value is None:
        if kind not in VALUELESS or unit is not None:
            return None
        return RecordDraft(kind, None, None, at, text, timed)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not _in_range(kind, float(value), unit):
        return None
    return RecordDraft(kind, float(value), unit, at, text, timed)


def recorded_reply(
    draft: RecordDraft, previous: RecordDraft | None, *, locale: str, now: datetime
) -> str:
    """One line: what was noted and, when comparable, the reading before it."""
    lang = _lang(locale)
    value = _value_text(draft, lang) or _KIND_LABEL[lang][draft.kind].lower()
    when = _when_text(draft.observed_at, now, lang, with_time=draft.timed)
    line = f"{_NOTED[lang]}{value}, {when}."
    if previous is not None and previous.value is not None and previous.unit == draft.unit:
        same_day = previous.observed_at.astimezone(now.tzinfo).date() == now.date()
        when = _when_text(previous.observed_at, now, lang, with_time=same_day and previous.timed)
        line += f"{_BEFORE[lang]}{when}, {_value_text(previous, lang)}."
    return line


def as_draft(row) -> RecordDraft:
    """An `Observation` row as a draft, for the comparison line."""
    return RecordDraft(row.kind, row.value, row.unit, row.observed_at, row.text,
                       getattr(row, "timed", True))


__all__ = [
    "RECORD_TOOL", "RecordDraft", "as_draft", "confirm_card", "dated_reading", "draft_args",
    "entry_text", "extract_by_rules",
    "extract_record", "recorded_reply", "summary", "validate_args", "value_flag",
]
