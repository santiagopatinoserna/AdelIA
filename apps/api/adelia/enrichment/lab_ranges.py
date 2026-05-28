"""Lab reference range lookup with optional sex/age stratification + interpretation zones.

Takes an observation name (or alias) + numeric value + optional sex/age → returns
canonical range + a clinical-meaningful status label (e.g. 'pre-diabetes', 'stage_1_hypertension').

v0.1 covers 30 most common labs/vitals. Adult ranges. Sex-specific overrides for
ferritin, creatinine, ALT, AST, hemoglobin, hematocrit.

Source: Mayo Clinic Labs + MedlinePlus + LabTestsOnline (public reference ranges).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process


_DATA_FILE = Path(__file__).parent / "data" / "lab_reference_ranges.json"


@dataclass(frozen=True)
class _RangeLookup:
    canonical_name: str
    aliases: tuple[str, ...]
    unit: str
    low: float
    high: float
    sex_specific: dict
    zones: tuple[dict, ...]


@dataclass(frozen=True)
class ReferenceRange:
    canonical_name: str
    unit: str
    low: float
    high: float
    sex: Literal["M", "F"] | None = None


@dataclass(frozen=True)
class RangeStatus:
    """Result of evaluating an observation against its reference range."""

    canonical_name: str
    value: float
    unit: str
    range: ReferenceRange
    flag: Literal["low", "normal", "high"]
    zone_label: str | None = None  # e.g. 'pre-diabetes', 'stage_1_hypertension'
    interpretation: str = ""  # human-readable summary in ES


@lru_cache(maxsize=1)
def _load_ranges() -> tuple[_RangeLookup, ...]:
    with _DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows: list[_RangeLookup] = []
    for entry in data.get("ranges", []):
        rows.append(
            _RangeLookup(
                canonical_name=entry["name"],
                aliases=tuple(a.lower() for a in (entry["name"], *entry.get("aliases", []))),
                unit=entry.get("unit", ""),
                low=float(entry.get("low", 0)),
                high=float(entry.get("high", 9999)),
                sex_specific=entry.get("sex_specific", {}),
                zones=tuple(entry.get("interpretation_zones", [])),
            )
        )
    return tuple(rows)


def _lookup(name: str) -> _RangeLookup | None:
    """Match observation name to a reference range row.

    Strategy: exact alias match first (cheap, avoids false positives like
    'hemoglobin' matching 'hemoglobin a1c'). Falls back to fuzzy
    token_sort_ratio which discriminates by length unlike token_set_ratio.
    """
    q = name.strip().lower()
    if not q:
        return None
    rows = _load_ranges()

    # Phase 1: exact alias match
    for idx, row in enumerate(rows):
        if q in row.aliases:
            return row

    # Phase 2: fuzzy fallback with token_sort_ratio (length-aware)
    all_aliases: list[tuple[str, int]] = []
    for idx, row in enumerate(rows):
        for alias in row.aliases:
            all_aliases.append((alias, idx))

    choices = [a for a, _ in all_aliases]
    best = process.extractOne(q, choices, scorer=fuzz.token_sort_ratio)
    if best is None:
        return None
    matched, score, pos = best
    if score < 80:
        return None
    _, row_idx = all_aliases[pos]
    return rows[row_idx]


def get_reference_range(name: str, *, sex: Literal["M", "F"] | None = None) -> ReferenceRange | None:
    """Return the canonical reference range for an observation (sex-aware where applicable)."""
    row = _lookup(name)
    if row is None:
        return None
    low, high = row.low, row.high
    if sex and sex in row.sex_specific:
        low = float(row.sex_specific[sex]["low"])
        high = float(row.sex_specific[sex]["high"])
    return ReferenceRange(
        canonical_name=row.canonical_name,
        unit=row.unit,
        low=low,
        high=high,
        sex=sex,
    )


def evaluate(
    name: str,
    value: float | str,
    *,
    sex: Literal["M", "F"] | None = None,
) -> RangeStatus | None:
    """Evaluate an observation value against reference range + interpretation zones.

    Returns None if observation name not recognized.
    """
    row = _lookup(name)
    if row is None:
        return None

    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    low, high = row.low, row.high
    if sex and sex in row.sex_specific:
        low = float(row.sex_specific[sex]["low"])
        high = float(row.sex_specific[sex]["high"])

    ref_range = ReferenceRange(
        canonical_name=row.canonical_name,
        unit=row.unit,
        low=low,
        high=high,
        sex=sex,
    )

    # Find interpretation zone (first zone where value <= max)
    zone_label: str | None = None
    for zone in row.zones:
        if v <= float(zone.get("max", 9999)):
            zone_label = zone.get("label")
            break

    # High-level flag
    if v < low:
        flag = "low"
    elif v > high:
        flag = "high"
    else:
        flag = "normal"

    # Build interpretation summary
    interpretation_parts = [f"{row.canonical_name} = {v} {row.unit}"]
    interpretation_parts.append(f"(referencia {low}-{high} {row.unit})")
    if zone_label:
        interpretation_parts.append(f"[{zone_label}]")
    elif flag != "normal":
        interpretation_parts.append(f"[{flag}]")
    interpretation = " ".join(interpretation_parts)

    return RangeStatus(
        canonical_name=row.canonical_name,
        value=v,
        unit=row.unit,
        range=ref_range,
        flag=flag,
        zone_label=zone_label,
        interpretation=interpretation,
    )


def coverage_count() -> int:
    return len(_load_ranges())
