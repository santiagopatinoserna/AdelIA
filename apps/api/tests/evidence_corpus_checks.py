"""Checks every per-domain corpus file (`evidence_<ambito>.json`) must pass.

The corpus grows one domain per branch (docs/HANDOFF_CLAUDE_CODE.md, 4.3),
and each domain has its own test file, `tests/test_evidence_<ambito>.py`. The
rules are the same for all of them, so they live here once: a rule tightened
for one domain is tightened for every domain, and a new one cannot ship with
a weaker copy of it. The digestive and skin file wrote these rules first and
keeps its own test; this module is that test made reusable.

Two of the rules are about safety, not shape:

* No chunk may tell a parent how much of a medicine to give. The detector is
  `golden.contains_dosage`, the one the red-flag reply is held to, so it
  flags "5 ml", "unas gotas" and "dale ... cada 6 horas" alike. A nasal wash
  or a rehydration step is written without a quantity for that reason.
* No chunk may name a medicine. A class of remedy (antibiotics, cough syrups,
  honey, herbal teas) may appear only in the sentence that advises against
  it, because "no le des jarabes para la tos" is part of what the sources
  tell parents. The drugs the golden set's dose near-misses ask about (B6,
  B9, B11, B14) are out whatever the sentence says: a chunk that names one
  gives retrieval something to cite for a question the product must refuse.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from pathlib import Path

from adelia.clinical.golden import contains_dosage
from adelia.enrichment import evidence_loader
from adelia.enrichment.evidence_hygiene import canonical_organization

DATA_DIR = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"
ALLOWED_SOURCE_TYPES = {"guideline", "paper", "protocol", "reference"}
META_KEYS = ("topic", "compiled", "method", "caveat", "purpose")

#: Medicines by name. Never, not even in a warning: a named drug next to a
#: symptom is one step from a dose.
NAMED_MEDICINES = re.compile(
    r"paracetamol|acetaminof\w*|ibuprofeno|salbutamol|budesonida|dexametasona|prednisolona|"
    r"hidrocortisona|adrenalina|epinefrina|amoxicilina|code[ií]na|dextrometorfano|loperamida|"
    r"ondansetr[oó]n|propranolol|timolol|polietilenglicol|lactobacillus|domperidona|"
    r"metoclopramida|aciclovir|permetrina|\d+\s*UI\b|®",
    re.IGNORECASE,
)
#: The drugs the golden set's dose near-misses name. Out in any sentence.
NEAR_MISS_DRUGS = {
    "cetirizina": re.compile(r"cetirizina", re.IGNORECASE),
    "simeticona": re.compile(r"simeticona", re.IGNORECASE),
    "melatonina": re.compile(r"melatonina", re.IGNORECASE),
    "flúor": re.compile(r"fl[uú]or", re.IGNORECASE),
}
#: Classes of remedy, allowed only in the sentence that advises against them.
WARNED_REMEDIES = re.compile(
    r"antibi[oó]tic\w*|probi[oó]tic\w*|hom[eo]opat\w*|cortico\w*|antihistam\w*|antitusiv\w*|"
    r"mucol[ií]tic\w*|descongestiv\w*|broncodilatador\w*|jarabe\w*|laxante\w*|antidiarr\w*|"
    r"antiem[eé]tic\w*|antif[uú]ngic\w*|\bmiel\b|infusi[oó]n\w*|manzanilla|hinojo|\ban[ií]s\b|"
    r"\btila\b|\bdosis\b|mg/kg|ml/kg",
    re.IGNORECASE,
)
WARNING = re.compile(
    r"\bno\b|\bnunca\b|\bni\b|evit\w+|desaconsej\w+|contraindic\w+|sin indicaci\w+|"
    r"no se recomienda\w*|no han demostrado|no sirve\w*|no es eficaz|peligros\w+|"
    r"intoxic\w*|t[oó]xic\w*",
    re.IGNORECASE,
)
SPANISH_HINT = re.compile(r"\b(el|la|los|las|de|que|y|en|con|para|bebé|si)\b", re.IGNORECASE)
#: An age past 3 years is fine where the source gives the natural course or the
#: band that contains the baby ("menores de 5 años", "hasta los 4 años").
LATE_AGE_CONTEXT = re.compile(
    r"desaparec|se reducen|se resuelve|tolerar|superan|aclararse|edad escolar|"
    r"menores de \d+ años|mayores de \d+ años|hasta (?:los |que )|antes de los|a partir de los",
    re.IGNORECASE,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(data: dict) -> Iterator[tuple[dict, int, str]]:
    for source in data["sources"]:
        for i, chunk in enumerate(source["chunks"]):
            yield source, i, chunk


def _label(source: dict, i: int | None = None) -> str:
    title = source["title"][:50]
    return title if i is None else f"{title} #{i}"


def check_meta(data: dict) -> None:
    meta = data.get("_meta") or {}
    for key in META_KEYS:
        assert isinstance(meta.get(key), str) and meta[key].strip(), f"_meta.{key}"
    assert "paráfrasis" in meta["caveat"], "the caveat must say the chunks are paraphrases"


def check_size(data: dict, low: int = 30, high: int = 40) -> None:
    n = len(data["sources"])
    assert low <= n <= high, f"{n} sources, expected {low} to {high}"


def check_source_shape(data: dict, subtopics: tuple[str, ...]) -> None:
    """What the loader, the database and the citation card need from a source."""
    titles: set[str] = set()
    urls: set[str] = set()
    for s in data["sources"]:
        label = _label(s)
        assert s["title"] not in titles, f"duplicate title {s['title']!r}"
        titles.add(s["title"])
        assert s["url"] not in urls, f"duplicate url {s['url']}"
        urls.add(s["url"])
        assert len(s["title"]) <= 500, label
        assert s["source_type"] in ALLOWED_SOURCE_TYPES, label
        assert s["url"].startswith("https://") and len(s["url"]) <= 1024, label
        assert s["specialties"] and s["specialties"][0] == "pediatrics", label
        assert s["license"] == "fair_use_snippet", label
        assert s["language"] == "es", label
        org = s["organization"]
        assert isinstance(org, str) and org.strip() and len(org) <= 128, label
        assert canonical_organization(org) == org, f"{label}: organization {org!r} is an alias"
        assert s.get("topics"), f"{label} has no topics"
        unknown = set(s["topics"]) - set(subtopics)
        assert not unknown, f"{label}: topics {sorted(unknown)} are not in the domain's list"
        assert 2 <= len(s["chunks"]) <= 4, f"{label}: {len(s['chunks'])} chunks"
        if s.get("publication_year") is None:
            assert (s.get("undated_reason") or "").strip(), f"{label}: no year and no reason"
        else:
            year = s["publication_year"]
            assert isinstance(year, int) and 1990 <= year <= 2027, f"{label}: year {year!r}"


def check_disjoint_from_other_files(path: Path) -> None:
    """The loader is idempotent by title across files, so a title another file
    already holds is silently skipped at boot. A URL another file already
    cites is a second copy of the same page under another name."""
    mine = load(path)["sources"]
    titles = {s["title"] for s in mine}
    urls = {s["url"] for s in mine}
    for other in sorted(DATA_DIR.glob("evidence_*.json")):
        if other == path:
            continue
        theirs = load(other)["sources"]
        shared_titles = titles & {s["title"] for s in theirs}
        shared_urls = urls & {s["url"] for s in theirs}
        assert not shared_titles, f"{other.name} already has {sorted(shared_titles)}"
        assert not shared_urls, f"{other.name} already cites {sorted(shared_urls)}"


def check_subtopic(data: dict, topic: str, minimum: int = 2) -> None:
    n = sum(topic in s["topics"] for s in data["sources"])
    assert n >= minimum, f"{topic}: {n} source(s), expected at least {minimum}"


def check_chunks_are_sized_attributed_and_spanish(data: dict) -> None:
    for source, i, chunk in chunks(data):
        label = _label(source, i)
        assert 300 <= len(chunk) <= 900, f"{label}: {len(chunk)} chars"
        assert "Tema:" in chunk and "Hallazgo:" in chunk, label
        head = source["title"].split(" (")[0].split(":")[0].split(",")[0][:18]
        assert head in chunk, f"{label} does not open with its title"
        assert "—" not in chunk, f"{label}: em dash"
        assert len(SPANISH_HINT.findall(chunk)) >= 10, f"{label} does not read as Spanish"


def check_no_dose(data: dict) -> None:
    """`contains_dosage` on every chunk, the detector the red-flag reply is held to."""
    for source, i, chunk in chunks(data):
        assert not contains_dosage(chunk), f"{_label(source, i)} carries a dose"


def check_no_medicine(
    data: dict,
    *,
    allow_near_miss: frozenset[str] = frozenset(),
    vaccine_topics: frozenset[str] = frozenset(),
) -> None:
    """Named medicines never; classes of remedy only where the sentence warns.

    `allow_near_miss` lifts the ban on one near-miss drug for the domain whose
    subject it is (fluoride toothpaste in the mouth and teeth domain). The
    golden question that names it still has to be refused, which the
    measurement checks, not this test. `vaccine_topics` are the topics where
    "dosis" counts injections, the one place the word itself is allowed.
    """
    for source, i, chunk in chunks(data):
        label = _label(source, i)
        hit = NAMED_MEDICINES.search(chunk)
        assert not hit, f"{label} names a medicine: {hit.group(0)!r}"
        for name, pattern in NEAR_MISS_DRUGS.items():
            if name not in allow_near_miss:
                assert not pattern.search(chunk), f"{label} names {name!r}"
        vaccine = bool(vaccine_topics & set(source["topics"]))
        for sentence in re.split(r"(?<=[.;:])\s+", chunk):
            for hit in WARNED_REMEDIES.finditer(sentence):
                if vaccine and hit.group(0).lower() == "dosis":
                    continue
                assert WARNING.search(sentence), f"{label}: {hit.group(0)!r} in {sentence!r}"


def check_ages_stay_in_the_first_years(data: dict) -> None:
    """The corpus is for 0-24 months. An age past 3 years appears only where
    the source gives a course or a band that contains the baby."""
    for source, i, chunk in chunks(data):
        for m in re.finditer(r"(\d+)(?:\s*(?:-|a|y)\s*(\d+))?\s*años", chunk):
            if int(m.group(2) or m.group(1)) <= 3:
                continue
            window = chunk[max(0, m.start() - 160): m.end() + 40]
            assert LATE_AGE_CONTEXT.search(window), f"{_label(source, i)}: {m.group(0)!r}"


def check_the_loader_reads_it(path: Path, monkeypatch) -> None:
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
    added, n_chunks = asyncio.run(evidence_loader.load_evidence_file(path))
    data = load(path)
    assert added == len(data["sources"])
    assert n_chunks == sum(len(s["chunks"]) for s in data["sources"])
    assert seen["origin"] == path.name and seen["tier"] == "evidence"
