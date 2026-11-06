"""Record one query embedding per golden question, so the set runs with no key.

    cd apps/api
    MISTRAL_API_KEY=... uv run python -m tests.record_golden_embeddings
    uv run python -m tests.record_golden_embeddings --merge candidate_vectors.json  # no key

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

The live recording covers the gate (GOLDEN_SET) and the candidates waiting to
join it (golden.CANDIDATES), so a promotion never needs a key.

`--merge FILE` adds the vectors that scripts/preview_golden_candidates.py
`--record` wrote in production, for the ids the fixture does not have yet. It
needs no key and changes no existing entry: a full re-record re-translates
every French and English question, and a new translation is a new
measurement of a question that did not change. It refuses another embedding
model, a vector that is not 1024-dim, an id that is not a golden question,
and a wording that differs from the question's current one; a French or
English question recorded without its Spanish text is left out by name
(2026-11-06, docs/GOLDEN_GATE_DESPLIEGUE.md).

The recording replaces the embedding call and the translation and nothing else.
Generation still needs a key as soon as retrieval returns anything (see
docs/APROBAR_CAMBIO_DE_MODELO.md).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from pathlib import Path

from adelia.clinical.golden import CANDIDATES, GOLDEN_SET, GoldenQuestion

OUT = Path(__file__).parent / "fixtures" / "golden_query_embeddings.json"
#: The embedding columns are Vector(1024) (workers/embed.py).
DIMENSION = 1024
_SECTIONS = ("questions", "embeddings", "corpus_queries", "corpus_embeddings")


class MergeError(ValueError):
    """A recorded vector the fixture cannot take as it is."""


def asked_questions() -> list[GoldenQuestion]:
    """Every question that is embedded: groups A and B of the gate and of the candidates."""
    return [q for q in (*GOLDEN_SET, *CANDIDATES) if q.group in ("A", "B")]


def _write(data: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def merge(fixture: dict, recorded: dict) -> tuple[dict, list[str], list[str]]:
    """`fixture` plus the ids of `recorded` it lacks; the ids added; the ids left out.

    Neither argument is modified. Raises MergeError, adding nothing, on any
    vector it cannot vouch for (see the module docstring). A French or English
    question recorded without its Spanish corpus text (the translation fell
    back to her words, which the recorder does not keep either) is left out by
    name instead: the gate then skips naming it until it is measured again.
    """
    if fixture.get("model") and recorded.get("model") != fixture["model"]:
        raise MergeError(
            f"recorded with model {recorded.get('model')!r}, the fixture holds "
            f"{fixture['model']!r}: vectors of two models are not comparable"
        )
    known = {q.id: q for q in asked_questions()}
    have = fixture.get("questions") or {}
    merged = copy.deepcopy(fixture)
    merged.setdefault("model", recorded.get("model"))
    for section in _SECTIONS:
        merged.setdefault(section, {})
    added: list[str] = []
    skipped: list[str] = []
    for qid, text in (recorded.get("questions") or {}).items():
        q = known.get(qid)
        if q is None:
            raise MergeError(f"{qid} is not a group A or B question of the gate or the candidates")
        if text != q.question:
            raise MergeError(f"{qid} was embedded with another wording; re-record it")
        if qid in have:
            if have[qid] != text:
                raise MergeError(f"{qid} has another wording in the fixture; re-record it")
            continue
        vectors = [recorded["embeddings"].get(qid)]
        corpus_text = (recorded.get("corpus_queries") or {}).get(qid)
        corpus_vector = (recorded.get("corpus_embeddings") or {}).get(qid)
        if (corpus_text is None) != (corpus_vector is None):
            raise MergeError(f"{qid} has a corpus text without its vector, or the reverse")
        if q.locale != "es" and corpus_text is None:
            skipped.append(qid)
            continue
        if corpus_vector is not None:
            vectors.append(corpus_vector)
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != DIMENSION:
                raise MergeError(f"{qid}: a vector that is not {DIMENSION}-dim")
        merged["questions"][qid] = text
        merged["embeddings"][qid] = vectors[0]
        if corpus_text is not None:
            merged["corpus_queries"][qid] = corpus_text
            merged["corpus_embeddings"][qid] = corpus_vector
        added.append(qid)
    return merged, added, skipped


async def main() -> None:
    from adelia.agent.corpus_query import corpus_query, needs_translation
    from adelia.config import settings
    from adelia.workers.embed import embed_texts

    asked = asked_questions()
    vectors = await embed_texts([q.question for q in asked])
    corpus_queries = {}
    for q in asked:
        if needs_translation(q.locale):
            text = await corpus_query(q.question, q.locale)
            if text != q.question:
                corpus_queries[q.id] = text
    corpus_vectors = await embed_texts(list(corpus_queries.values())) if corpus_queries else []
    _write(
        {
            "model": settings.mistral_embed_model,
            "questions": {q.id: q.question for q in asked},
            "embeddings": {q.id: v for q, v in zip(asked, vectors, strict=True)},
            "corpus_queries": corpus_queries,
            "corpus_embeddings": dict(zip(corpus_queries, corpus_vectors, strict=True)),
        }
    )
    print(f"recorded {len(asked)} query embeddings and {len(corpus_queries)} corpus "
          f"translations -> {OUT}")


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--merge", help="add the ids of this --record file the fixture lacks")
    args = parser.parse_args(argv)
    if not args.merge:
        asyncio.run(main())
        return 0
    fixture = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    recorded = json.loads(Path(args.merge).read_text(encoding="utf-8"))
    try:
        merged, added, skipped = merge(fixture, recorded)
    except MergeError as exc:
        print(f"not merged: {exc}", file=sys.stderr)
        return 1
    _write(merged)
    print(f"merged {len(added)} new ids into {OUT}: {', '.join(added) or 'none'}")
    if skipped:
        print(f"left out, no Spanish corpus text recorded (measure again): {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
