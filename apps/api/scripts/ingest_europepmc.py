"""Bulk-ingest real open-access medical literature into the evidence RAG.

Source: Europe PMC (indexed biomedical literature — journals, reviews,
trials, guidelines). NO blogs/forums/commercial content. Each article's
abstract (a peer-reviewed summary, freely available for indexing) becomes one
evidence chunk with full attribution (title, journal, year, DOI/PMC URL,
language). Quality filters drop off-topic and empty records.

Idempotent by source title — safe to re-run / extend.

Usage:
  uv run python scripts/ingest_europepmc.py "<topic-slug>" "<europepmc-query>" [max]
Example (pediatric gastroesophageal reflux, all languages):
  uv run python scripts/ingest_europepmc.py reflux-peds \
    'TITLE:reflux AND TITLE:infant AND OPEN_ACCESS:Y'  600
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from adelia.db import AsyncSessionLocal
from adelia.models import EvidenceChunk, EvidenceSource
from adelia.workers.embed import embed_texts
from sqlalchemy import select

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# "reflux"/"regurgitation" are ambiguous: they also mean urological (vesico-
# ureteral) reflux and CARDIAC valve regurgitation. Drop those off-topic hits.
_TITLE_EXCLUDE = (
    # urological
    "vesicoureteral", "vesicoureteric", "vesico-ureteral", "vesico ureteric", "urosonography",
    "voiding", "urinary reflux", "bladder",
    # cardiac valve regurgitation (NOT gastroesophageal reflux)
    "aortic", "tricuspid", "mitral", "valvular", "valvuloplasty",
    "coronary", "atrioventricular", "echocardiogra", "carditis",
    "ventricular septal", "atrial septal", "hepatojugular", "velopharyngeal",
)
# These reflux-specific phrases must NOT be excluded even if a stop-word matches.
_TITLE_KEEP = ("gastroesophageal", "gastro-oesophageal", "gastro esophageal", "flap valve")
_MIN_ABSTRACT = 120  # chars — skip stubs


def _quality_ok(rec: dict) -> bool:
    title = (rec.get("title") or "").lower()
    if not any(keep in title for keep in _TITLE_KEEP) and any(bad in title for bad in _TITLE_EXCLUDE):
        return False
    abstract = rec.get("abstractText") or ""
    if len(abstract) < _MIN_ABSTRACT:
        return False
    if not rec.get("pubYear"):
        return False
    return True


def _fetch_all(query: str, max_records: int) -> list[dict]:
    out: list[dict] = []
    cursor = "*"
    with httpx.Client(timeout=60) as c:
        while len(out) < max_records:
            params = {
                "query": query, "format": "json", "pageSize": 100,
                "resultType": "core", "cursorMark": cursor, "sort": "P_PDATE_D desc",
            }
            d = c.get(BASE, params=params).json()
            results = d.get("resultList", {}).get("result", [])
            if not results:
                break
            out.extend(results)
            nxt = d.get("nextCursorMark")
            if not nxt or nxt == cursor:
                break
            cursor = nxt
    return out[:max_records]


def _source_url(rec: dict) -> str:
    if rec.get("doi"):
        return f"https://doi.org/{rec['doi']}"
    if rec.get("pmcid"):
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{rec['pmcid']}/"
    if rec.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/"
    return "https://europepmc.org"


def _chunk_text(rec: dict) -> str:
    # Self-contained chunk: header + abstract, so retrieval has context.
    return (
        f"[{rec.get('title','').strip()} — {rec.get('journalTitle','') or 'journal'} "
        f"{rec.get('pubYear','')}] {rec.get('abstractText','').strip()}"
    )


async def main(topic: str, query: str, max_records: int) -> None:
    print(f"▶ Europe PMC query: {query}\n  topic={topic} max={max_records}")
    records = _fetch_all(query, max_records)
    kept = [r for r in records if _quality_ok(r)]
    print(f"  fetched {len(records)}, passed quality filter {len(kept)}")

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(EvidenceSource.title))
        existing_titles = {row[0] for row in existing.all()}

        new = [r for r in kept if r.get("title") and r["title"] not in existing_titles]
        print(f"  new (not already in RAG): {len(new)}")
        if not new:
            print("  nothing to add.")
            return

        added_sources = 0
        added_chunks = 0
        # Embed in batches; one source + one chunk (abstract) per article.
        for start in range(0, len(new), 100):
            batch = new[start : start + 100]
            texts = [_chunk_text(r) for r in batch]
            embeddings = await embed_texts(texts)
            for rec, text, emb in zip(batch, texts, embeddings, strict=True):
                lang = (rec.get("language") or "eng")[:8]
                source = EvidenceSource(
                    source_type="paper",
                    title=rec["title"][:512],
                    organization=(rec.get("journalTitle") or "")[:128] or None,
                    publication_year=int(rec["pubYear"]) if str(rec.get("pubYear","")).isdigit() else None,
                    url=_source_url(rec)[:1024],
                    specialties=["pediatrics", "gastroenterology", "general_medicine"],
                    license="open_access_abstract",
                    language=lang,
                )
                session.add(source)
                await session.flush()
                session.add(EvidenceChunk(
                    source_id=source.id, content=text, chunk_index=0,
                    chunk_metadata={"topic": topic, "pmcid": rec.get("pmcid"), "doi": rec.get("doi")},
                    embedding=emb,
                ))
                added_sources += 1
                added_chunks += 1
            print(f"  …ingested {added_sources}/{len(new)}")
        await session.commit()
        print(f"✓ DONE — +{added_sources} sources, +{added_chunks} chunks for '{topic}'")


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "reflux-peds"
    query = sys.argv[2] if len(sys.argv) > 2 else (
        '(TITLE:"gastroesophageal reflux" OR TITLE:"gastro-oesophageal reflux" '
        'OR TITLE:GERD OR TITLE:GORD OR TITLE:regurgitation OR TITLE:reflux) '
        'AND (TITLE:infant OR TITLE:infants OR TITLE:pediatric OR TITLE:paediatric '
        'OR TITLE:child OR TITLE:children OR TITLE:neonatal OR TITLE:neonate '
        'OR TITLE:newborn OR TITLE:baby OR TITLE:babies) AND OPEN_ACCESS:Y'
    )
    max_records = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    asyncio.run(main(topic, query, max_records))
