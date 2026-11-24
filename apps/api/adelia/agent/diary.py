"""Her notes read back: what she noted, day by day, and where it is going.

Owner's direction of 2026-11-21: AdelIA starts by doing one simple thing well.
She keeps everything about the baby in it from birth (what she notes, her
files, her recordings) and any question is looked up there, trends included.
Until then the notes were written and hardly read back: the record node
stores them (migration 0023), "Hoy" shows the latest one, and nothing
answered «¿cuánto ha comido hoy?». The rules left it to the classifier, the
tool loop searched only her documents, which hold none of her notes, and
«¿cuándo le di la última dosis de apiretal?» went to the guidelines by rule.

What this module keeps:

* Counting is code. Feeds per day, hours of sleep, the highest reading, grams
  a day: a miscounted feed reads as a fact to a mother at 3 a.m., so no model
  adds anything up.
* Her numbers, never a verdict. It says what she noted and when; whether that
  is normal needs sources and stays with the contract (`buscar_en_expediente`).
  The one reference it adds is the WHO weight percentile at each weighing,
  the table `percentil_crecimiento` already uses.
* Not noted is not zero. A day with no feed noted is left out of the list and
  of the chart, never drawn as a day she did not eat.
* Her whole record. A weight also comes from her reports (the `observation`
  entities the extractor read), so the curve starts at birth when the
  discharge report is in, not at the first weight she typed.
* Scoped like every read (services/scope): a sibling's notes never answer.

Two doors: `parse_question` reads the common questions by rule and the agent
answers them with no model (agent/orchestrator._track); the
`consultar_anotaciones` tool covers the phrasings the rules do not read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from uuid import uuid4

from adelia.agent import cards, record
from adelia.agent.pediatrics import growth_percentile
from adelia.agent.route import asks_about_notes, names_her_reports, read_shorthand
from adelia.clinical.red_flags import normalize
from adelia.enrichment.profile_service import UNKNOWN_PROFILE, ProfileFacts, age_in_months
from adelia.models import OBSERVATION_KINDS
from adelia.services.scope import Scope

#: The read tool the model calls (agent/tools.py).
TOOL = "consultar_anotaciones"
#: Every kind at once: «¿qué he anotado hoy?».
ALL = "all"
KINDS = (*OBSERVATION_KINDS, ALL)

#: How far back a question with no time in it looks. A fever is a matter of
#: days, feeds and sleep of a week, a weight curve of her whole life.
DEFAULT_DAYS: dict[str, int | None] = {
    "temperature": 3, "feed": 7, "sleep": 7, "stool": 7, "nappy": 7, "medication": 7,
    "symptom": 14, "note": 14, "vaccine": None, "weight": None, ALL: 1,
}
MAX_DAYS = 366
#: Lines of one list: a week, short enough to read with a baby in one arm.
MAX_LINES = 8
#: Rows read per kind. A year of feeds is about 3000; the newest are kept.
MAX_ROWS = 1000
#: Points of one chart: a month of days, or a weight curve from birth.
MAX_POINTS = 60


# --- the question --------------------------------------------------------------

#: The words that name each kind of note, on `normalize`d text, es/en/fr.
#: "ml" alone is not here: it is a feed unless a medicine is named.
_KIND_WORDS: dict[str, re.Pattern[str]] = {
    "feed": re.compile(
        r"\b(?:tomas?|comid[oa]|comio|comer|biberon(?:es)?|mamad[oa]|mamo|pecho|leche|"
        r"tetadas?|cucharadas?|papillas?|bebid[oa]|bebio|"
        r"feeds?|fed|eaten|ate|bottles?|milk|drank|drunk|nursed|"
        r"tetees?|biberons?|repas|mange|lait|bu)\b"),
    "sleep": re.compile(
        r"\b(?:dormid[oa]|durmio|dormir|duerme|sueno|siestas?|"
        r"slept|sleep\w*|naps?|napped|dormi|dort|sommeil|siestes?)\b"),
    "temperature": re.compile(
        r"\b(?:fiebres?|temperaturas?|febricula|fevers?|temperatures?|fievres?)\b"),
    "stool": re.compile(r"\b(?:cacas?|deposicion(?:es)?|heces|poos?|poops?|stools?|selles?)\b"),
    "nappy": re.compile(r"\b(?:panal(?:es)?|pis|nappies|nappy|diapers?|couches?)\b"),
    "weight": re.compile(
        r"\b(?:peso|pesos|pesa|pesaba|engordad[oa]|kilos?|weight|weighs?|weighed|poids|pese)\b"),
    "medication": re.compile(
        r"\b(?:medicin\w*|medicamento\w*|dosis|apiretal|dalsy|paracetamol|ibuprofeno|jarabe|"
        r"gotas|vitamina d|dose|doses|medicine|medication|syrup|drops|vitamin d|"
        r"doliprane|sirop|gouttes)\b"),
}
_ML = re.compile(r"\bml\b")
#: «¿Qué he anotado hoy?», «resumen de hoy», «mis notas»: every kind.
_EVERYTHING = re.compile(
    r"\b(?:anotado|apuntado|registrado|guardado|notas|anotaciones|apuntes|registros|resumen|"
    r"noted?|logged|log|recorded|saved|note)\b")

_LAST_N_DAYS = re.compile(r"\b(?:ultimos|last|past|derniers) (\d{1,3}) (?:dias|days|jours)\b")
_SINCE_BIRTH = re.compile(
    r"\b(?:desde que naci\w*|desde (?:el|su) nacimiento|since birth|since (?:she|he) was born|"
    r"depuis (?:la |sa )?naissance)\b")
_MONTH = re.compile(
    r"\b(?:este mes|el mes|ultimo mes|this month|last month|ce mois|le mois|dernier mois)\b")
_WEEK = re.compile(r"\b(?:semana|week|semaine)\b")
_YESTERDAY = re.compile(r"\b(?:ayer|anoche|yesterday|last night|hier|cette nuit)\b")
_TODAY = re.compile(r"\b(?:hoy|today|aujourd'hui|esta manana|this morning|ce matin)\b")


@dataclass(frozen=True)
class NotesAsk:
    """Which notes, and how far back (`days` None: the kind's default)."""

    kinds: tuple[str, ...]
    days: int | None = None
    since_birth: bool = False

    def window(self, kind: str) -> int | None:
        if self.since_birth:
            return None
        return self.days if self.days is not None else DEFAULT_DAYS[kind]


def parse_question(message: str) -> NotesAsk | None:
    """A question about what she noted, read by rule, or None for the model.

    The same test the route node used to send it here (route.asks_about_notes),
    so a question the rules routed is a question the rules can read. One that
    also names her reports («¿cuánto pesaba en la revisión de los 4 meses?»)
    stays with the tool loop: the answer may be in a document's text, which
    only `buscar_en_expediente` reads.
    """
    n = read_shorthand(normalize(message))
    if not asks_about_notes(n) or names_her_reports(n):
        return None
    kinds = [kind for kind, words in _KIND_WORDS.items() if words.search(n)]
    if _ML.search(n) and not {"feed", "medication"} & set(kinds):
        kinds.append("feed")
    if not kinds:
        if not _EVERYTHING.search(n):
            return None
        kinds = [ALL]
    days, since_birth = _window(n)
    return NotesAsk(tuple(kinds), days, since_birth)


def ask_from_args(args: dict) -> NotesAsk | None:
    """The tool's arguments, checked: the model may name a kind that does not exist."""
    kind = str(args.get("kind") or ALL)
    if kind not in KINDS:
        return None
    days = args.get("days")
    if isinstance(days, bool) or not isinstance(days, (int, float)):
        return NotesAsk((kind,))
    return NotesAsk((kind,), max(1, min(MAX_DAYS, int(days))))


def _window(n: str) -> tuple[int | None, bool]:
    if (m := _LAST_N_DAYS.search(n)) is not None:
        return max(1, min(MAX_DAYS, int(m.group(1)))), False
    if _SINCE_BIRTH.search(n):
        return None, True
    if _MONTH.search(n):
        return 30, False
    if _WEEK.search(n):
        return 7, False
    if _YESTERDAY.search(n):
        return 2, False
    if _TODAY.search(n):
        return 1, False
    return None, False


# --- reading -------------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    """One note as the summaries read it; `record`'s helpers take it as a draft."""

    kind: str
    value: float | None
    unit: str | None
    observed_at: datetime
    text: str
    #: A weight read from one of her reports, not typed by her.
    from_report: bool = False


@dataclass(frozen=True)
class Reading:
    """One kind of note read back: Markdown for her (and the model), maybe a chart."""

    kind: str
    text: str
    card: dict | None = None


def window_start(days: int | None, now: datetime) -> datetime | None:
    """Local midnight `days - 1` days ago: «hoy» is since midnight, not the last 24 h."""
    if days is None:
        return None
    first = now.date() - timedelta(days=days - 1)
    return datetime.combine(first, time.min, tzinfo=now.tzinfo)


async def read_notes(
    scope: Scope, ask: NotesAsk, *, now: datetime, locale: str,
    facts: ProfileFacts = UNKNOWN_PROFILE,
) -> list[Reading]:
    """Every kind she asked about, read in one short session and summed in code."""
    from adelia.db import AsyncSessionLocal
    from adelia.services.observations import notes_since, previous_comparable

    fetched: list[tuple[str, int | None, list[Note], Note | None]] = []
    # One session, no network I/O inside it (pool exhaustion once caused 500s).
    async with AsyncSessionLocal() as session:
        for kind in ask.kinds:
            days = ask.window(kind)
            since = window_start(days, now)
            rows = await notes_since(session, scope=scope, since=since, limit=MAX_ROWS,
                                     kinds=None if kind == ALL else (kind,))
            notes = [_note(row) for row in rows]
            if kind == "weight":
                reported = await _report_weights(session, scope, facts, since, now.tzinfo)
                notes = _merge(notes, reported, now)
            earlier = None
            if not notes and since is not None and kind != ALL:
                row = await previous_comparable(session, scope=scope, kind=kind, before=since)
                earlier = _note(row) if row is not None else None
            fetched.append((kind, days, notes, earlier))
    return [summarize(kind, notes, days=days, now=now, locale=locale, facts=facts, earlier=earlier)
            for kind, days, notes, earlier in fetched]


def reply(readings: list[Reading]) -> str:
    return "\n\n".join(r.text for r in readings)


def _note(row) -> Note:
    return Note(row.kind, row.value, row.unit, row.observed_at, row.text)


_WEIGHT_NAME = re.compile(r"^(?:peso|weight|poids)\b")
_AT_BIRTH = re.compile(r"\b(?:nacer|nacimiento|birth|naissance)\b")
_KG_UNITS = {"kg", "kgs", "kilo", "kilos", "kilogramos", "kilograms"}
_G_UNITS = {"g", "gr", "grs", "gramos", "grams", "grammes"}


async def _report_weights(session, scope: Scope, facts: ProfileFacts, since: datetime | None,
                          tz: tzinfo | None) -> list[Note]:
    """The weights her reports carry, as notes.

    A birth weight is dated at birth whatever day the report was written: a
    discharge report read at two months must not put 3,2 kg at two months.
    A value that is not a plausible baby weight in kg or g (a percentile, a
    weight-for-age ratio) is left out rather than drawn.
    """
    import sqlalchemy as sa

    from adelia.models import Entity

    rows = (await session.execute(
        sa.select(Entity.name, Entity.value, Entity.event_date)
        .where(*scope.where(Entity), Entity.entity_type == "observation",
               Entity.deleted_at.is_(None))
        .limit(500)
    )).all()
    out: list[Note] = []
    for name, value, day in rows:
        n = normalize(name or "")
        if not _WEIGHT_NAME.search(n):
            continue
        kg = _kg(value)
        if kg is None:
            continue
        if _AT_BIRTH.search(n):
            day = facts.date_of_birth
        if day is None:
            continue
        at = datetime.combine(day, time(12, 0), tzinfo=tz)
        if since is not None and at < since:
            continue
        out.append(Note("weight", kg, "kg", at, name, from_report=True))
    return out


def _kg(value) -> float | None:
    if not isinstance(value, dict):
        return None
    raw, unit = value.get("value"), str(value.get("unit") or "kg").strip().lower().rstrip(".")
    try:
        number = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if unit in _G_UNITS:
        number /= 1000
    elif unit not in _KG_UNITS:
        return None
    low, high = record.RANGES[("weight", "kg")]
    return round(number, 3) if low <= number <= high else None


def _merge(noted: list[Note], reported: list[Note], now: datetime) -> list[Note]:
    """Her weights and her reports' in one curve; the same weight the same day once."""
    seen = {(_local_day(n, now), round(n.value or 0, 2)) for n in noted}
    extra = [r for r in reported if (_local_day(r, now), round(r.value or 0, 2)) not in seen]
    return sorted([*noted, *extra], key=lambda n: n.observed_at)


# --- wording ---------------------------------------------------------------------

_TITLE = {
    "es": {"feed": "Tomas", "sleep": "Sueño", "temperature": "Temperatura",
           "stool": "Deposiciones", "nappy": "Pañales mojados", "weight": "Peso",
           "medication": "Medicación", "symptom": "Síntomas", "vaccine": "Vacunas",
           "note": "Notas", ALL: "Lo anotado"},
    "en": {"feed": "Feeds", "sleep": "Sleep", "temperature": "Temperature", "stool": "Stools",
           "nappy": "Wet nappies", "weight": "Weight", "medication": "Medicines",
           "symptom": "Symptoms", "vaccine": "Vaccines", "note": "Notes", ALL: "What you noted"},
    "fr": {"feed": "Repas", "sleep": "Sommeil", "temperature": "Température", "stool": "Selles",
           "nappy": "Couches mouillées", "weight": "Poids", "medication": "Médicaments",
           "symptom": "Symptômes", "vaccine": "Vaccins", "note": "Notes",
           ALL: "Ce que tu as noté"},
}
_TODAY_WORD = {"es": "hoy", "en": "today", "fr": "aujourd’hui"}
_YESTERDAY_WORD = {"es": "ayer", "en": "yesterday", "fr": "hier"}
_COLON = {"es": ": ", "en": ": ", "fr": "\u00a0: "}
_FEEDS = {"es": ("toma", "tomas"), "en": ("feed", "feeds"), "fr": ("repas", "repas")}
_NOTHING = {"es": "nada anotado", "en": "nothing noted", "fr": "rien de noté"}
_NOTHING_ALL = {"es": "Nada anotado", "en": "Nothing noted", "fr": "Rien de noté"}
_LAST = {"es": "Lo último: ", "en": "Last noted: ", "fr": "Dernière note\u00a0: "}
_HIGHEST = {"es": "La más alta: ", "en": "Highest: ", "fr": "La plus haute\u00a0: "}
_REPORT = {"es": " (informe)", "en": " (report)", "fr": " (compte rendu)"}
_PERCENTILE = {"es": "Percentil OMS: ", "en": "WHO percentile: ", "fr": "Percentile OMS\u00a0: "}
_HINT = {
    "es": "Cuéntamelo cuando pase y lo anoto.",
    "en": "Tell me when it happens and I will note it.",
    "fr": "Dis-le-moi quand ça arrive et je le note.",
}
_MORE = {"es": "- y {k} más", "en": "- and {k} more", "fr": "- et {k} de plus"}
_QUOTES = {"es": ("«", "»"), "en": ("“", "”"), "fr": ("«\u00a0", "\u00a0»")}
#: Characters that would turn her own words into Markdown (a link, an image).
_MARKDOWN = re.compile(r"([\\`*_\[\]()#<>!|~])")
#: Kinds whose meaning is in her words, not in the number.
_TOLD_IN_WORDS = {"medication", "symptom", "vaccine", "note"}


def _lang(locale: str) -> str:
    return locale if locale in _TITLE else "es"


def _span(days: int | None, lang: str) -> str | None:
    if days is None:
        return None
    if days == 1:
        return _TODAY_WORD[lang]
    if days == 2:
        return {"es": "hoy y ayer", "en": "today and yesterday", "fr": "aujourd’hui et hier"}[lang]
    return {"es": f"últimos {days} días", "en": f"last {days} days",
            "fr": f"{days} derniers jours"}[lang]


def _nothing_span(days: int | None, lang: str) -> str:
    if days is None:
        return {"es": "todavía", "en": "yet", "fr": "pour l’instant"}[lang]
    if days == 1:
        return _TODAY_WORD[lang]
    if days == 2:
        return {"es": "hoy ni ayer", "en": "today or yesterday",
                "fr": "aujourd’hui ni hier"}[lang]
    return {"es": f"en los últimos {days} días", "en": f"in the last {days} days",
            "fr": f"ces {days} derniers jours"}[lang]


def _title(kind: str, days: int | None, lang: str) -> str:
    span = _span(days, lang)
    title = _TITLE[lang][kind]
    return f"{title}, {span}" if span else title


def _local_day(note: Note, now: datetime) -> date:
    return note.observed_at.astimezone(now.tzinfo).date()


def _short_date(day: date, now: datetime) -> str:
    return f"{day.day:02d}/{day.month:02d}" + ("" if day.year == now.year else f"/{day.year % 100:02d}")


def _day_word(day: date, now: datetime, lang: str) -> str:
    """«hoy», «ayer» or «18/11»: the day a list line opens with."""
    days = (now.date() - day).days
    if days == 0:
        return _TODAY_WORD[lang]
    if days == 1:
        return _YESTERDAY_WORD[lang]
    return _short_date(day, now)


def _on_day(day: date, now: datetime, lang: str) -> str:
    """«hoy», «ayer», «el 18/11»: a day inside a sentence."""
    word = _day_word(day, now, lang)
    if word in (_TODAY_WORD[lang], _YESTERDAY_WORD[lang]):
        return word
    return {"es": f"el {word}", "en": f"on {word}", "fr": f"le {word}"}[lang]


def _since(day: date, now: datetime, lang: str) -> str:
    word = _day_word(day, now, lang)
    if lang == "en":
        return f"Since {word}"
    return {"es": "Desde ", "fr": "Depuis "}[lang] + _on_day(day, now, lang)


def _plural_days(count: int, lang: str) -> str:
    one, many = {"es": ("día", "días"), "en": ("day", "days"), "fr": ("jour", "jours")}[lang]
    return f"{count} {one if count == 1 else many}"


def _quote(text: str, lang: str) -> str:
    plain = _MARKDOWN.sub(r"\\\1", " ".join((text or "").split()))[:160]
    left, right = _QUOTES[lang]
    return f"{left}{plain}{right}"


def _draft(note: Note) -> record.RecordDraft:
    return record.RecordDraft(note.kind, note.value, note.unit, note.observed_at, note.text)


def _value(note: Note, lang: str) -> str:
    return record._value_text(_draft(note), lang) or ""


def _when(note: Note, now: datetime, lang: str) -> str:
    return record._when_text(note.observed_at, now, lang)


def _last_line(note: Note, now: datetime, lang: str) -> str:
    value = _value(note, lang) if note.unit != "count" else ""
    return f"{_LAST[lang]}{_when(note, now, lang)}{', ' + value if value else ''}."


def _trend(title: str, unit: str, style: str, points: list[dict]) -> dict | None:
    """A chart only when there is a line to draw: one point is a number, not a trend."""
    if len(points) < 2:
        return None
    return cards.card_trend(uuid4().hex[:12], title, unit, style, points[-MAX_POINTS:])


# --- the summaries ---------------------------------------------------------------


def summarize(
    kind: str, notes: list[Note], *, days: int | None, now: datetime, locale: str,
    facts: ProfileFacts = UNKNOWN_PROFILE, earlier: Note | None = None,
) -> Reading:
    """One kind of note, in her language, from oldest-first `notes`."""
    lang = _lang(locale)
    if not notes:
        return Reading(kind, _nothing(kind, days, lang, now, earlier))
    title = _title(kind, days, lang)
    if kind in ("feed", "sleep", "stool", "nappy"):
        return _daily(kind, notes, title, now, lang)
    if kind == "temperature":
        return _temperatures(notes, title, now, lang)
    if kind == "weight":
        return _weights(notes, title, now, lang, facts)
    return _entries(kind, notes, title, now, lang)


def _nothing(kind: str, days: int | None, lang: str, now: datetime, earlier: Note | None) -> str:
    if kind == ALL:
        return f"{_NOTHING_ALL[lang]} {_nothing_span(days, lang)}."
    line = f"{_TITLE[lang][kind]}{_COLON[lang]}{_NOTHING[lang]} {_nothing_span(days, lang)}."
    if earlier is not None:
        return f"{line} {_last_line(earlier, now, lang)}"
    return f"{line} {_HINT[lang]}"


def _lines(items: list[str], lang: str) -> list[str]:
    if len(items) <= MAX_LINES:
        return items
    return [*items[:MAX_LINES], _MORE[lang].format(k=len(items) - MAX_LINES)]


def _daily(kind: str, notes: list[Note], title: str, now: datetime, lang: str) -> Reading:
    by_day: dict[date, list[Note]] = {}
    for note in notes:
        by_day.setdefault(_local_day(note, now), []).append(note)
    unit = _chart_unit(kind, notes)
    lines: list[str] = []
    points: list[dict] = []
    for day in sorted(by_day):
        text, value = _DAY_TOTAL[kind](by_day[day], lang, unit)
        lines.append(f"- {_day_word(day, now, lang)}{_COLON[lang]}{text}")
        if value:
            points.append({"label": _short_date(day, now), "value": round(value, 2), "text": text})
    lines.reverse()
    body = [f"**{title}**", *_lines(lines, lang), "", _last_line(notes[-1], now, lang)]
    return Reading(kind, "\n".join(body), _trend(title, unit if unit != "count" else "", "bars",
                                                 points))


def _chart_unit(kind: str, notes: list[Note]) -> str:
    if kind == "feed":
        return "ml" if any(n.unit == "ml" for n in notes) else "count"
    if kind == "sleep":
        return "h"
    return "count"


def _feed_day(notes: list[Note], lang: str, unit: str) -> tuple[str, float]:
    count = sum(int(n.value) if n.unit == "count" and n.value else 1 for n in notes)
    one, many = _FEEDS[lang]
    parts = [f"{count} {one if count == 1 else many}"]
    totals = {u: sum(n.value or 0 for n in notes if n.unit == u) for u in ("ml", "min", "spoon")}
    for u, total in totals.items():
        if total:
            word = record._UNIT_WORD[lang].get(u, u)
            parts.append(f"{record._number(total, lang)} {word}")
    return ", ".join(parts), (totals["ml"] if unit == "ml" else count)


def _sleep_day(notes: list[Note], lang: str, unit: str) -> tuple[str, float]:
    hours = sum(n.value or 0 for n in notes if n.unit == "h")
    hours += sum(n.value or 0 for n in notes if n.unit == "min") / 60
    awake = sum(n.value or 0 for n in notes if n.unit == "h_awake")
    parts = []
    if hours:
        parts.append(f"{record._number(round(hours, 1), lang)} h")
    if awake:
        parts.append(f"{record._number(awake, lang)} {record._UNIT_WORD[lang]['h_awake']}")
    return ", ".join(parts), round(hours, 1)


def _count_day(notes: list[Note], lang: str, unit: str) -> tuple[str, float]:
    count = sum(n.value if n.value is not None else 1 for n in notes)
    return record._number(count, lang), count


_DAY_TOTAL = {"feed": _feed_day, "sleep": _sleep_day, "stool": _count_day, "nappy": _count_day}


def _temperatures(notes: list[Note], title: str, now: datetime, lang: str) -> Reading:
    readings = [n for n in notes if n.value is not None]
    lines = [f"- {_when(n, now, lang)}, {_value(n, lang)}" for n in reversed(readings)]
    body = [f"**{title}**", *_lines(lines, lang)]
    if len(readings) > 1:
        top = max(readings, key=lambda n: (n.value, n.observed_at))
        body += ["", f"{_HIGHEST[lang]}{_value(top, lang)}, {_when(top, now, lang)}."]
    points = [{"label": f"{_short_date(_local_day(n, now), now)} "
                        f"{n.observed_at.astimezone(now.tzinfo):%H:%M}",
               "value": n.value, "text": _value(n, lang), "x": _days_after(readings[0], n)}
              for n in readings]
    return Reading("temperature", "\n".join(body), _trend(title, "°C", "line", points))


def _weights(notes: list[Note], title: str, now: datetime, lang: str,
             facts: ProfileFacts) -> Reading:
    weights = [n for n in notes if n.value is not None]
    lines = [f"- {_day_word(_local_day(n, now), now, lang)}{_COLON[lang]}{_value(n, lang)}"
             f"{_REPORT[lang] if n.from_report else ''}" for n in reversed(weights)]
    body = [f"**{title}**", *_lines(lines, lang)]
    first, last = weights[0], weights[-1]
    first_day, last_day = _local_day(first, now), _local_day(last, now)
    span = (last_day - first_day).days
    tail: list[str] = []
    if len(weights) > 1 and span >= 1:
        diff = (last.value or 0.0) - (first.value or 0.0)
        sign = "+" if diff >= 0 else "-"
        grams = round(abs(diff) * 1000 / span)
        per_day = {"es": "al día", "en": "a day", "fr": "par jour"}[lang]
        in_word = {"es": "en", "en": "in", "fr": "en"}[lang]
        tail.append(
            f"{_since(first_day, now, lang)}{_COLON[lang]}{sign}{record._number(abs(diff), lang)} kg "
            f"{in_word} {_plural_days(span, lang)} ({sign}{grams} g {per_day})."
        )
    percentiles = _percentiles([first, last] if len(weights) > 1 else [last], facts, now)
    # The latest weighing decides whether the line is said at all: a lone
    # percentile at birth next to today's weight would read as today's.
    if percentiles and percentiles[-1][1] == last_day:
        tail.append(_PERCENTILE[lang] + ", ".join(
            f"{p} {_on_day(day, now, lang)}" for p, day in percentiles) + ".")
    if tail:
        body += ["", *tail]
    points = [{"label": _short_date(_local_day(n, now), now), "value": n.value,
               "text": _value(n, lang), "x": _days_after(first, n)} for n in weights]
    return Reading("weight", "\n".join(body), _trend(title, "kg", "line", points))


def _days_after(first: Note, note: Note) -> float:
    """Where a reading sits in time, in days: a line spaces its points by the
    calendar, so two weighings a week apart are not drawn as far apart as two
    months."""
    return round((note.observed_at - first.observed_at).total_seconds() / 86400, 3)


def _percentiles(notes: list[Note], facts: ProfileFacts, now: datetime) -> list[tuple[int, date]]:
    """The WHO weight percentile at each weighing's age, where the table has it."""
    if facts.date_of_birth is None or facts.sex not in ("M", "F"):
        return []
    out: list[tuple[int, date]] = []
    for note in notes:
        day = _local_day(note, now)
        months = age_in_months(facts.date_of_birth, today=day)
        if months is None or note.value is None:
            continue
        p = growth_percentile(metric="weight", value=note.value, age_months=months, sex=facts.sex)
        if p is not None:
            out.append((p, day))
    return out


def _entries(kind: str, notes: list[Note], title: str, now: datetime, lang: str) -> Reading:
    """Medicines, symptoms, vaccines, notes, or everything: one line each, newest first.

    Her own words go with each of these: «2,5 ml» says nothing without the
    name of the medicine she wrote next to it.
    """
    lines = []
    for note in reversed(notes):
        if kind == ALL:
            line = record.summary(_draft(note), locale=lang, now=now)
            if note.value is None or note.kind in _TOLD_IN_WORDS:
                line += f", {_quote(note.text, lang)}"
        else:
            line = f"{_when(note, now, lang)}, {_quote(note.text, lang)}"
        lines.append(f"- {line}")
    return Reading(kind, "\n".join([f"**{title}**", *_lines(lines, lang)]))
