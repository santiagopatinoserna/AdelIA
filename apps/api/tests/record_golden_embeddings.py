"""Record one query embedding per golden question, so the set runs with no key.

    cd apps/api
    MISTRAL_API_KEY=... uv run python -m tests.record_golden_embeddings

Writes tests/fixtures/golden_query_embeddings.json. The vectors are 1024-dim
mistral-embed outputs of the question text, nothing more: no patient data, no
secrets, safe to commit. Re-record whenever a question's wording changes,
because a stale vector measures the old question.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adelia.clinical.golden import GOLDEN_SET
from adelia.config import settings
from adelia.workers.embed import embed_texts

OUT = Path(__file__).parent / "fixtures" / "golden_query_embeddings.json"


async def main() -> None:
    asked = [q for q in GOLDEN_SET if q.group in ("A", "B")]
    vectors = await embed_texts([q.question for q in asked])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "model": settings.mistral_embed_model,
                "questions": {q.id: q.question for q in asked},
                "embeddings": {q.id: v for q, v in zip(asked, vectors, strict=True)},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"recorded {len(asked)} query embeddings -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
