"""ICD-10 + SNOMED CT normalization service.

Takes a free-text entity name and returns canonical {icd10, snomed} codes plus
the canonical English name. Multi-lingual aliases (ES, EN, FR) supported via
rapidfuzz token-set ratio fuzzy match.

v0.1 coverage: 50+ conditions/allergies/procedures/immunizations. Curated subset
of WHO ICD-10 (public) + SNOMED CT widely-known concepts. Expand via JSON edits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process


_DATA_FILE = Path(__file__).parent / "data" / "code_normalization.json"


@dataclass(frozen=True)
class NormalizedCode:
    canonical_name: str
    icd10: str
    snomed: str
    category: str  # 'conditions' | 'allergies' | 'procedures' | 'immunizations'
    match_score: int  # 0-100, rapidfuzz ratio


@dataclass(frozen=True)
class _Lookup:
    canonical_name: str
    icd10: str
    snomed: str
    category: str
    search_aliases: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_lookup() -> tuple[_Lookup, ...]:
    """Load the normalization JSON once and flatten into a fast lookup table."""
    with _DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows: list[_Lookup] = []
    for category in ("conditions", "allergies", "procedures", "immunizations"):
        for entry in data.get(category, []):
            aliases = (entry["name"], *entry.get("aliases", []))
            rows.append(
                _Lookup(
                    canonical_name=entry["name"],
                    icd10=entry["icd10"],
                    snomed=entry["snomed"],
                    category=category,
                    search_aliases=tuple(a.lower() for a in aliases),
                )
            )
    return tuple(rows)


def normalize(query: str, *, min_score: int = 80) -> NormalizedCode | None:
    """Best-effort lookup. Returns None if no alias scores ≥ min_score."""
    if not query or not query.strip():
        return None

    q = query.strip().lower()
    lookup = _load_lookup()

    # Build flat (alias, row_index) list for rapidfuzz
    all_aliases: list[tuple[str, int]] = []
    for idx, row in enumerate(lookup):
        for alias in row.search_aliases:
            all_aliases.append((alias, idx))

    choices = [a for a, _ in all_aliases]
    best = process.extractOne(q, choices, scorer=fuzz.token_set_ratio)
    if best is None:
        return None
    matched_alias, score, position = best
    if score < min_score:
        return None
    _, row_idx = all_aliases[position]
    row = lookup[row_idx]
    return NormalizedCode(
        canonical_name=row.canonical_name,
        icd10=row.icd10,
        snomed=row.snomed,
        category=row.category,
        match_score=int(score),
    )


def normalize_many(
    queries: list[str], *, min_score: int = 80
) -> dict[str, NormalizedCode | None]:
    """Bulk normalization. Returns dict mapping each query to its NormalizedCode or None."""
    return {q: normalize(q, min_score=min_score) for q in queries}


def coverage_stats() -> dict[str, int]:
    """How many entries per category. Useful for /health endpoint."""
    lookup = _load_lookup()
    stats: dict[str, int] = {}
    for row in lookup:
        stats[row.category] = stats.get(row.category, 0) + 1
    stats["total"] = len(lookup)
    return stats
