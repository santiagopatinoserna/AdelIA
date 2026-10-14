"""Display metadata of the evidence corpus (audit 1.1 follow-up, 2026-10-14).

Two promises: the canonical table turns the spellings found in production
into one string per institution and refuses a URL as a publisher, and the
loader carries a correction made in a corpus file to rows loaded BEFORE the
correction (it used to skip any title it already had, so "https://www" stayed
in production after the file was fixed).
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import text

from adelia.enrichment import evidence_loader
from adelia.enrichment.evidence_hygiene import canonical_organization, looks_like_url
from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

TEST_TITLE_PREFIX = "HYGIENE-TEST-"
NICE = "National Institute for Health and Care Excellence (NICE)"
AAP = "American Academy of Pediatrics"


@pytest.mark.parametrize(
    "spelling",
    ["NICE", "NICE Guideline NG143", "National Institute for Health and Care Excellence (NICE)"],
)
def test_nice_is_one_string(spelling):
    assert canonical_organization(spelling) == NICE


@pytest.mark.parametrize(
    "spelling",
    [
        "American Academy of Pediatrics",
        "American Academy of Pediatrics (HealthyChildren.org)",
        "American Academy of Pediatrics / Pediatrics",
        "Pediatrics (American Academy of Pediatrics, Committee on Nutrition)",
        "https://www",
    ],
)
def test_the_academy_documents_are_one_string_and_a_url_is_not_among_them(spelling):
    expected = None if spelling == "https://www" else AAP
    assert canonical_organization(spelling) == expected


def test_a_journal_is_not_the_academy():
    """A study published in Pediatrics is not a position of the Academy."""
    assert canonical_organization("Pediatrics") == "Pediatrics (American Academy of Pediatrics)"
    assert canonical_organization("Pediatrics (American Academy of Pediatrics)") != AAP


@pytest.mark.parametrize("value", ["https://www", "http://x.org", "HTTPS://WWW.NICE.ORG.UK", "www.aeped.es",
                                   "//cdn.example.org", "ftp://example.org"])
def test_urls_and_pieces_of_urls_are_recognized(value):
    assert looks_like_url(value)
    assert canonical_organization(value) is None


@pytest.mark.parametrize("value", ["mpedia.fr (Association Française de Pédiatrie Ambulatoire, AFPA)",
                                   "Assurance Maladie (ameli.fr)", "Appetite", "NASPGHAN-ESPGHAN"])
def test_a_site_named_as_publisher_is_not_a_url(value):
    assert not looks_like_url(value)
    assert canonical_organization(value) == value


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_becomes_none(value):
    assert canonical_organization(value) is None


def test_a_url_like_organization_is_reported(caplog):
    with caplog.at_level(logging.WARNING, logger="adelia.enrichment.evidence_hygiene"):
        assert canonical_organization("https://www") is None
    assert "looks like a URL" in caplog.text


async def _sweep():
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM evidence_sources WHERE title LIKE :p"), {"p": f"{TEST_TITLE_PREFIX}%"}
        )
        await session.commit()


def _corpus_file(tmp_path, title, **fields):
    source = {
        "source_type": "guideline", "title": title, "organization": "TEST",
        "publication_year": 2020, "specialties": ["pediatrics"], "language": "es",
        "chunks": ["Un fragmento de prueba."],
    }
    source.update(fields)
    path = tmp_path / "evidence_probe.json"
    path.write_text(json.dumps({"sources": [source]}), encoding="utf-8")
    return path


async def _row(title):
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text("SELECT organization, publication_year FROM evidence_sources WHERE title = :t"),
                {"t": title},
            )
        ).one()


async def _seed(title, organization, year):
    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk, EvidenceSource

    async with AsyncSessionLocal() as session:
        source = EvidenceSource(
            source_type="guideline", title=title, organization=organization,
            publication_year=year, specialties=["pediatrics"], language="es",
        )
        session.add(source)
        await session.flush()
        session.add(EvidenceChunk(source_id=source.id, content="original", chunk_index=0, language="es"))
        await session.commit()


@needs_pg
async def test_a_corrected_file_reaches_the_rows_loaded_before_the_correction(tmp_path):
    title = f"{TEST_TITLE_PREFIX}sync-{uuid4().hex[:6]}"
    await _sweep()
    try:
        await _seed(title, "https://www", None)
        path = _corpus_file(tmp_path, title, organization="NICE Guideline NG143", publication_year=2019)

        assert await evidence_loader.sync_source_metadata(path) == 1
        assert tuple(await _row(title)) == (NICE, 2019)
        # Idempotent: the second boot has nothing left to change.
        assert await evidence_loader.sync_source_metadata(path) == 0
    finally:
        await _sweep()


@needs_pg
async def test_sync_never_blanks_a_value_and_never_touches_chunks(tmp_path):
    from adelia.db import AsyncSessionLocal

    title = f"{TEST_TITLE_PREFIX}keep-{uuid4().hex[:6]}"
    await _sweep()
    try:
        await _seed(title, "Appetite", 2011)
        # The file knows neither a year nor a usable organization.
        path = _corpus_file(tmp_path, title, organization="https://www", publication_year=None)

        assert await evidence_loader.sync_source_metadata(path) == 0
        assert tuple(await _row(title)) == ("Appetite", 2011)
        async with AsyncSessionLocal() as session:
            content = (
                await session.execute(
                    text(
                        "SELECT ec.content FROM evidence_chunks ec "
                        "JOIN evidence_sources es ON es.id = ec.source_id WHERE es.title = :t"
                    ),
                    {"t": title},
                )
            ).scalars().all()
        assert content == ["original"]
    finally:
        await _sweep()


@needs_pg
async def test_a_new_source_with_a_url_as_publisher_is_stored_without_one(tmp_path, monkeypatch):
    """Rejecting the source would drop its chunks, which is what a bad file
    already did once (2026-08-26); the field alone is what is wrong."""
    title = f"{TEST_TITLE_PREFIX}new-{uuid4().hex[:6]}"

    async def _embed(texts):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(evidence_loader, "embed_with_retry", _embed)
    monkeypatch.setattr(evidence_loader, "SOURCE_PACING_S", 0)
    await _sweep()
    try:
        path = _corpus_file(tmp_path, title, organization="https://www", publication_year=None)
        assert await evidence_loader.load_evidence_file(path) == (1, 1)
        assert tuple(await _row(title)) == (None, None)
    finally:
        await _sweep()
