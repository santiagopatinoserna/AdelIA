"""The digestive and skin corpus (0-24 months).

The coverage audit found nothing on infant colic, constipation, cradle cap or
birthmarks, one source on jaundice and a handful on cow's milk protein allergy
and atopic dermatitis. This file closes those gaps from parent-facing pages of
paediatric bodies, paraphrased in Spanish. Its shape is pinned here because
the startup loader swallows errors: a malformed file would simply not load.

Nothing in it may tell a parent how much of a medicine to give: the same
detector the red-flag reply is held to (`golden.contains_dosage`) runs on
every chunk, plus a list of drug names the sources mention and the file must
not repeat.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from adelia.clinical.golden import contains_dosage
from adelia.enrichment import evidence_loader
from adelia.enrichment.evidence_hygiene import canonical_organization

PATH = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data" / "evidence_digestivo_piel.json"

# Every sub-topic the task names, by the tag the sources carry in `topics`.
SUBTOPICS = (
    "colico",
    "llanto",
    "estrenimiento",
    "heces",
    "diarrea",
    "deshidratacion",
    "vomitos",
    "aplv",
    "dermatitis_atopica",
    "costra_lactea",
    "dermatitis_panal",
    "ictericia",
    "hemangioma",
    "manchas_nacimiento",
    "proteccion_solar",
    "picaduras",
)

# Medicines, remedies and products the source pages name and this corpus must
# not pass on to a parent (doses, brand creams, probiotics, herbal teas).
FORBIDDEN = re.compile(
    r"paracetamol|ibuprofeno|simeticona|propranolol|timolol|corticoide|hidrocortisona|"
    r"antihistam|antibi[oó]tico|antif[uú]ngico|laxante|polietilenglicol|probi[oó]tico|"
    r"lactobacillus|loperamida|zinc|hom[eo]opat|manzanilla|hinojo|\bdosis\b|mg/kg|ml/kg|®",
    re.IGNORECASE,
)
# Allowed only as a warning against them, in the sentence that warns.
WARNED_AGAINST = re.compile(r"hom[eo]opat|antibi[oó]tico|probi[oó]tico", re.IGNORECASE)
SPANISH_HINT = re.compile(r"\b(el|la|los|las|de|que|y|en|con|para|bebé|si)\b", re.IGNORECASE)


def _data() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def _chunks():
    for source in _data()["sources"]:
        for i, chunk in enumerate(source["chunks"]):
            yield source, i, chunk


def test_the_file_exists_and_has_meta():
    data = _data()
    meta = data["_meta"]
    for key in ("topic", "compiled", "method", "caveat", "purpose"):
        assert meta.get(key), key


def test_between_30_and_40_sources():
    assert 30 <= len(_data()["sources"]) <= 40


def test_sources_have_the_shape_the_loader_and_cards_need():
    titles = set()
    for s in _data()["sources"]:
        assert s["title"] not in titles, s["title"]
        titles.add(s["title"])
        assert s["source_type"] in {"guideline", "paper", "protocol", "reference"}
        assert s["url"].startswith("https://"), s["title"]
        assert "pediatrics" in s["specialties"], s["title"]
        assert s["specialties"][0] == "pediatrics"
        assert s["license"] == "fair_use_snippet"
        assert s["language"] == "es"
        assert s["topics"] and all(t in SUBTOPICS for t in s["topics"]), s["title"]
        assert canonical_organization(s["organization"]) == s["organization"]
        if s["publication_year"] is None:
            assert s.get("undated_reason", "").strip(), s["title"]


def test_no_two_sources_share_a_url():
    urls = Counter(s["url"] for s in _data()["sources"])
    assert [u for u, n in urls.items() if n > 1] == []


def test_titles_do_not_collide_with_other_corpus_files():
    """The loader is idempotent by title across files: a clash would be
    silently skipped at boot."""
    mine = {s["title"] for s in _data()["sources"]}
    for other in PATH.parent.glob("evidence_*.json"):
        if other == PATH:
            continue
        theirs = {s["title"] for s in json.loads(other.read_text(encoding="utf-8"))["sources"]}
        assert not mine & theirs, f"{other.name}: {sorted(mine & theirs)}"


@pytest.mark.parametrize("topic", SUBTOPICS)
def test_every_subtopic_has_at_least_two_sources(topic):
    n = sum(topic in s["topics"] for s in _data()["sources"])
    assert n >= 2, f"{topic}: {n} source(s)"


def test_chunks_are_sized_attributed_and_spanish():
    for source, i, chunk in _chunks():
        label = f"{source['title'][:50]} #{i}"
        assert 300 <= len(chunk) <= 900, f"{label}: {len(chunk)} chars"
        assert "Tema:" in chunk and "Hallazgo:" in chunk, label
        head = source["title"].split(" (")[0].split(":")[0].split(",")[0][:18]
        assert head in chunk, f"{label} lacks its title"
        assert "—" not in chunk, f"{label}: em dash"
        assert len(SPANISH_HINT.findall(chunk)) >= 10, f"{label} does not read as Spanish"


def test_no_chunk_carries_a_dose():
    for source, i, chunk in _chunks():
        assert not contains_dosage(chunk), f"{source['title'][:50]} #{i}"


def test_no_chunk_names_a_medicine_or_remedy_except_to_warn():
    for source, i, chunk in _chunks():
        for sentence in re.split(r"(?<=[.;:])\s+", chunk):
            hit = FORBIDDEN.search(sentence)
            if not hit:
                continue
            warns = WARNED_AGAINST.search(hit.group(0)) and re.search(
                r"\bno\b|sin indicación|ni eficacia|no se recomiendan|no han demostrado", sentence
            )
            assert warns, f"{source['title'][:50]} #{i}: {hit.group(0)!r} in {sentence!r}"


def test_ages_stay_inside_the_first_two_years_or_are_the_natural_course():
    """The corpus is for 0-24 months; the only ages past it are where a mark
    or an allergy is expected to fade, or a prevalence quoted for an age band
    that includes the baby ("menores de 4 años"), as the source states them."""
    allowed_context = re.compile(
        r"desaparec|se reducen|tolerar|superan|aclararse|edad escolar|menores de \d+ años", re.I
    )
    for source, i, chunk in _chunks():
        for m in re.finditer(r"(\d+)(?:\s*(?:-|a|y)\s*(\d+))?\s*años", chunk):
            top = int(m.group(2) or m.group(1))
            if top <= 3:
                continue
            window = chunk[max(0, m.start() - 160): m.end() + 40]
            assert allowed_context.search(window), f"{source['title'][:50]} #{i}: {m.group(0)!r}"


def test_the_loader_reads_it(monkeypatch):
    """Same entry point as boot, with the database and the embedder stubbed:
    every source and every chunk reach load_sources unchanged."""
    seen: dict = {}

    async def fake_sync(path, data=None):
        return 0

    async def fake_load(sources, origin, *, tier="evidence"):
        seen["sources"], seen["origin"], seen["tier"] = sources, origin, tier
        return len(sources), sum(len(s["chunks"]) for s in sources)

    monkeypatch.setattr(evidence_loader, "sync_source_metadata", fake_sync)
    monkeypatch.setattr(evidence_loader, "load_sources", fake_load)
    added, chunks = asyncio.run(evidence_loader.load_evidence_file(PATH))
    data = _data()
    assert added == len(data["sources"])
    assert chunks == sum(len(s["chunks"]) for s in data["sources"])
    assert seen["origin"] == PATH.name and seen["tier"] == "evidence"
