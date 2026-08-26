"""Every evidence_*.json must satisfy the DB constraints BEFORE boot.

The startup loader swallows exceptions (evidence must never block boot), so a
bad file fails silently in production: a CHECK violation on source_type
skipped an entire 40-source corpus on 2026-08-26 and only the logs knew.
This test makes that mistake impossible to push.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"
# Mirror of ck_evidence_sources_type (alembic 0005_evidence_chunks).
ALLOWED_SOURCE_TYPES = {"guideline", "paper", "protocol", "reference"}
FILES = sorted(DATA_DIR.glob("evidence_*.json"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_evidence_file_respects_db_constraints(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources", [])
    assert sources, f"{path.name} has no sources"
    titles = [s["title"] for s in sources]
    assert len(titles) == len(set(titles)), f"{path.name}: duplicate titles (loader is idempotent by title)"
    for s in sources:
        assert s["source_type"] in ALLOWED_SOURCE_TYPES, (
            f"{path.name}: {s['title'][:60]!r} has source_type {s['source_type']!r}; "
            f"allowed: {sorted(ALLOWED_SOURCE_TYPES)}"
        )
        assert s.get("chunks"), f"{path.name}: {s['title'][:60]!r} has no chunks"
        assert len(s["title"]) <= 500
