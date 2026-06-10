"""Drug-drug interaction checker.

Offline curated dataset (30+ widely-known interactions) with severity grading:
contraindicated > major > moderate > minor. Alias resolution for ES/EN brand/
generic names. Service: check_interactions(med_names) → list of interactions
between every pair, sorted by severity.

Future v0.2.1: NLM RxNav API integration for live lookup when network available.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Literal


_DATA_FILE = Path(__file__).parent / "data" / "drug_interactions.json"

Severity = Literal["contraindicated", "major", "moderate", "minor"]
_SEVERITY_RANK = {"contraindicated": 0, "major": 1, "moderate": 2, "minor": 3}


@dataclass(frozen=True)
class DrugInteraction:
    drug_a: str  # canonical name
    drug_b: str  # canonical name
    severity: Severity
    mechanism: str
    recommendation: str


@dataclass(frozen=True)
class _Dataset:
    aliases: dict[str, str]  # alias.lower() → canonical
    interactions: tuple[DrugInteraction, ...]


@lru_cache(maxsize=1)
def _load_dataset() -> _Dataset:
    with _DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Build alias → canonical map
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in data.get("drug_aliases", {}).items():
        for alias in aliases:
            alias_to_canonical[alias.lower()] = canonical

    interactions: list[DrugInteraction] = []
    for entry in data.get("interactions", []):
        drugs = entry["drugs"]
        if len(drugs) != 2:
            continue
        a, b = sorted(drugs)  # canonical pair (sorted for dedupe stability)
        interactions.append(
            DrugInteraction(
                drug_a=a,
                drug_b=b,
                severity=entry["severity"],
                mechanism=entry["mechanism"],
                recommendation=entry["recommendation"],
            )
        )

    return _Dataset(aliases=alias_to_canonical, interactions=tuple(interactions))


def resolve_canonical(name: str) -> str | None:
    """Return canonical drug name for an alias, or None if unknown.

    Strips dosage info (e.g. 'warfarin 5mg' → 'warfarin') and tries exact match.
    """
    if not name:
        return None
    cleaned = name.strip().lower()
    # Strip trailing dosage/unit tokens
    for token in cleaned.split():
        if any(d.isdigit() for d in token):
            cleaned = cleaned.split(token, 1)[0].strip()
            break
    ds = _load_dataset()
    if cleaned in ds.aliases:
        return ds.aliases[cleaned]
    # Try first token (single-word brand)
    first_word = cleaned.split()[0] if cleaned else ""
    if first_word in ds.aliases:
        return ds.aliases[first_word]
    return None


def check_pair(drug_a: str, drug_b: str) -> DrugInteraction | None:
    """Check a specific pair (order independent). Returns interaction or None."""
    a = resolve_canonical(drug_a)
    b = resolve_canonical(drug_b)
    if a is None or b is None or a == b:
        return None
    pair = tuple(sorted([a, b]))
    for inter in _load_dataset().interactions:
        if (inter.drug_a, inter.drug_b) == pair:
            return inter
    return None


def check_interactions(med_names: list[str]) -> list[DrugInteraction]:
    """Check all pairwise interactions among a list of meds.

    Returns sorted by severity (contraindicated first), deduplicated by pair.
    Unknown drug names silently skipped.
    """
    canonicals: list[str] = []
    seen = set()
    for name in med_names:
        c = resolve_canonical(name)
        if c is not None and c not in seen:
            canonicals.append(c)
            seen.add(c)

    found: list[DrugInteraction] = []
    for a, b in combinations(canonicals, 2):
        inter = check_pair(a, b)
        if inter is not None:
            found.append(inter)

    found.sort(key=lambda i: _SEVERITY_RANK.get(i.severity, 99))
    return found


def coverage_stats() -> dict:
    """Info for /health or admin debug."""
    ds = _load_dataset()
    by_severity: dict[str, int] = {}
    for i in ds.interactions:
        by_severity[i.severity] = by_severity.get(i.severity, 0) + 1
    return {
        "drugs_known": len({i.drug_a for i in ds.interactions} | {i.drug_b for i in ds.interactions}),
        "aliases_total": len(ds.aliases),
        "interactions_total": len(ds.interactions),
        "by_severity": by_severity,
    }
