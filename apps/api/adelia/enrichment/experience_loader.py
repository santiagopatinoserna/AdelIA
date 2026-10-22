"""Load the "what other mothers say" fixture as its own evidence tier.

A mother wants an action plan and to feel accompanied, and much of daily
life with a baby is not researched (Kenza, 2026-10-22). This layer is what
other parents report in PUBLIC blogs and forums, cited by URL, summarised in
our own words in `experience/*.json`. It shares the table, the embedding and
the citation card with the clinical corpus, and differs from it in exactly
the places that keep it honest:

  * `tier = 'experience'` on every row, which retrieval filters on, so the
    pediatric query never returns it and the experience query never returns
    a guideline;
  * `specialties = ['experience']`, never 'pediatrics', as a second lock
    behind the first;
  * `source_type = 'experience'`: a blog post is not a guideline.

The file shape is deliberately not the evidence one (entries, not sources;
one summary, not chunks; an author, not an organization): a reviewer reads a
page per entry and writes two or three sentences, and the format should make
pasting a chunk of a study into it feel wrong. The conversion is here, in one
place, so tests can hold it.

Usage (offline):
    cd apps/api
    uv run python -m adelia.enrichment.experience_loader [path/to/file.json]
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from adelia.enrichment.evidence_loader import load_sources, sync_source_metadata

logger = logging.getLogger(__name__)

EXPERIENCE_DIR = Path(__file__).parent / "experience"
EXPERIENCE_TIER = "experience"


def experience_entries_as_sources(data: dict) -> list[dict]:
    """Entries of an experience file in the shape evidence_loader loads.

    Refuses a file that does not declare `_meta.tier == 'experience'`: the
    tier is the whole safety property, and a file that forgot to say it is a
    file nobody reviewed under that rule.
    """
    tier = (data.get("_meta") or {}).get("tier")
    if tier != EXPERIENCE_TIER:
        raise ValueError(f"experience file must declare _meta.tier = 'experience', got {tier!r}")
    sources: list[dict] = []
    for entry in data.get("entries", []):
        sources.append({
            "tier": EXPERIENCE_TIER,
            "source_type": EXPERIENCE_TIER,
            "title": entry["title"],
            "organization": entry["author"],
            "publication_year": entry.get("year"),
            "url": entry["url"],
            "specialties": [EXPERIENCE_TIER],
            "license": "public_page_summary",
            "language": entry.get("language", "es"),
            "chunks": [entry["summary"]],
        })
    return sources


async def load_experience_file(path: Path) -> tuple[int, int]:
    """Additive, idempotent-by-title load of one experience file.

    Returns: (sources_inserted, chunks_inserted).
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    sources = experience_entries_as_sources(data)
    await sync_source_metadata(path, {"sources": sources})
    return await load_sources(sources, path.name, tier=EXPERIENCE_TIER)


async def load_experience_dir(directory: Path = EXPERIENCE_DIR) -> tuple[int, int]:
    """Every *.json in the experience directory, one bad file never skipping the rest."""
    total_sources = total_chunks = 0
    for path in sorted(directory.glob("*.json")):
        try:
            s, c = await load_experience_file(path)
        except Exception:  # noqa: BLE001 — same contract as the evidence loop in main.py
            logger.exception("experience load failed for %s", path.name)
            continue
        total_sources += s
        total_chunks += c
    return total_sources, total_chunks


def main() -> None:
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1:
        sources, chunks = asyncio.run(load_experience_file(Path(sys.argv[1])))
    else:
        sources, chunks = asyncio.run(load_experience_dir())
    print(f"Loaded {sources} new experience sources, {chunks} new chunks")


if __name__ == "__main__":
    main()
