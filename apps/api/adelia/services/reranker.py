"""Reranking seam: where a cross-encoder or an LLM judge plugs in later.

Retrieval produces a candidate pool (vector order fused with the full-text
order, see services/fusion.py) and keeps the top-k. A reranker is a second,
slower, more precise pass over that pool: it reads the question and each
candidate together and re-scores them, which a bi-encoder embedding cannot do.

Nothing here scores anything. There is deliberately NO model-backed reranker:
this environment has no API keys, and a reranker that cannot be run against
the corpus is worse than none, because it silently decides what the model is
allowed to cite about a baby with nobody having seen it do so. What exists is
the interface and the identity implementation, so that adding one later is one
class and one argument, and retrieval does not change.

Contract for an implementation of `Reranker.rerank`:
  * return candidates from the input only. It may reorder and it may drop, it
    may not invent. `rerank_items` enforces this by mapping the result back to
    the originals by `id` and ignoring any id it was not given.
  * best first. The caller keeps the first top-k of what comes back.
  * never be the thing that admits a fragment. The distance cut-offs
    (settings.evidence_max_distance, settings.patient_max_distance) have
    already been applied to the pool, and the "nothing grounded, so refuse in
    code" path in chat_orchestrator depends on that. A reranker only orders.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ScoredCandidate:
    """One retrieval candidate as a reranker sees it.

    `id` is the stable key retrieval maps the result back with. `text` is what
    the reranker reads next to the query. `score` is whatever the previous
    stage assigned (the fused RRF score); a reranker may overwrite it with its
    own. `payload` carries the original object (EvidenceMatch,
    RetrievedChunk) through untouched and is excluded from equality, so two
    candidates compare on what a reranker can actually observe.
    """

    id: str
    text: str
    score: float
    payload: Any = field(default=None, compare=False, repr=False)


class Reranker(Protocol):
    """Re-score a candidate pool against the query. Best first."""

    async def rerank(
        self, query: str, candidates: Sequence[ScoredCandidate]
    ) -> list[ScoredCandidate]: ...


class NullReranker:
    """The identity: hands the pool back in the order it was given.

    The default everywhere, so that wiring the seam changes no behaviour.
    """

    async def rerank(
        self, query: str, candidates: Sequence[ScoredCandidate]
    ) -> list[ScoredCandidate]:
        return list(candidates)


async def rerank_items(
    reranker: Reranker,
    query: str,
    items: Sequence[T],
    *,
    id_of: Callable[[T], str],
    text_of: Callable[[T], str],
    score_of: Callable[[T], float],
) -> list[T]:
    """Run `reranker` over arbitrary retrieval objects and return them reordered.

    The one call site both retrieval modules share, so that EvidenceMatch and
    RetrievedChunk are reranked by the same code and neither imports the
    other. Objects the reranker returns that were not in `items` are ignored,
    and an object returned twice appears once, at its first position, so a
    misbehaving implementation cannot add a fragment or duplicate one.
    """
    by_id = {id_of(item): item for item in items}
    candidates = [
        ScoredCandidate(id=id_of(item), text=text_of(item), score=score_of(item), payload=item)
        for item in items
    ]
    reranked = await reranker.rerank(query, candidates)

    out: list[T] = []
    emitted: set[str] = set()
    for candidate in reranked:
        if candidate.id in by_id and candidate.id not in emitted:
            emitted.add(candidate.id)
            out.append(by_id[candidate.id])
    return out
