"""Record one query embedding per golden question, so the set runs with no key.

    cd apps/api
    MISTRAL_API_KEY=... uv run python -m tests.record_golden_embeddings

Writes tests/fixtures/golden_query_embeddings.json. The vectors are 1024-dim
mistral-embed outputs of the question text, nothing more: no patient data, no
secrets, safe to commit. Re-record whenever a question's wording changes,
because a stale vector measures the old question, and whenever a question is
added: `tests/test_rag_golden.py` skips, naming the ids, when the recording
does not cover every group A and B question.

For a French or English question it also records the Spanish text the corpus
is searched with (agent/corpus_query.py, translated by the configured provider,
so this needs that provider's key too) and that text's vector. A question whose
translation fell back to the original is not recorded there, and the test then
skips naming it: re-record when the provider answers.

The recording replaces the embedding call and the translation and nothing else.
Generation still needs a key as soon as retrieval returns anything (see
docs/APROBAR_CAMBIO_DE_MODELO.md).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adelia.agent.corpus_query import corpus_query, needs_translation
from adelia.clinical.golden import GOLDEN_SET
from adelia.config import settings
from adelia.workers.embed import embed_texts

OUT = Path(__file__).parent / "fixtures" / "golden_query_embeddings.json"


async def main() -> None:
    asked = [q for q in GOLDEN_SET if q.group in ("A", "B")]
    vectors = await embed_texts([q.question for q in asked])
    corpus_queries = {}
    for q in asked:
        if needs_translation(q.locale):
            text = await corpus_query(q.question, q.locale)
            if text != q.question:
                corpus_queries[q.id] = text
    corpus_vectors = await embed_texts(list(corpus_queries.values())) if corpus_queries else []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "model": settings.mistral_embed_model,
                "questions": {q.id: q.question for q in asked},
                "embeddings": {q.id: v for q, v in zip(asked, vectors, strict=True)},
                "corpus_queries": corpus_queries,
                "corpus_embeddings": dict(zip(corpus_queries, corpus_vectors, strict=True)),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"recorded {len(asked)} query embeddings and {len(corpus_queries)} corpus "
          f"translations -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
