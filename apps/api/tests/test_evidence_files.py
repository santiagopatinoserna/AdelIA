"""Every evidence_*.json must satisfy the DB constraints BEFORE boot.

The startup loader swallows exceptions (evidence must never block boot), so a
bad file fails silently in production: a CHECK violation on source_type
skipped an entire 40-source corpus on 2026-08-26 and only the logs knew.
This test makes that mistake impossible to push.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from adelia.enrichment.evidence_hygiene import (
    CANONICAL_ORGANIZATIONS,
    canonical_organization,
    looks_like_url,
)

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
        # Column widths in models.EvidenceSource: a longer value makes the
        # whole file fail to load at boot (StringDataRightTruncationError).
        for field, limit in (("organization", 128), ("url", 1024), ("license", 64), ("language", 8)):
            value = s.get(field) or ""
            assert len(value) <= limit, f"{path.name}: {s['title'][:60]!r} {field} longer than {limit}"


# A chunk is read by a mother in Spain or France. "Call 111" (NHS advice line),
# "999" or "911" are numbers that do not exist there, and a model composing an
# answer passes them on. The source's urgency level is written in words
# instead ("llamar a emergencias", "consulta urgente el mismo día"). Found on
# 2026-11-03 in four of the domain files before they reached main.
FOREIGN_EMERGENCY_NUMBER = re.compile(r"\b(?:111|999|911)\b")


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_no_chunk_sends_a_parent_to_a_foreign_emergency_number(path: Path):
    for s in json.loads(path.read_text(encoding="utf-8"))["sources"]:
        for i, chunk in enumerate(s["chunks"]):
            hit = FOREIGN_EMERGENCY_NUMBER.search(chunk)
            assert not hit, f"{path.name}: {s['title'][:60]!r} #{i} says {hit.group(0)}"


# ---------------------------------------------------------------------------
# The urgent-care corpus (audit 3.4)
#
# The audit's finding was blunt: the corpus did not have a single line about
# urgencies, fever under 3 months or anaphylaxis, while the answering path
# always returned something. This file is what the red-flag detector cites,
# so its shape is part of the safety guarantee, not a nicety.
# ---------------------------------------------------------------------------

URGENCIAS = DATA_DIR / "evidence_urgencias_lactante.json"

# The eight topics the audit named, plus jaundice, each keyed by a word that
# must appear in the title of the source covering it.
REQUIRED_TOPICS = {
    "fiebre en menores de 3 meses": "NG143",
    "deshidratación": "CG84",
    "dificultad respiratoria": "NG9",
    "exantema que no blanquea": "NG240",
    "convulsión febril": "Convulsiones febriles",
    "anafilaxia": "Anafilaxia",
    "sueño seguro": "sueño",
    "atragantamiento": "European Resuscitation Council",
    "ictericia": "Ictericia",
}


def test_the_urgent_care_corpus_exists():
    assert URGENCIAS.exists(), "the red-flag detector cites sources from this file"


@pytest.mark.parametrize("topic,needle", sorted(REQUIRED_TOPICS.items()))
def test_every_urgent_topic_has_a_source_with_at_least_three_chunks(topic, needle):
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    matching = [s for s in data["sources"] if needle in s["title"]]
    assert matching, f"no source covers {topic!r}"
    for source in matching:
        assert len(source["chunks"]) >= 3, f"{topic}: {len(source['chunks'])} chunk(s)"


def test_urgent_care_chunks_are_sized_and_attributed():
    """Every chunk opens with the title and the authors, and stays inside the
    300-900 character window the other corpora use, so retrieval sees one
    idea per fragment and a citation is readable on its own."""
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    for source in data["sources"]:
        head = source["title"].split(" (")[0].split(":")[0][:24]
        for i, chunk in enumerate(source["chunks"]):
            assert 300 <= len(chunk) <= 900, f"{source['title'][:40]} #{i}: {len(chunk)} chars"
            assert "Tema:" in chunk and "Hallazgo:" in chunk, f"{source['title'][:40]} #{i}"
            assert head.split(",")[0][:18] in chunk, f"{source['title'][:40]} #{i} lacks its title"
            assert "—" not in chunk, "no em dashes in user-facing text"


def test_urgent_care_sources_are_pediatric_and_carry_a_url():
    """The answering path filters on the `pediatrics` tag, so an urgent-care
    source without it is a source retrieval will never return."""
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    for source in data["sources"]:
        assert "pediatrics" in source["specialties"], source["title"][:50]
        assert source["url"].startswith("https://"), source["title"][:50]
        assert source["publication_year"] >= 2009
        assert source["language"] == "es"


# ---------------------------------------------------------------------------
# The development corpus (0-24 months), 2026-10-27
#
# Measured in production: the common "at what age" questions (crawling,
# sitting, hours of sleep, first tooth, solids, weight, vaccines) found no
# fragment under the distance cut. This file answers them with public pages
# of the AEP, AEPap, WHO, CDC, the Spanish and French health ministries,
# ameli, mpedia, the AAP and UNICEF. It is family guidance about normal
# development: a fragment that names a drug or a dose does not belong here,
# because the golden set's "dose" near-misses (B6, B9, B11, B14) must keep
# finding nothing.
# ---------------------------------------------------------------------------

DESARROLLO = DATA_DIR / "evidence_desarrollo_0_24m.json"

# One source title per gap question the file was written to close.
DESARROLLO_TOPICS = {
    "gateo": "gateo",
    "sentarse": "sentarse",
    "horas de sueño": "sueno_horas",
    "dentición": "denticion",
    "inicio de sólidos": "cuando_solidos",
    "peso por edad": "peso_por_edad",
    "biberón nocturno": "biberon_retirada",
    "lenguaje a los 12 meses": "lenguaje_12m",
    "andar": "andar",
    "vacunas en España": "vacunas_espana",
    "vacunas en Francia": "vacunas_francia",
}

# Words that would make a fragment read as medication guidance. "dosis" is
# allowed only in the vaccine calendars, where it counts injections.
DESARROLLO_FORBIDDEN = ("paracetamol", "ibuprofeno", "mg/kg", "cetirizina", "melatonina",
                        "simeticona", "flúor", "cólico", "estreñimiento", "almohada")


def test_the_development_corpus_exists_and_is_sized():
    data = json.loads(DESARROLLO.read_text(encoding="utf-8"))
    assert 25 <= len(data["sources"]) <= 40, len(data["sources"])
    assert "paráfrasis" in data["_meta"]["caveat"]


@pytest.mark.parametrize("gap,topic", sorted(DESARROLLO_TOPICS.items()))
def test_every_gap_question_has_a_tagged_source(gap, topic):
    data = json.loads(DESARROLLO.read_text(encoding="utf-8"))
    tagged = [s for s in data["sources"] if topic in s.get("topics", [])]
    assert len(tagged) >= 2, f"{gap!r}: {len(tagged)} source(s) tagged {topic!r}"


def test_development_chunks_are_sized_attributed_and_drug_free():
    data = json.loads(DESARROLLO.read_text(encoding="utf-8"))
    for source in data["sources"]:
        assert 2 <= len(source["chunks"]) <= 4, source["title"][:50]
        assert source.get("topics"), source["title"][:50]
        assert "pediatrics" in source["specialties"], source["title"][:50]
        assert source["url"].startswith("https://"), source["title"][:50]
        assert source["language"] == "es"
        vaccine = {"vacunas_espana", "vacunas_francia"} & set(source["topics"])
        for i, chunk in enumerate(source["chunks"]):
            label = f"{source['title'][:40]} #{i}"
            assert 300 <= len(chunk) <= 900, f"{label}: {len(chunk)} chars"
            assert "Tema:" in chunk and "Hallazgo:" in chunk, label
            assert "—" not in chunk, f"{label}: no em dashes in user-facing text"
            low = chunk.lower()
            for word in DESARROLLO_FORBIDDEN:
                assert word not in low, f"{label} mentions {word!r}"
            if not vaccine:
                assert "dosis" not in low, f"{label} mentions a dose outside a vaccine calendar"


# ---------------------------------------------------------------------------
# Display metadata (audit 1.1 follow-up, 2026-10-14)
#
# Production held a source whose organization was "https://www" (a cut-off
# piece of its own URL, which the citation card prints as the publisher), two
# sources with no year, and NICE under three spellings. The loader skips a
# title it already has, so none of that is visible in a test of the database
# constraints above: it is only wrong on the screen of the mother reading the
# citation. These tests read the same files and fail for that class of defect.
# ---------------------------------------------------------------------------

WEB_LANDING = Path(__file__).resolve().parents[3] / "apps" / "web" / "app" / "[locale]" / "page.tsx"


def _label(path: Path, source: dict) -> str:
    return f"{path.name}: {source['title'][:60]!r}"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_source_has_a_publisher_that_is_not_a_url(path: Path):
    for s in json.loads(path.read_text(encoding="utf-8"))["sources"]:
        org = s.get("organization")
        assert isinstance(org, str) and org.strip(), f"{_label(path, s)} has no organization"
        assert not looks_like_url(org), f"{_label(path, s)} organization looks like a URL: {org!r}"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_organization_is_spelled_the_canonical_way(path: Path):
    """One string per institution, or "how many organizations" has no answer
    and the same body shows up under four names on the cards."""
    for s in json.loads(path.read_text(encoding="utf-8"))["sources"]:
        org = s["organization"]
        assert canonical_organization(org) == org, (
            f"{_label(path, s)} organization {org!r} should be "
            f"{canonical_organization(org)!r} (adelia/enrichment/evidence_hygiene.py)"
        )


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_source_has_a_year_or_says_why_it_has_none(path: Path):
    """A year is either a plausible integer or null with an `undated_reason`.
    The reason is for the next person who edits the file: a null that nobody
    explained is indistinguishable from one that nobody filled in, which is
    how two sources reached production without one."""
    this_year = date.today().year
    for s in json.loads(path.read_text(encoding="utf-8"))["sources"]:
        year = s.get("publication_year")
        if year is None:
            reason = s.get("undated_reason")
            assert isinstance(reason, str) and reason.strip(), (
                f"{_label(path, s)} has no publication_year and no undated_reason"
            )
        else:
            assert isinstance(year, int) and not isinstance(year, bool), _label(path, s)
            assert 1900 <= year <= this_year + 1, f"{_label(path, s)} year {year}"


def test_the_canonical_table_has_no_ambiguous_alias():
    seen: dict[str, str] = {}
    for canonical, aliases in CANONICAL_ORGANIZATIONS.items():
        assert canonical not in aliases
        for alias in aliases:
            assert alias not in CANONICAL_ORGANIZATIONS, f"{alias!r} is an alias and a canonical name"
            assert alias not in seen, f"{alias!r} maps to {seen[alias]!r} and {canonical!r}"
            seen[alias] = canonical
            assert len(canonical) <= 128


# What the landing says it is built on. Each name is printed on the page
# (apps/web/app/[locale]/page.tsx) and must correspond to an organization that
# really stands behind at least one source in the files, so the page cannot
# name an institution the corpus does not hold. "WHO" is the English label of
# the same institution the Spanish and French pages print as "OMS".
LANDING_INSTITUTIONS = {
    "NICE": "National Institute for Health and Care Excellence (NICE)",
    "American Academy of Pediatrics": "American Academy of Pediatrics",
    "OMS": "World Health Organization (WHO)",
    "WHO": "World Health Organization (WHO)",
    "Asociación Española de Pediatría": "Asociación Española de Pediatría",
    "AEPap": "Asociación Española de Pediatría de Atención Primaria (AEPap)",
    "NASPGHAN-ESPGHAN": "NASPGHAN-ESPGHAN",
    "Santé publique France": "Santé publique France",
}


def test_the_institutions_the_landing_names_are_in_the_corpus():
    organizations = {
        s["organization"]
        for path in FILES
        for s in json.loads(path.read_text(encoding="utf-8"))["sources"]
    }
    page = WEB_LANDING.read_text(encoding="utf-8")
    for label, canonical in LANDING_INSTITUTIONS.items():
        assert canonical in organizations, f"the corpus holds nothing from {canonical!r}"
        assert f'"{label}"' in page, f"{label!r} is no longer named on the landing"
