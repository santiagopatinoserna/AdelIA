# apps/api/adelia/agent/pediatrics.py
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data"

@lru_cache(maxsize=1)
def _growth() -> dict:
    return json.loads((_DATA / "who_growth.json").read_text(encoding="utf-8"))

@lru_cache(maxsize=1)
def _vaccines() -> list[dict]:
    return json.loads((_DATA / "vaccines_es.json").read_text(encoding="utf-8"))

# maps a percentile band edge to its numeric percentile
_BANDS = [("p3", 3), ("p15", 15), ("p50", 50), ("p85", 85), ("p97", 97)]

def growth_percentile(*, metric: str, value: float, age_months: int, sex: str) -> int | None:
    table = _growth().get(metric, {}).get(sex)
    if not table:
        return None
    row = next((r for r in table if r["age_months"] == age_months), None)
    if row is None:
        return None
    # piecewise-linear interpolation across the known band edges
    edges = [(row[k], p) for k, p in _BANDS]
    if value <= edges[0][0]:
        return edges[0][1]
    if value >= edges[-1][0]:
        return edges[-1][1]
    for (v_lo, p_lo), (v_hi, p_hi) in zip(edges, edges[1:]):
        if v_lo <= value <= v_hi:
            frac = (value - v_lo) / (v_hi - v_lo) if v_hi != v_lo else 0.0
            return round(p_lo + frac * (p_hi - p_lo))
    return None

def due_vaccines(*, age_months: int) -> list[dict]:
    out = []
    for v in _vaccines():
        if v["due_month"] <= age_months + 1:  # due now or within a month
            out.append({"name": v["name"], "due_month": v["due_month"],
                        "overdue": v["due_month"] < age_months})
    return out
