"""The "what other mothers say" fixture (Kenza, 2026-10-22).

A mother wants a plan and to feel accompanied, and much of daily life with a
baby (the mess of weaning, the bath a toddler suddenly fears) is not
researched. Santiago's decision: that layer comes from PUBLIC sources cited by
URL, is always labelled as experience, and never carries doses, warning signs
or anything that contradicts a guideline. These tests hold the file to that
shape before the loader ever sees it, because the startup loader swallows
exceptions and a bad file would fail silently.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

EXPERIENCE_DIR = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "experience"
FILES = sorted(EXPERIENCE_DIR.glob("*.json"))
ES_FILE = EXPERIENCE_DIR / "experiences_es.json"

#: Everyday, non-medical routines. Anything else belongs in the evidence corpus
#: or nowhere.
ALLOWED_TOPICS = {
    "sleep", "crying", "colic", "teething", "weaning", "bath", "carrying", "going_out",
}

#: Words that mean the entry crossed into medicine. An experience entry that
#: needs any of them is not an experience entry.
FORBIDDEN = re.compile(
    r"\b(mg|ml|dosis|paracetamol|ibuprofeno|apiretal|dalsy|antibi[oó]tico|medicamento|"
    r"f[aá]rmaco|probi[oó]tico|suplemento|vitamina|miel|homeop[aá]t\w*|diagn[oó]stico|"
    r"urgencias|fiebre|convulsi[oó]n|deshidrataci[oó]n)\b",
    re.IGNORECASE,
)

REQUIRED = {"id", "title", "author", "url", "year", "topics", "summary", "language"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_spanish_experience_file_exists():
    assert ES_FILE.exists(), "adelia/enrichment/experience/experiences_es.json"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_the_file_declares_itself_as_experience_not_evidence(path: Path):
    meta = _load(path)["_meta"]
    assert meta["tier"] == "experience"
    caveat = meta["caveat"].lower()
    assert "no" in caveat and "evidencia" in caveat, "the caveat must say this is not medical evidence"
    assert "madres" in caveat or "padres" in caveat


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_between_twelve_and_twenty_reviewed_entries(path: Path):
    entries = _load(path)["entries"]
    assert 12 <= len(entries) <= 20, len(entries)


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_entry_is_complete_cited_and_unique(path: Path):
    entries = _load(path)["entries"]
    ids = [e["id"] for e in entries]
    urls = [e["url"] for e in entries]
    titles = [e["title"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate ids"
    assert len(urls) == len(set(urls)), "duplicate urls"
    assert len(titles) == len(set(titles)), "duplicate titles (loader is idempotent by title)"
    this_year = date.today().year
    for e in entries:
        label = f"{path.name}: {e.get('id')}"
        assert REQUIRED <= set(e), f"{label} missing {REQUIRED - set(e)}"
        assert re.fullmatch(r"[a-z0-9_]+", e["id"]), label
        assert e["url"].startswith("https://") or e["url"].startswith("http://"), label
        assert isinstance(e["author"], str) and e["author"].strip(), label
        assert e["language"] == "es", label
        assert e["topics"] and set(e["topics"]) <= ALLOWED_TOPICS, f"{label}: {e['topics']}"
        if e["year"] is None:
            assert e.get("undated_reason", "").strip(), f"{label} has no year and no undated_reason"
        else:
            assert isinstance(e["year"], int) and 2005 <= e["year"] <= this_year + 1, label
        # Column widths of models.EvidenceSource, which this file is loaded into.
        assert len(e["title"]) <= 500, label
        assert len(e["author"]) <= 128, label
        assert len(e["url"]) <= 1024, label


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_summary_is_a_short_paraphrase_without_medicine(path: Path):
    """Two or three sentences of our own words in Spanish. No quotation longer
    than a few words (the sources are not ours), no em dashes (house rule),
    and none of the vocabulary that would make it clinical advice."""
    for e in _load(path)["entries"]:
        label = f"{path.name}: {e['id']}"
        summary = e["summary"].strip()
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s]
        assert 2 <= len(sentences) <= 4, f"{label}: {len(sentences)} sentences"
        assert 120 <= len(summary) <= 700, f"{label}: {len(summary)} chars"
        assert "—" not in summary and "—" not in e["title"], f"{label}: em dash"
        for quoted in re.findall(r"[«\"“]([^»\"”]+)[»\"”]", summary):
            assert len(quoted.split()) <= 5, f"{label}: quotation too long: {quoted!r}"
        hit = FORBIDDEN.search(summary)
        assert hit is None, f"{label}: {hit.group(0)!r} is not experience, it is medicine"


def test_the_topics_cover_everyday_life_broadly():
    covered = {t for e in _load(ES_FILE)["entries"] for t in e["topics"]}
    assert {"sleep", "crying", "bath", "carrying", "weaning", "going_out"} <= covered
