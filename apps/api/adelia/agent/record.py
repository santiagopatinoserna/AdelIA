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
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from adelia.agent import cards
from adelia.clinical import red_flags
from adelia.clinical.red_flags import normalize, temperature_in
from adelia.models import OBSERVATION_KINDS

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
#: How far back a note may be dated, and how far ahead (clock skew).
MAX_AGE = timedelta(days=7)
MAX_AHEAD = timedelta(minutes=15)
MAX_TEXT = 500


@dataclass(frozen=True)
class RecordDraft:
    kind: str
    value: float | None
    unit: str | None
    observed_at: datetime
    text: str


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


def extract_by_rules(message: str, *, now: datetime) -> RecordDraft | None:
    """One observation read without a model, or None when the rules cannot tell."""
    n = normalize(message)
    text = message.strip()[:MAX_TEXT]
    at = _when(n, now)

    def draft(kind: str, value: float | None, unit: str | None) -> RecordDraft | None:
        if value is not None and not _in_range(kind, value, unit):
            return None
        return RecordDraft(kind, value, unit, at, text)

    if (m := _MEDICATION.search(n)) is not None:
        return draft("medication", _num(m.group(1)), m.group(2))
    if (t := temperature_in(message)) is not None:
        return draft("temperature", t, "°C")
    if (m := _WEIGHT_KG.search(n)) is not None:
        return draft("weight", _num(m.group(1)), "kg")
    if (m := _FEED_ML.search(n)) is not None:
        return draft("feed", _num(m.group(1)), "ml")
    if _AWAKE.search(n) and (m := _HOURS.search(n)) is not None:
        return draft("sleep", _num(m.group(1)), "h_awake")
    if _SLEEP_VERB.search(n):
        if (m := _HOURS.search(n)) is not None:
            return draft("sleep", _num(m.group(1)), "h")
        if (m := _MINUTES.search(n)) is not None:
            return draft("sleep", _num(m.group(1)), "min")
    if (m := _STOOL.search(n)) is not None:
        return draft("stool", _num(m.group(1)), "count")
    if (m := _NAPPY.search(n)) is not None:
        return draft("nappy", _num(m.group(1)), "count")
    if _VOMIT.search(n) and (m := _TIMES.search(n)) is not None:
        return draft("symptom", _num(m.group(1)), "count")
    if (m := _SPOONS.search(n)) is not None:
        return draft("feed", _num(m.group(1)), "spoon")
    if _FEED_WORD.search(n) and (m := _TIMES.search(n)) is not None:
        return draft("feed", _num(m.group(1)), "count")
    return None


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
    provider: str | None = None,
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
    day = now - timedelta(days=1) if data.day == "yesterday" else now
    at = day
    if data.time and re.fullmatch(r"\d{1,2}:\d{2}", data.time):
        hour, minute = (int(x) for x in data.time.split(":"))
        if hour < 24 and minute < 60:
            at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if data.value is None:
        if data.kind not in VALUELESS:
            return None
        return RecordDraft(data.kind, None, None, at, message.strip()[:MAX_TEXT])
    if not _in_range(data.kind, data.value, data.unit):
        return None
    return RecordDraft(data.kind, float(data.value), data.unit, at, message.strip()[:MAX_TEXT])


async def extract_record(
    message: str, *, locale: str, now: datetime, complete_json: CompleteJson | None = None,
    provider: str | None = None,
) -> RecordDraft:
    """Rules, then the model, then a note: never None, never an invented number."""
    draft = extract_by_rules(message, now=now)
    if draft is not None:
        return draft
    if complete_json is None:
        from adelia.agent.route import _complete_json as complete_json
    try:
        draft = await extract_by_model(
            message, locale=locale, now=now, complete_json=complete_json, provider=provider
        )
    except Exception as exc:  # noqa: BLE001 - a dead model costs the structure, not the note
        logger.info("record: model extraction unavailable (%s)", type(exc).__name__)
        draft = None
    return draft or RecordDraft("note", None, None, now, message.strip()[:MAX_TEXT])


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
        return f"{day} {({'es': 'a las', 'en': 'at', 'fr': 'à'})[lang]} {clock}"
    if days == 1:
        day = {"es": "ayer", "en": "yesterday", "fr": "hier"}[lang]
    else:
        day = {"es": "el", "en": "on", "fr": "le"}[lang] + f" {at.day:02d}/{at.month:02d}"
    if not with_time:
        return day
    return f"{day} {({'es': 'a las', 'en': 'at', 'fr': 'à'})[lang]} {clock}"


def summary(draft: RecordDraft, *, locale: str, now: datetime) -> str:
    """The entry as the card shows it: "Temperatura: 37,8 °C, hoy a las 16:10"."""
    lang = _lang(locale)
    label = _KIND_LABEL[lang][draft.kind]
    value = _value_text(draft, lang)
    when = _when_text(draft.observed_at, now, lang)
    colon = " : " if lang == "fr" else ": "
    return f"{label}{colon}{value}, {when}" if value else f"{label}, {when}"


def draft_args(draft: RecordDraft) -> dict:
    return {
        "kind": draft.kind, "value": draft.value, "unit": draft.unit,
        "observed_at": draft.observed_at.isoformat(), "text": draft.text,
    }


def confirm_card(draft: RecordDraft, *, locale: str, now: datetime) -> dict:
    card = cards.card_confirm(uuid4().hex[:12], _CARD_TITLE[_lang(locale)], RECORD_TOOL,
                              draft_args(draft))
    card["payload"]["body"] = summary(draft, locale=locale, now=now)
    return card


def validate_args(args: dict, *, now: datetime) -> RecordDraft | None:
    """The card's args as they came back from the browser, or None if anything is off."""
    if not isinstance(args, dict):
        return None
    kind, value, unit = args.get("kind"), args.get("value"), args.get("unit")
    text, at_raw = args.get("text"), args.get("observed_at")
    if kind not in OBSERVATION_KINDS:
        return None
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return None
    try:
        at = datetime.fromisoformat(str(at_raw))
    except ValueError:
        return None
    if at.tzinfo is None or not (now - MAX_AGE <= at <= now + MAX_AHEAD):
        return None
    if value is None:
        if kind not in VALUELESS or unit is not None:
            return None
        return RecordDraft(kind, None, None, at, text)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not _in_range(kind, float(value), unit):
        return None
    return RecordDraft(kind, float(value), unit, at, text)


def recorded_reply(
    draft: RecordDraft, previous: RecordDraft | None, *, locale: str, now: datetime
) -> str:
    """One line: what was noted and, when comparable, the reading before it."""
    lang = _lang(locale)
    value = _value_text(draft, lang) or _KIND_LABEL[lang][draft.kind].lower()
    line = f"{_NOTED[lang]}{value}, {_when_text(draft.observed_at, now, lang)}."
    if previous is not None and previous.value is not None and previous.unit == draft.unit:
        same_day = previous.observed_at.astimezone(now.tzinfo).date() == now.date()
        when = _when_text(previous.observed_at, now, lang, with_time=same_day)
        line += f"{_BEFORE[lang]}{when}, {_value_text(previous, lang)}."
    return line


def as_draft(row) -> RecordDraft:
    """An `Observation` row as a draft, for the comparison line."""
    return RecordDraft(row.kind, row.value, row.unit, row.observed_at, row.text)


__all__ = [
    "RECORD_TOOL", "RecordDraft", "as_draft", "confirm_card", "draft_args", "extract_by_rules",
    "extract_record", "recorded_reply", "summary", "validate_args", "value_flag",
]
