from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class TemporalIntent:
    entity_name: str          # lowercase, e.g. "glucosa", "colesterol"
    from_date: date | None
    to_date: date | None


# Keywords that signal a temporal/series query.
_TEMPORAL_KEYWORDS = (
    "curva",
    "tendencia",
    "evolución",
    "evolucion",
    "histórico",
    "historico",
    "serie",
)

# Entity-name capture: anything after the temporal keyword + "de" until a
# date-window keyword or punctuation. Lowercase comparison.
_ENTITY_PATTERN = re.compile(
    r"(?:curva|tendencia|evolución|evolucion|histórico|historico|serie)"
    r"\s+(?:del\s+|de\s+(?:mi\s+|mis\s+)?)?"
    r"([a-záéíóúñ ]+?)"
    r"(?=\s+(?:de\s+los\s+últimos|los\s+últimos|en\s+los\s+últimos|desde|últim[oa]s|en\s+los)|\s*\?|$)",
    re.IGNORECASE,
)

_RELATIVE_YEARS_PATTERN = re.compile(
    r"últim[oa]s\s+(\d+)\s+años", re.IGNORECASE
)
_RELATIVE_MONTHS_PATTERN = re.compile(
    r"últim[oa]s\s+(\d+)\s+meses", re.IGNORECASE
)
_EXPLICIT_RANGE_PATTERN = re.compile(
    r"desde\s+(\d{4})\s+hasta\s+(\d{4})", re.IGNORECASE
)


def detect_temporal_intent(question: str) -> TemporalIntent | None:
    """Heuristic detector for time-series queries over the entities table.

    Returns a TemporalIntent if the question matches a temporal pattern
    (curva|tendencia|evolución|histórico|serie de <entity>), with an
    inferred date range. Returns None otherwise — caller falls back to
    standard RAG retrieval.
    """
    q_lower = question.lower()

    # Quick keyword bail-out: skip regex if no temporal keyword present.
    if not any(kw in q_lower for kw in _TEMPORAL_KEYWORDS):
        return None

    entity_match = _ENTITY_PATTERN.search(question)
    if not entity_match:
        return None
    entity_name = entity_match.group(1).strip().lower()
    # Trim leading "del" / "de" that may sneak in (contraction edge case)
    entity_name = re.sub(r"^del?\s+", "", entity_name).strip()
    # Trim trailing "mi" / "mis" / "de" that may sneak in
    entity_name = re.sub(r"\s+(de|mi|mis)$", "", entity_name).strip()
    if not entity_name:
        return None

    from_date: date | None = None
    to_date: date | None = None

    explicit = _EXPLICIT_RANGE_PATTERN.search(q_lower)
    if explicit:
        from_year, to_year = int(explicit.group(1)), int(explicit.group(2))
        from_date = date(from_year, 1, 1)
        to_date = date(to_year, 12, 31)
        return TemporalIntent(entity_name=entity_name, from_date=from_date, to_date=to_date)

    years_match = _RELATIVE_YEARS_PATTERN.search(q_lower)
    if years_match:
        n = int(years_match.group(1))
        to_date = date.today()
        from_date = to_date - timedelta(days=n * 365)
        return TemporalIntent(entity_name=entity_name, from_date=from_date, to_date=to_date)

    months_match = _RELATIVE_MONTHS_PATTERN.search(q_lower)
    if months_match:
        n = int(months_match.group(1))
        to_date = date.today()
        from_date = to_date - timedelta(days=n * 30)
        return TemporalIntent(entity_name=entity_name, from_date=from_date, to_date=to_date)

    # Temporal keyword present but no explicit range — entity-only intent
    return TemporalIntent(entity_name=entity_name, from_date=None, to_date=None)
