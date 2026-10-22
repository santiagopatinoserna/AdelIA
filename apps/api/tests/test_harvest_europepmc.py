"""The Europe PMC harvester builds a CANDIDATE corpus file, offline-testable.

Pure tests: no database, no network. The records below are shaped like the
`resultType=core` JSON of the Europe PMC REST search, trimmed to the fields
the harvester reads.
"""
from __future__ import annotations

import fnmatch
import http.client
import json
import urllib.error
from pathlib import Path

import pytest

from adelia.enrichment import harvest_europepmc as h

ABSTRACT_HTML = (
    "<h4>Background</h4>Reflux is common in infants. It usually resolves by 12 months."
    "<h4>Methods</h4>We searched <i>PubMed</i> and Embase. Ten trials (n = 1,203) were included."
    "<h4>Results</h4>Thickened feeds reduced regurgitation &amp; vomiting (RR 0.6). Platelets "
    "were 150 &times; 10<sup>9</sup>/L."
)


def test_normalize_abstract_keeps_section_labels_and_strips_markup():
    text = h.normalize_abstract(ABSTRACT_HTML)
    assert text.startswith("Background: Reflux is common in infants.")
    assert " Methods: We searched PubMed and Embase." in text
    assert "regurgitation & vomiting" in text
    assert "10^9/L" in text
    assert "<" not in text and "  " not in text


def test_normalize_abstract_of_nothing_is_empty():
    assert h.normalize_abstract(None) == ""
    assert h.normalize_abstract("   <p> </p> ") == ""


def test_chunks_are_verbatim_and_concatenate_to_the_normalized_abstract():
    text = h.normalize_abstract(ABSTRACT_HTML)
    chunks = h.chunk_abstract(text, limit=120)
    assert len(chunks) > 1
    assert " ".join(chunks) == text
    assert all(0 < len(c) <= 120 for c in chunks)


def test_chunks_break_on_sentence_boundaries():
    text = h.normalize_abstract(ABSTRACT_HTML)
    for chunk in h.chunk_abstract(text, limit=120)[:-1]:
        assert chunk.endswith((".", "!", "?")), chunk


def test_a_sentence_longer_than_the_limit_is_split_on_whitespace_without_loss():
    text = "Background: " + " ".join(f"word{i}" for i in range(400)) + "."
    chunks = h.chunk_abstract(text, limit=900)
    assert " ".join(chunks) == text
    assert all(len(c) <= 900 for c in chunks)


def test_a_short_abstract_is_a_single_chunk():
    assert h.chunk_abstract("One sentence only.") == ["One sentence only."]


def test_a_token_longer_than_the_limit_is_never_cut_inside_a_word():
    """Cutting mid-word would put a space into the text that the abstract
    does not have, so the over-long token stays whole and the record is
    dropped later (see test_a_record_whose_chunks_cannot_fit_is_dropped)."""
    token = "x" * 1000
    chunks = h.chunk_abstract(f"Short start. {token} end.", limit=900)
    assert " ".join(chunks) == f"Short start. {token} end."


# ---------------------------------------------------------------------------
# Filters: one record in, a drop reason (or None) out.
# ---------------------------------------------------------------------------

INFANT_ABSTRACT = (
    "<h4>Background</h4>Gastro-oesophageal reflux is frequent in infants under 12 months. "
    "<h4>Methods</h4>We pooled randomised trials of thickened feeds in infants. "
    "<h4>Results</h4>Twelve trials with 1,034 infants showed fewer regurgitation episodes."
)


def _rec(**overrides) -> dict:
    record = {
        "id": "100",
        "source": "MED",
        "pmid": "100",
        "doi": "10.1000/abc.100",
        "title": "Thickened feeds for reflux in infants: a systematic review.",
        "pubYear": "2021",
        "license": "cc by",
        "pubTypeList": {"pubType": ["Systematic Review", "Journal Article"]},
        "journalInfo": {"journal": {"title": "Archives of disease in childhood",
                                    "medlineAbbreviation": "Arch Dis Child"}},
        "abstractText": INFANT_ABSTRACT,
    }
    record.update(overrides)
    return record


def test_an_on_topic_open_record_is_kept():
    assert h.drop_reason(_rec()) is None


def test_license_is_recorded_exactly_and_only_cc_by_or_cc0_pass():
    assert h.license_label("cc by") == "CC BY"
    assert h.license_label("CC BY") == "CC BY"
    assert h.license_label("cc0") == "CC0"
    for other in ("cc by-nc", "cc by-nc-nd", "cc by-sa", "", None, "other"):
        assert h.license_label(other) is None, other
    assert h.drop_reason(_rec(license="cc by-nc")) == "license_not_cc_by_or_cc0"
    assert h.drop_reason(_rec(license=None)) == "license_not_cc_by_or_cc0"


def test_a_record_without_abstract_is_dropped():
    assert h.drop_reason(_rec(abstractText=None)) == "no_abstract"
    assert h.drop_reason(_rec(abstractText="<p></p>")) == "no_abstract"


def test_retractions_errata_and_comments_are_dropped():
    for pub_type in ("Retracted Publication", "Retraction of Publication",
                     "Published Erratum", "Erratum", "Comment", "Editorial", "Letter"):
        record = _rec(pubTypeList={"pubType": ["Systematic Review", pub_type]})
        assert h.drop_reason(record) == "excluded_pub_type", pub_type


def test_animal_studies_are_dropped():
    assert h.drop_reason(_rec(title="Probiotics in neonatal piglets: a meta-analysis.")) == (
        "animal_study")
    assert h.drop_reason(_rec(
        title="Early-life antibiotics and gut microbiota: a systematic review.",
        abstractText="Infant mice and rats exposed to antibiotics had altered microbiota.",
    )) == "animal_study"


def test_a_human_review_that_mentions_animal_work_is_kept():
    record = _rec(abstractText=INFANT_ABSTRACT + " Animal studies in mice were excluded; "
                  "we included children only.")
    assert h.drop_reason(record) is None


def test_adult_or_adolescent_only_reviews_are_dropped():
    for title in ("Vitamin D in older adults: a meta-analysis.",
                  "Sleep and screen use in adolescents: a systematic review.",
                  "Obesity prevention in school-age children: a systematic review."):
        record = _rec(title=title, abstractText="We reviewed trials. Adults and infants "
                      "were mentioned once in the infants background.")
        assert h.drop_reason(record) == "not_0_24_months", title


def test_maternal_only_outcomes_are_dropped():
    record = _rec(
        title="Exercise during pregnancy and gestational diabetes: a meta-analysis.",
        abstractText="Pregnant women who exercised had less gestational diabetes. "
                     "Infant data were not reported for most infants.",
    )
    assert h.drop_reason(record) == "maternal_only"


def test_a_maternal_intervention_with_an_infant_outcome_is_kept():
    record = _rec(
        title="Maternal vitamin D supplementation in pregnancy: a meta-analysis.",
        abstractText="Supplementation raised infant birth weight and reduced infant "
                     "rickets. Neonatal outcomes improved in infants.",
    )
    assert h.drop_reason(record) is None


def test_a_record_that_barely_mentions_infants_is_dropped():
    record = _rec(title="Antibiotic stewardship in primary care: a systematic review.",
                  abstractText="Prescribing fell across all ages, infants included.")
    assert h.drop_reason(record) == "not_0_24_months"


def test_source_type_follows_the_pub_type():
    assert h.source_type_for(_rec()) == "paper"
    meta = _rec(pubTypeList={"pubType": ["Meta-Analysis"]})
    assert h.source_type_for(meta) == "paper"
    for guideline in ("Practice Guideline", "Guideline"):
        record = _rec(pubTypeList={"pubType": [guideline, "Journal Article"]})
        assert h.source_type_for(record) == "guideline"


# ---------------------------------------------------------------------------
# Topics and the source shape.
# ---------------------------------------------------------------------------


def test_topics_come_from_the_documented_keyword_map():
    assert set(h.TOPIC_KEYWORDS) == {
        "reflux_vomiting", "feeding", "sleep_sids", "fever_infections", "growth_weight",
        "allergy_eczema", "crying_colic", "development", "iron_vitamin_d", "skin",
        "jaundice", "constipation_diarrhea", "teething", "vaccines",
    }
    assert h.topics_for("Thickened feeds for reflux and vomiting in breastfed infants") == [
        "feeding", "reflux_vomiting"]
    assert h.topics_for("Phototherapy for neonatal hyperbilirubinaemia") == ["jaundice"]
    assert h.topics_for("Rotavirus vaccination and diarrhoea") == [
        "constipation_diarrhea", "vaccines"]
    assert h.topics_for("Teething and fever") == ["fever_infections", "teething"]
    assert h.topics_for("Nothing relevant here") == []


def test_build_source_has_the_corpus_shape():
    source = h.build_source(_rec())
    assert source["source_type"] == "paper"
    assert source["title"] == "Thickened feeds for reflux in infants: a systematic review"
    assert source["organization"] == "Archives of disease in childhood"
    assert source["publication_year"] == 2021
    assert source["url"] == "https://doi.org/10.1000/abc.100"
    assert source["specialties"] == ["pediatrics"]
    assert source["license"] == "CC BY"
    assert source["language"] == "en"
    assert " ".join(source["chunks"]) == h.normalize_abstract(INFANT_ABSTRACT)
    assert "reflux_vomiting" in source["topics"]
    assert source["europepmc_id"] == "MED:100"


def test_build_source_without_doi_links_to_europe_pmc():
    source = h.build_source(_rec(doi=None))
    assert source["url"] == "https://europepmc.org/article/MED/100"


def test_organization_is_canonical_and_fits_the_column():
    pediatrics = _rec(journalInfo={"journal": {"title": "Pediatrics"}})
    assert h.build_source(pediatrics)["organization"] == (
        "Pediatrics (American Academy of Pediatrics)")
    long_name = "Journal of " + "very " * 40 + "long names"
    org = h.build_source(_rec(journalInfo={"journal": {"title": long_name}}))["organization"]
    assert len(org) <= 128 and long_name.startswith(org) and not org.endswith(" ")
    no_journal = h.build_source(_rec(journalInfo={}))["organization"]
    assert no_journal == "Europe PMC"


def test_year_falls_back_to_the_journal_issue_or_says_why_it_is_missing():
    record = _rec(pubYear=None, journalInfo={"yearOfPublication": 2019,
                                             "journal": {"title": "BMJ open"}})
    assert h.build_source(record)["publication_year"] == 2019
    undated = h.build_source(_rec(pubYear=None))
    assert undated["publication_year"] is None
    assert undated["undated_reason"]


def test_review_boilerplate_does_not_tag_a_topic():
    """Words every systematic review uses about itself must not tag a concern:
    otherwise every source is "allergy" (sensitivity analysis) and
    "development" (English language, development of the protocol)."""
    boilerplate = ("A sensitivity analysis was run. Only English language studies were "
                   "included. The development of the search strategy followed PRISMA.")
    assert h.topics_for(boilerplate) == []


# ---------------------------------------------------------------------------
# Selection over many records: dedupe, existing corpus, the output document.
# ---------------------------------------------------------------------------


def test_normalized_title_ignores_case_punctuation_and_markup():
    assert h.normalized_title("Thickened <i>feeds</i> for Reflux, in infants.") == (
        h.normalized_title("thickened feeds for reflux in infants"))


def test_duplicates_by_doi_and_by_title_are_dropped():
    records = [
        _rec(),
        _rec(id="101", pmid="101", doi="10.1000/ABC.100", title="Another title on infants."),
        _rec(id="102", pmid="102", doi="10.1000/other", title="THICKENED feeds for reflux "
             "in infants: a systematic review"),
        _rec(id="103", pmid="103", doi="10.1000/new", title="Colic in infants: a review."),
    ]
    result = h.select(records, existing_titles=set())
    assert [s["europepmc_id"] for s in result.sources] == ["MED:100", "MED:103"]
    assert [reason for _, reason in result.dropped] == ["duplicate_doi", "duplicate_title"]
    assert result.fetched == 4


def test_titles_already_in_the_corpus_are_dropped():
    existing = {h.normalized_title("Colic in infants: a review")}
    result = h.select([_rec(title="Colic in infants: a review.")], existing_titles=existing)
    assert result.sources == []
    assert result.dropped[0][1] == "already_in_corpus"


def test_existing_corpus_titles_are_read_from_every_evidence_file():
    titles = h.existing_corpus_titles()
    assert h.normalized_title(
        "Recomendaciones de la Asociación Española de Pediatría sobre la Alimentación "
        "Complementaria") in titles
    assert len(titles) >= 100


def test_a_record_whose_chunks_cannot_fit_is_dropped():
    record = _rec(abstractText="Infants were studied. " + "x" * 1000 + " infants.")
    result = h.select([record], existing_titles=set())
    assert result.dropped[0][1] == "chunk_over_limit"


def test_filter_drops_are_reported_with_their_reason():
    result = h.select([_rec(license="cc by-nc"), _rec(abstractText="")], existing_titles=set())
    assert [reason for _, reason in result.dropped] == ["license_not_cc_by_or_cc0",
                                                        "no_abstract"]
    assert result.dropped_counts() == {"license_not_cc_by_or_cc0": 1, "no_abstract": 1}


# Mirror of tests/test_evidence_files.py, applied to the candidate document.
ALLOWED_SOURCE_TYPES = {"guideline", "paper", "protocol", "reference"}


def _assert_corpus_constraints(document: dict) -> None:
    from adelia.enrichment.evidence_hygiene import canonical_organization, looks_like_url

    sources = document["sources"]
    titles = [s["title"] for s in sources]
    assert len(titles) == len(set(titles))
    for s in sources:
        assert s["source_type"] in ALLOWED_SOURCE_TYPES
        assert s["chunks"] and all(isinstance(c, str) and c for c in s["chunks"])
        assert all(len(c) <= h.CHUNK_LIMIT for c in s["chunks"])
        assert len(s["title"]) <= 500
        for field, limit in (("organization", 128), ("url", 1024), ("license", 64),
                             ("language", 8)):
            assert len(s.get(field) or "") <= limit, field
        assert s["organization"].strip() and not looks_like_url(s["organization"])
        assert canonical_organization(s["organization"]) == s["organization"]
        assert s["license"] in {"CC BY", "CC0"}
        assert s["language"] == "en"
        assert s["specialties"] == ["pediatrics"]
        year = s["publication_year"]
        assert (isinstance(year, int) and 1900 <= year <= 2100) or s.get("undated_reason")


def test_the_output_document_satisfies_the_corpus_constraints_and_says_what_it_is():
    records = [_rec(), _rec(id="103", pmid="103", doi=None, title="Colic in infants: a review.",
                            pubTypeList={"pubType": ["Practice Guideline"]}),
               _rec(id="104", license="cc by-nc-nd")]
    result = h.select(records, existing_titles=set())
    document = h.build_document(result, query="q", harvested_on="2026-10-22")
    _assert_corpus_constraints(document)
    meta = document["_meta"]
    assert meta["query"] == "q" and meta["harvested"] == "2026-10-22"
    assert meta["counts"]["fetched"] == 3
    assert meta["counts"]["kept"] == 2
    assert meta["counts"]["dropped"] == {"license_not_cc_by_or_cc0": 1}
    assert meta["counts"]["chunks"] == sum(len(s["chunks"]) for s in document["sources"])
    assert "verbatim abstract text" in meta["caveat"]
    assert "not clinically reviewed" in meta["caveat"]
    assert "—" not in json.dumps(document, ensure_ascii=False)


# ---------------------------------------------------------------------------
# The candidate never reaches the boot loader.
# ---------------------------------------------------------------------------

MAIN = Path(h.__file__).resolve().parents[1] / "main.py"


def test_the_boot_loader_mirror_matches_adelia_main():
    """BOOT_GLOB and DATA_DIR describe what adelia.main loads at startup. If
    main.py changes where or what it globs, this fails and the exclusion
    below has to be re-proven against the new rule."""
    source = MAIN.read_text(encoding="utf-8")
    assert '"enrichment" / "data"' in source
    assert f'glob("{h.BOOT_GLOB}")' in source
    assert h.DATA_DIR == MAIN.parent / "enrichment" / "data"


def test_the_default_candidate_is_outside_the_boot_glob():
    assert h.DEFAULT_OUT.parent.resolve() != h.DATA_DIR.resolve()
    assert not fnmatch.fnmatch(h.DEFAULT_OUT.name, h.BOOT_GLOB)
    booted = {p.resolve() for p in h.DATA_DIR.glob(h.BOOT_GLOB)}
    assert h.DEFAULT_OUT.resolve() not in booted
    assert not h.DEFAULT_OUT.resolve().is_relative_to(h.DATA_DIR.resolve())


def test_an_output_path_the_boot_loader_would_read_is_refused(tmp_path):
    with pytest.raises(ValueError):
        h.check_out_path(h.DATA_DIR / "evidence_europepmc.json")
    with pytest.raises(ValueError):
        h.check_out_path(h.DATA_DIR / "anything.json")
    with pytest.raises(ValueError):
        h.check_out_path(tmp_path / "evidence_europepmc.json")
    assert h.check_out_path(tmp_path / "candidate.json") == tmp_path / "candidate.json"


CANDIDATE_FILES = sorted(h.CANDIDATES_DIR.glob("*.json")) if h.CANDIDATES_DIR.exists() else []


@pytest.mark.parametrize("path", CANDIDATE_FILES, ids=[p.name for p in CANDIDATE_FILES])
def test_a_committed_candidate_file_satisfies_the_corpus_constraints(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["sources"]
    _assert_corpus_constraints(document)


# ---------------------------------------------------------------------------
# Fetching: paging, politeness and retries, with the network injected.
# ---------------------------------------------------------------------------


def _pages(*batches):
    """A fake get_json serving `batches` as cursorMark pages, recording URLs."""
    calls: list[str] = []

    def get_json(url: str) -> dict:
        calls.append(url)
        index = len(calls) - 1
        results = batches[index] if index < len(batches) else []
        cursor = f"c{index + 1}" if index + 1 < len(batches) else f"c{index}"
        return {"hitCount": sum(len(b) for b in batches), "nextCursorMark": cursor,
                "resultList": {"result": results}}

    return get_json, calls


def test_records_are_paged_with_cursor_mark_until_the_cursor_stops_moving():
    get_json, calls = _pages([_rec(id="1"), _rec(id="2")], [_rec(id="3")])
    records = list(h.iter_records("q", max_records=100, get_json=get_json, page_size=2))
    assert [r["id"] for r in records] == ["1", "2", "3"]
    assert "cursorMark=%2A" in calls[0] and "cursorMark=c1" in calls[1]
    assert all("resultType=core" in c and "format=json" in c for c in calls)
    assert len(calls) == 2


def test_paging_stops_at_max_records():
    get_json, calls = _pages([_rec(id="1"), _rec(id="2")], [_rec(id="3"), _rec(id="4")])
    records = list(h.iter_records("q", max_records=3, get_json=get_json, page_size=2))
    assert [r["id"] for r in records] == ["1", "2", "3"]


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_the_client_waits_between_requests_to_stay_under_five_per_second():
    clock = _Clock()
    client = h.PoliteClient(opener=lambda req, timeout: b'{"ok": 1}', clock=clock.time,
                            sleep=clock.sleep)
    assert h.MIN_INTERVAL_S >= 0.2
    for _ in range(3):
        assert client.get_json("https://example.invalid/x") == {"ok": 1}
    assert len(clock.sleeps) == 2 and all(s >= 0.2 for s in clock.sleeps)


def test_the_client_retries_transient_errors_with_backoff_and_sends_a_user_agent():
    clock = _Clock()
    seen: list = []

    def opener(request, timeout):
        seen.append(request)
        if len(seen) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        return b'{"ok": 2}'

    client = h.PoliteClient(opener=opener, clock=clock.time, sleep=clock.sleep)
    assert client.get_json("https://example.invalid/x") == {"ok": 2}
    assert len(seen) == 3
    assert clock.sleeps[:2] == list(h.RETRY_DELAYS_S[:2])
    agent = seen[0].get_header("User-agent")
    assert agent == h.USER_AGENT and "AdelIA" in agent and "@" not in agent


def test_the_client_does_not_retry_a_client_error():
    clock = _Clock()

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "bad query", {}, None)

    client = h.PoliteClient(opener=opener, clock=clock.time, sleep=clock.sleep)
    with pytest.raises(urllib.error.HTTPError):
        client.get_json("https://example.invalid/x")
    assert clock.sleeps == []


# ---------------------------------------------------------------------------
# Report and CLI.
# ---------------------------------------------------------------------------


def _document():
    records = [
        _rec(),
        _rec(id="103", doi="10.1/b", title="Colic in infants: a guideline.", pubYear="2012",
             pubTypeList={"pubType": ["Practice Guideline"]}),
        _rec(id="104", license="cc by-nc-nd"),
    ]
    return h.build_document(h.select(records, existing_titles=set()), "q", "2026-10-22")


def test_the_report_counts_topics_types_year_bands_and_drop_reasons():
    report = h.format_report(_document())
    assert "fetched 3, kept 2, dropped 1" in report
    assert "license_not_cc_by_or_cc0: 1" in report
    assert "paper: 1" in report and "guideline: 1" in report
    assert "2010-2014: 1" in report and "2020-2026: 1" in report
    assert "reflux_vomiting: 2" in report and "crying_colic: 1" in report


def test_the_cli_writes_the_candidate_and_prints_the_report(tmp_path, capsys):
    get_json, _ = _pages([_rec(), _rec(id="104", license="cc by-nc")])
    out = tmp_path / "candidate.json"
    dropped = tmp_path / "dropped.json"
    code = h.main(["--max", "10", "--out", str(out), "--report", "--dropped", str(dropped)],
                  get_json=get_json)
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    _assert_corpus_constraints(document)
    assert document["_meta"]["counts"]["kept"] == 1
    assert json.loads(dropped.read_text(encoding="utf-8"))[0]["reason"] == (
        "license_not_cc_by_or_cc0")
    assert "fetched 2, kept 1, dropped 1" in capsys.readouterr().out


def test_the_cli_refuses_the_boot_data_dir(tmp_path):
    get_json, calls = _pages([_rec()])
    with pytest.raises(SystemExit):
        h.main(["--out", str(h.DATA_DIR / "evidence_x.json")], get_json=get_json)
    assert calls == [], "refused before any request"


def test_the_client_retries_a_truncated_body():
    """Seen live on 2026-10-22: a 500-record core page broke off mid-body
    (http.client.IncompleteRead) after minutes of streaming, and the whole
    harvest died with it."""
    clock = _Clock()
    answers = [http.client.IncompleteRead(b"partial"), b'{"ok": tru', b'{"ok": 3}']

    def opener(request, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = h.PoliteClient(opener=opener, clock=clock.time, sleep=clock.sleep)
    assert client.get_json("https://example.invalid/x") == {"ok": 3}
    assert answers == []


def test_pages_are_small_enough_to_stream_reliably():
    assert h.PAGE_SIZE <= 200
