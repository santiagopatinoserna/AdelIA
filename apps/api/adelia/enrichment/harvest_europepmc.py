"""Harvest open-licensed infant evidence from Europe PMC into a CANDIDATE corpus file.

Why this exists: the public corpus holds 127 sources and 301 chunks, all of
them Spanish paraphrases written by hand (see the `_meta.caveat` of every
data/evidence_*.json). Europe PMC indexes about two thousand systematic
reviews, meta-analyses and guidelines about infants that are open access
under CC BY or CC0, which is enough to grow the corpus by an order of
magnitude without a single line of rewritten text.

What this module does NOT do, on purpose:

* It never writes into `enrichment/data/`. `adelia.main` loads EVERY
  `data/evidence_*.json` at boot, so a file there is a production load the
  next time the API starts. The output goes to `enrichment/candidates/`, under
  a name that does not match the boot glob either, and stays there until a
  person has reviewed it and moved it on purpose.
* It never paraphrases or translates. Each chunk is a verbatim slice of the
  abstract as Europe PMC serves it; the only transformations are the markup
  ones in `normalize_abstract` (section headings become "Label: ", tags are
  dropped, entities are decoded, whitespace is collapsed). Joining the chunks
  with one space gives back the normalized abstract exactly, and a test holds
  that.
* It does not judge clinical quality. The filters below are keyword rules,
  written out so anyone can read why a record was kept or dropped; they
  remove what is clearly off-topic, not what is weak.
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import http.client
import json
import logging
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from adelia.enrichment.evidence_hygiene import canonical_organization

logger = logging.getLogger(__name__)

# Longest chunk, in characters: the window the hand-written corpora use.
CHUNK_LIMIT = 900

_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_SUP = re.compile(r"<sup[^>]*>(.*?)</sup>", re.IGNORECASE | re.DOTALL)
_BLOCK_TAG = re.compile(r"</?(?:p|br|div|li|ul|ol|abstract|sec)\b[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
# A sentence ends at . ! or ? followed by whitespace and something that can
# open a sentence. An abbreviation ("vs. Placebo") may split early; that only
# moves a chunk boundary, it never changes the text.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'])")


def _heading_to_label(match: re.Match[str]) -> str:
    label = _ANY_TAG.sub("", match.group(1)).strip().rstrip(":").strip()
    return f" {label}: " if label else " "


def normalize_abstract(raw: str | None) -> str:
    """The abstract as plain text, with its section labels kept inline.

    Europe PMC returns structured abstracts as `<h4>Background</h4>text`.
    The heading becomes "Background: " so a chunk that starts a section still
    says which one. A superscript becomes "^x" because dropping the tag alone
    would turn "10<sup>9</sup>/L" into "109/L", a different number.
    """
    if not raw:
        return ""
    text = _HEADING.sub(_heading_to_label, raw)
    text = _SUP.sub(lambda m: "^" + m.group(1), text)
    text = _BLOCK_TAG.sub(" ", text)
    text = _ANY_TAG.sub("", text)
    text = html.unescape(text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _split_long(sentence: str, limit: int) -> list[str]:
    """Cut a sentence longer than `limit` at whitespace, keeping every word.

    A token with no space inside the limit is left whole and over-long: a cut
    inside it would add a space the abstract does not have. `build_source`
    drops such a record instead of storing a chunk past the limit.
    """
    pieces: list[str] = []
    rest = sentence
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = rest.find(" ", limit)
            if cut < 0:
                break
        pieces.append(rest[:cut])
        rest = rest[cut + 1:]
    if rest:
        pieces.append(rest)
    return pieces


# ---------------------------------------------------------------------------
# Filters. Each rule is a keyword list, case-insensitive and anchored at word
# starts, so a dropped record can be explained by pointing at a word.
# ---------------------------------------------------------------------------

# Europe PMC writes licenses in lower case ("cc by", "cc0"). Only these two
# allow storing and showing the text verbatim with attribution and nothing
# else; NC and ND variants would restrict what the product may do with it.
_LICENSES = {"cc by": "CC BY", "cc0": "CC0"}

# Not evidence in themselves, or no longer evidence.
EXCLUDED_PUB_TYPES = frozenset({
    "retracted publication", "retraction of publication", "retraction notice",
    "published erratum", "erratum", "correction", "comment", "editorial", "letter",
    "expression of concern", "news",
})
GUIDELINE_PUB_TYPES = frozenset({"practice guideline", "guideline"})

# Words that place a record in the first two years of life. "Early
# childhood" reaches age 5, which is why a title match alone keeps a record
# but the abstract needs two hits (see _MIN_ABSTRACT_INFANT_HITS).
_INFANT = re.compile(
    r"\b(?:infan\w*|newborn\w*|new-born\w*|neonat\w*|toddler\w*|bab(?:y|ies)\b|"
    r"breast[- ]?(?:fe\w*|milk)|human milk|preterm\w*|first 1,?000 days|"
    r"under[- ](?:two|2)s?\b|0-24 months|early childhood|weaning)",
    re.IGNORECASE,
)
_MIN_ABSTRACT_INFANT_HITS = 2

# A population that is not 0-24 months, named in the title. Only applied when
# the title names no infant term, so "adolescent mothers and their infants"
# survives.
_OTHER_POPULATION = re.compile(
    r"\b(?:adults?\b|adolescen\w*|teen\w*|elderly|older (?:people|persons|adults)|"
    r"school[- ]?(?:age\w*|children)|schoolchildren|students?\b|youths?\b|men\b|women\b|"
    r"workers?\b|nurses?\b|physicians?\b|college|universit\w*)",
    re.IGNORECASE,
)

# Pregnancy and the mother, named in the title. Dropped unless the abstract
# reports an outcome measured on the child (_CHILD_OUTCOME).
_MATERNAL = re.compile(
    r"\b(?:pregnan\w*|gestation\w*|maternal|mothers?\b|postpartum|post-partum|antenatal|"
    r"prenatal|pre-?eclampsia|caesarean|cesarean|childbirth|obstetric\w*|labou?r\b)",
    re.IGNORECASE,
)
_CHILD_OUTCOME = re.compile(
    r"\b(?:infant|neonatal|newborn|child|offspring)s?'?\s+(?:birth ?weight|outcomes?|"
    r"growth|development|health|mortality|morbidity|rickets|allerg\w*|eczema|sleep|"
    r"feeding|infections?)",
    re.IGNORECASE,
)

# Animals. "rats" is matched in lower case only: upper-case RAT is a rapid
# antigen test. "bovine" is absent on purpose, cow's milk is a human topic.
_ANIMAL = re.compile(
    r"\b(?:mice|mouse|murine|(?-i:rats?)|rodents?|piglets?|porcine|swine|pigs?|lambs?|"
    r"ovine|sheep|calf|calves|primates?|monkeys?|macaques?|rabbits?|canine|dogs?|"
    r"feline|cats?|zebrafish|animal models?)\b",
    re.IGNORECASE,
)
# An abstract that names an animal and any of these is a human review that
# mentions animal work (often to say it was excluded).
_HUMAN = re.compile(
    r"\b(?:humans?|children|child|participants|patients|women|mothers|girls|boys|people|"
    r"persons|randomi[sz]ed controlled|RCTs?)\b",
    re.IGNORECASE,
)


def license_label(raw: str | None) -> str | None:
    """The license as it is stored ("CC BY", "CC0"), or None when not allowed."""
    if not raw:
        return None
    return _LICENSES.get(raw.strip().lower())


def _pub_types(record: dict) -> set[str]:
    raw = (record.get("pubTypeList") or {}).get("pubType") or []
    if isinstance(raw, str):
        raw = [raw]
    return {p.strip().lower().replace("-", " ") for p in raw if isinstance(p, str)}


def source_type_for(record: dict) -> str:
    """'guideline' for guideline pub types, 'paper' for reviews and the rest."""
    return "guideline" if _pub_types(record) & GUIDELINE_PUB_TYPES else "paper"


def clean_title(raw: str | None) -> str:
    """Title without markup and without the trailing period MEDLINE adds."""
    text = html.unescape(_ANY_TAG.sub("", raw or ""))
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def drop_reason(record: dict) -> str | None:
    """Why `record` cannot be a candidate source, or None when it can.

    Checks run cheapest and least debatable first, so the reason reported is
    the strongest one: a retracted CC BY-NC review is reported as a license
    problem, which needs no judgment at all.
    """
    if license_label(record.get("license")) is None:
        return "license_not_cc_by_or_cc0"
    abstract = normalize_abstract(record.get("abstractText"))
    if not abstract:
        return "no_abstract"
    if _pub_types(record) & EXCLUDED_PUB_TYPES:
        return "excluded_pub_type"
    title = clean_title(record.get("title"))
    if _ANIMAL.search(title) or (_ANIMAL.search(abstract) and not _HUMAN.search(abstract)):
        return "animal_study"
    if _INFANT.search(title):
        return None
    if _MATERNAL.search(title) and not _CHILD_OUTCOME.search(abstract):
        return "maternal_only"
    if _OTHER_POPULATION.search(title):
        return "not_0_24_months"
    if len(_INFANT.findall(abstract)) < _MIN_ABSTRACT_INFANT_HITS:
        return "not_0_24_months"
    return None


def chunk_abstract(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Pack whole sentences into chunks of at most `limit` characters.

    The target size is the abstract split evenly over the fewest chunks that
    fit, so a 1,000 character abstract becomes two halves rather than 900
    characters plus a 100 character tail that retrieval would match on
    nothing but a trial registration number.
    """
    if not text:
        return []
    sentences: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentences.extend(_split_long(sentence, limit))
    target = len(text) / max(1, math.ceil(len(text) / limit))
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= limit and len(current) < target:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Parent-concern topics. A source is tagged with every topic whose keywords
# appear in its title or abstract; the tags let a reviewer sample the file by
# concern and see which concerns the harvest leaves thin. Keywords match at a
# word start, so "vaccin" covers vaccine, vaccines and vaccination.
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reflux_vomiting": ("reflux", "gerd", "gord", "regurgitat", "vomit", "spit-up",
                        "spitting up", "posseting"),
    "feeding": ("breastfe", "breast-fe", "breast fe", "breast milk", "breastmilk", "human milk",
                "lactation", "infant formula", "formula-fed", "formula fed", "complementary feed",
                "complementary food", "weaning", "solid food", "bottle-fe", "bottle fe",
                "responsive feeding", "baby-led", "feeding", "feeds"),
    "sleep_sids": ("sleep", "sids", "sudden infant death", "sudi", "sudden unexpected infant",
                   "bed-sharing", "bed sharing", "co-sleeping", "cosleeping", "cot death"),
    "fever_infections": ("fever", "febrile", "infection", "infectious", "sepsis", "septic",
                         "bronchiolitis", "rsv", "respiratory syncytial", "otitis", "pneumonia",
                         "meningitis", "urinary tract", "antibiotic", "influenza", "covid"),
    "growth_weight": ("growth", "weight gain", "stunting", "stunted", "wasting", "overweight",
                      "obesity", "obese", "bmi", "body mass", "failure to thrive",
                      "faltering growth", "length-for-age", "weight-for"),
    "allergy_eczema": ("allerg", "eczema", "atopic", "anaphyla", "cow's milk protein",
                       "cows' milk protein", "cow's milk allergy", "sensitisation",
                       "sensitization", "wheez", "asthma"),
    "crying_colic": ("colic", "crying", "cry ", "fussiness", "fussy", "inconsolable"),
    # Not "development" or "language" alone: "development of the search
    # strategy" and "English language studies" are review boilerplate.
    "development": ("neurodevelopment", "developmental", "child development",
                    "infant development", "early development", "milestone", "cognitive",
                    "cognition", "language development", "language delay", "speech",
                    "motor skill", "motor development", "autism", "screen time"),
    "iron_vitamin_d": ("iron", "anaemia", "anemia", "ferritin", "vitamin d", "rickets",
                       "cholecalciferol"),
    "skin": ("skin", "dermatitis", "diaper rash", "nappy rash", "diaper dermatitis", "emollient",
             "cradle cap", "seborrh", "haemangioma", "hemangioma", "birthmark", "eczema"),
    "jaundice": ("jaundice", "hyperbilirubin", "bilirubin", "phototherapy", "icterus"),
    "constipation_diarrhea": ("constipat", "diarrhoea", "diarrhea", "diarrheal", "stool",
                              "bowel movement", "gastroenteritis", "dehydration",
                              "oral rehydration"),
    "teething": ("teething", "tooth eruption", "primary teeth", "deciduous teeth",
                 "early childhood caries", "dental caries", "oral health"),
    "vaccines": ("vaccin", "immunization", "immunisation", "immunize", "immunise", "bcg"),
}

_TOPIC_PATTERNS = {
    topic: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + ")", re.IGNORECASE)
    for topic, keywords in TOPIC_KEYWORDS.items()
}


def topics_for(text: str) -> list[str]:
    """Sorted topic tags whose keywords appear in `text`."""
    return sorted(topic for topic, pattern in _TOPIC_PATTERNS.items() if pattern.search(text))


# ---------------------------------------------------------------------------
# Record to source.
# ---------------------------------------------------------------------------

# Column widths of models.EvidenceSource (see tests/test_evidence_files.py).
ORGANIZATION_LIMIT = 128
FALLBACK_ORGANIZATION = "Europe PMC"


def _organization(record: dict) -> str:
    """The journal, spelled the canonical way and cut at a word to fit.

    Journal articles keep the journal as their organization (see
    evidence_hygiene): a review in "Pediatrics" is not a document of the
    Academy, but the journal's canonical spelling is applied so the field
    stays one string per title.
    """
    journal = ((record.get("journalInfo") or {}).get("journal") or {})
    name = (journal.get("title") or journal.get("medlineAbbreviation") or "").strip()
    name = canonical_organization(name) or FALLBACK_ORGANIZATION
    if len(name) > ORGANIZATION_LIMIT:
        cut = name.rfind(" ", 0, ORGANIZATION_LIMIT + 1)
        name = name[: cut if cut > 0 else ORGANIZATION_LIMIT].rstrip(" ,;:-")
    return name


def _year(record: dict) -> int | None:
    for value in (record.get("pubYear"), (record.get("journalInfo") or {}).get(
            "yearOfPublication")):
        try:
            year = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if 1900 <= year <= 2100:
            return year
    return None


def _url(record: dict) -> str:
    doi = (record.get("doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    return f"https://europepmc.org/article/{record.get('source', 'MED')}/{record.get('id')}"


def build_source(record: dict) -> dict:
    """One kept record in the shape of a data/evidence_*.json source.

    `topics` and `europepmc_id` are extra keys. The loader builds each
    EvidenceSource from named fields only (evidence_loader.load_evidence_file),
    so unknown keys are ignored there, as `undated_reason` already is.
    """
    abstract = normalize_abstract(record.get("abstractText"))
    title = clean_title(record.get("title"))
    source: dict = {
        "source_type": source_type_for(record),
        "title": title,
        "organization": _organization(record),
        "publication_year": _year(record),
        "url": _url(record),
        "specialties": ["pediatrics"],
        "license": license_label(record.get("license")),
        "language": "en",
        "topics": topics_for(f"{title} {abstract}"),
        "europepmc_id": f"{record.get('source', 'MED')}:{record.get('id')}",
        "chunks": chunk_abstract(abstract),
    }
    if source["publication_year"] is None:
        source["undated_reason"] = "Europe PMC record carries no publication year"
    return source


# ---------------------------------------------------------------------------
# Selection over the whole harvest.
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
# Mirror of the boot loader in adelia.main: every file matching this, in
# DATA_DIR, is loaded into production at startup. The candidate must match
# neither (tests/test_harvest_europepmc.py holds both halves).
BOOT_GLOB = "evidence_*.json"
CANDIDATES_DIR = Path(__file__).parent / "candidates"
DEFAULT_OUT = CANDIDATES_DIR / "europepmc_infant_reviews.json"


def normalized_title(title: str | None) -> str:
    """Lower-case letters and digits only: the key two copies of a title share."""
    text = clean_title(title).casefold()
    return " ".join(re.findall(r"[^\W_]+", text))


def existing_corpus_titles(data_dir: Path = DATA_DIR) -> set[str]:
    """Normalized titles of every source already in the boot-loaded corpus.

    The loader is idempotent by exact title, so a review the corpus already
    paraphrases in Spanish would come back as a second source under its
    English title; matching on the normalized title catches the case where
    the hand-written entry kept the original English title.
    """
    titles: set[str] = set()
    for path in sorted(data_dir.glob(BOOT_GLOB)):
        data = json.loads(path.read_text(encoding="utf-8"))
        titles.update(normalized_title(s.get("title")) for s in data.get("sources", []))
    return titles


def _summary(record: dict) -> dict:
    journal = ((record.get("journalInfo") or {}).get("journal") or {}).get("title")
    return {
        "europepmc_id": f"{record.get('source', 'MED')}:{record.get('id')}",
        "title": clean_title(record.get("title")),
        "journal": journal,
        "year": _year(record),
    }


@dataclass
class HarvestResult:
    sources: list[dict] = field(default_factory=list)
    dropped: list[tuple[dict, str]] = field(default_factory=list)
    fetched: int = 0

    def dropped_counts(self) -> dict[str, int]:
        return dict(Counter(reason for _, reason in self.dropped))


def select(records: Iterable[dict], existing_titles: set[str]) -> HarvestResult:
    """Filter, build and dedupe, in the order the records came.

    The first copy of a DOI or of a title wins; later ones are recorded as
    duplicates rather than silently skipped, so the counts add up to what
    was fetched.
    """
    result = HarvestResult()
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    for record in records:
        result.fetched += 1
        reason = drop_reason(record)
        doi = (record.get("doi") or "").strip().lower()
        key = normalized_title(record.get("title"))
        if reason is None and doi and doi in seen_dois:
            reason = "duplicate_doi"
        if reason is None and key in seen_titles:
            reason = "duplicate_title"
        if reason is None and key in existing_titles:
            reason = "already_in_corpus"
        source = build_source(record) if reason is None else None
        if source is not None and any(len(c) > CHUNK_LIMIT for c in source["chunks"]):
            reason, source = "chunk_over_limit", None
        if source is None:
            result.dropped.append((_summary(record), reason or "unknown"))
            continue
        result.sources.append(source)
        if doi:
            seen_dois.add(doi)
        seen_titles.add(key)
    return result


METHOD = (
    "Europe PMC REST search (resultType=core, cursorMark paging). Kept: records with an "
    "abstract, license CC BY or CC0, not retracted, erratum, comment, editorial or letter, "
    "about children 0-24 months by the keyword rules in adelia/enrichment/harvest_europepmc.py, "
    "deduplicated by DOI and normalized title, and not already in data/evidence_*.json. Chunks "
    "are the abstract after markup normalization, split on sentence boundaries into pieces of "
    f"at most {CHUNK_LIMIT} characters; joined with one space they give the abstract back."
)
CAVEAT = (
    "verbatim abstract text, English, open license; not clinically reviewed. Candidate "
    "file, not loaded at boot. License is CC BY or CC0 per source, attribution via title, "
    "journal and DOI. Topic tags come from keyword matching and are hints for review, not "
    "classifications."
)


def build_document(result: HarvestResult, query: str, harvested_on: str) -> dict:
    """The candidate file: corpus-shaped sources plus a _meta that says what they are."""
    topic_counts = Counter(t for s in result.sources for t in s["topics"])
    return {
        "_meta": {
            "topic": "Systematic reviews, meta-analyses and guidelines about infants and "
                     "toddlers (0-24 months), open access",
            "source": "Europe PMC (https://europepmc.org)",
            "query": query,
            "harvested": harvested_on,
            "method": METHOD,
            "caveat": CAVEAT,
            "counts": {
                "fetched": result.fetched,
                "kept": len(result.sources),
                "dropped": result.dropped_counts(),
                "chunks": sum(len(s["chunks"]) for s in result.sources),
                "topics": dict(sorted(topic_counts.items())),
                "untagged": sum(1 for s in result.sources if not s["topics"]),
            },
        },
        "sources": result.sources,
    }


def check_out_path(path: Path) -> Path:
    """Refuse an output path the boot loader would read.

    Anything inside DATA_DIR is refused, not only names matching the glob:
    the glob is one edit of main.py away from widening. A name matching the
    glob is refused anywhere, so moving the file into DATA_DIR later is a
    rename someone has to choose, not an accident of copying it.
    """
    resolved = path.resolve()
    if resolved.is_relative_to(DATA_DIR.resolve()):
        raise ValueError(f"{path} is inside {DATA_DIR}, which adelia.main loads at boot")
    if fnmatch.fnmatch(resolved.name, BOOT_GLOB):
        raise ValueError(f"{path.name} matches the boot glob {BOOT_GLOB!r}")
    return path


# ---------------------------------------------------------------------------
# Fetching. Europe PMC asks for moderate use; this stays under 5 requests per
# second, retries what is transient and nothing else, and names the project
# without a contact address.
# ---------------------------------------------------------------------------

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
USER_AGENT = "AdelIA-evidence-harvester/1.0 (open-source pediatric evidence corpus)"
MIN_INTERVAL_S = 0.25
RETRY_DELAYS_S: tuple[float, ...] = (2.0, 5.0, 15.0, 30.0)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# 500-record core pages took minutes to stream and broke off mid-body live.
PAGE_SIZE = 100

DEFAULT_QUERY = (
    '(TITLE_ABS:"infant" OR TITLE_ABS:"infants" OR TITLE_ABS:"newborn" OR '
    'TITLE_ABS:"toddler" OR TITLE_ABS:"breastfed") AND (PUB_TYPE:"Systematic Review" OR '
    'PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Practice Guideline" OR PUB_TYPE:"Guideline") AND '
    'PUB_YEAR:[2010 TO 2026] AND SRC:MED AND OPEN_ACCESS:y AND '
    '(LICENSE:"cc by" OR LICENSE:"cc0")'
)

Opener = Callable[[urllib.request.Request, float], bytes]


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


class PoliteClient:
    """GET JSON with a minimum interval between requests and bounded retries.

    The opener, clock and sleep are injected so the tests exercise the real
    pacing and retry logic without a network or a real wait.
    """

    def __init__(self, opener: Opener = _urlopen, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 min_interval: float = MIN_INTERVAL_S,
                 delays: tuple[float, ...] = RETRY_DELAYS_S, timeout: float = 120.0) -> None:
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._min_interval = min_interval
        self._delays = delays
        self._timeout = timeout
        self._last: float | None = None

    def _pace(self) -> None:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get_json(self, url: str) -> dict:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for delay in (*self._delays, None):
            self._pace()
            try:
                return json.loads(self._opener(request, self._timeout))
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRYABLE_STATUS or delay is None:
                    raise
                logger.warning("Europe PMC HTTP %d, retrying in %.0fs", exc.code, delay)
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    http.client.HTTPException, json.JSONDecodeError) as exc:
                # A body cut off mid-stream surfaces as IncompleteRead or as
                # JSON that ends early; both mean "fetch the same page again".
                if delay is None:
                    raise
                logger.warning("Europe PMC unreachable or truncated (%s), retrying in %.0fs",
                               type(exc).__name__, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


def iter_records(query: str, max_records: int, get_json: Callable[[str], dict],
                 page_size: int = PAGE_SIZE) -> Iterator[dict]:
    """Yield search results page by page until the cursor stops or max is reached."""
    cursor = "*"
    yielded = 0
    while yielded < max_records:
        params = {"query": query, "format": "json", "resultType": "core",
                  "pageSize": str(min(page_size, max_records - yielded)), "cursorMark": cursor}
        page = get_json(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
        results = (page.get("resultList") or {}).get("result") or []
        for record in results:
            if yielded >= max_records:
                return
            yield record
            yielded += 1
        next_cursor = page.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor:
            return
        cursor = next_cursor


# ---------------------------------------------------------------------------
# Report and CLI.
# ---------------------------------------------------------------------------

YEAR_BANDS: tuple[tuple[str, int, int], ...] = (
    ("before 2010", 0, 2009), ("2010-2014", 2010, 2014), ("2015-2019", 2015, 2019),
    ("2020-2026", 2020, 2026),
)


def _year_band(year: int | None) -> str:
    for label, low, high in YEAR_BANDS:
        if year is not None and low <= year <= high:
            return label
    return "undated or later"


def _block(title: str, counts: Counter | dict) -> list[str]:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"{title}:", *(f"  {key}: {value}" for key, value in items)]


def format_report(document: dict) -> str:
    """Plain-text counts a reviewer reads before deciding to use the file."""
    counts = document["_meta"]["counts"]
    sources = document["sources"]
    dropped = sum(counts["dropped"].values())
    lines = [f"fetched {counts['fetched']}, kept {counts['kept']}, dropped {dropped}",
             f"chunks: {counts['chunks']}"]
    lines += _block("dropped by reason", counts["dropped"])
    lines += _block("source_type", Counter(s["source_type"] for s in sources))
    bands = Counter(_year_band(s["publication_year"]) for s in sources)
    lines += ["year band:", *(f"  {label}: {bands[label]}" for label in
                              [b[0] for b in YEAR_BANDS] + ["undated or later"] if bands[label])]
    lines += _block("topics", counts["topics"])
    lines.append(f"  (untagged): {counts['untagged']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None,
         get_json: Callable[[str], dict] | None = None) -> int:
    """CLI: python -m adelia.enrichment.harvest_europepmc --max 3000 --out PATH --report"""
    parser = argparse.ArgumentParser(prog="python -m adelia.enrichment.harvest_europepmc",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--max", type=int, default=3000, help="most records to fetch")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="candidate JSON path")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Europe PMC search query")
    parser.add_argument("--report", action="store_true", help="print counts after writing")
    parser.add_argument("--dropped", type=Path, help="also write dropped records and reasons")
    args = parser.parse_args(argv)
    try:
        check_out_path(args.out)
    except ValueError as exc:
        parser.error(str(exc))

    logging.basicConfig(level=logging.INFO)
    fetch = get_json or PoliteClient().get_json
    records = iter_records(args.query, args.max, fetch)
    result = select(records, existing_corpus_titles())
    document = build_document(result, args.query, date.today().isoformat())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    if args.dropped:
        rows = [{**summary, "reason": reason} for summary, reason in result.dropped]
        args.dropped.parent.mkdir(parents=True, exist_ok=True)
        args.dropped.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    print(f"wrote {args.out}: {len(result.sources)} sources, "
          f"{document['_meta']['counts']['chunks']} chunks")
    if args.report:
        print(format_report(document))
    return 0


if __name__ == "__main__":
    sys.exit(main())
