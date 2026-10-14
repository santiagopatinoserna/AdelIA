"""The reranking seam: the identity default, and the guard rails on a plug-in.

There is no model-backed reranker (no API keys, and one nobody has seen run is
worse than none), so what is tested is the contract a future one must live
inside: it may reorder and drop, and it may not add or duplicate a fragment.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from adelia.services.reranker import (
    NullReranker,
    Reranker,
    ScoredCandidate,
    rerank_items,
)


@dataclass(frozen=True)
class Item:
    key: str
    body: str
    fused: float


ITEMS = [Item("a", "alpha text", 0.03), Item("b", "beta text", 0.02), Item("c", "gamma", 0.01)]


async def _run(reranker: Reranker, items=ITEMS) -> list[Item]:
    return await rerank_items(
        reranker,
        "the question",
        items,
        id_of=lambda i: i.key,
        text_of=lambda i: i.body,
        score_of=lambda i: i.fused,
    )


async def test_null_reranker_is_the_identity():
    candidates = [ScoredCandidate("x", "text x", 0.5), ScoredCandidate("y", "text y", 0.4)]
    out = await NullReranker().rerank("q", candidates)
    assert out == candidates
    assert out is not candidates  # a new list, the caller's is not aliased


async def test_null_reranker_satisfies_the_protocol():
    reranker: Reranker = NullReranker()
    assert await reranker.rerank("q", []) == []


async def test_rerank_items_with_the_null_reranker_changes_nothing():
    assert await _run(NullReranker()) == ITEMS


async def test_candidates_carry_what_a_reranker_needs():
    seen: list[tuple[str, list[ScoredCandidate]]] = []

    class Spy:
        async def rerank(self, query, candidates):
            seen.append((query, list(candidates)))
            return list(candidates)

    await _run(Spy())
    query, candidates = seen[0]
    assert query == "the question"
    assert [(c.id, c.text, c.score) for c in candidates] == [
        ("a", "alpha text", 0.03),
        ("b", "beta text", 0.02),
        ("c", "gamma", 0.01),
    ]
    # the original object rides along untouched
    assert [c.payload for c in candidates] == ITEMS


async def test_a_reranker_can_reorder():
    class Reverse:
        async def rerank(self, query, candidates):
            return list(reversed(candidates))

    assert [i.key for i in await _run(Reverse())] == ["c", "b", "a"]


async def test_a_reranker_can_drop():
    class KeepFirst:
        async def rerank(self, query, candidates):
            return list(candidates)[:1]

    assert [i.key for i in await _run(KeepFirst())] == ["a"]


async def test_a_reranker_cannot_invent_a_fragment():
    class Inventor:
        async def rerank(self, query, candidates):
            return [ScoredCandidate("not-in-the-pool", "made up", 9.9), *candidates]

    assert [i.key for i in await _run(Inventor())] == ["a", "b", "c"]


async def test_a_reranker_cannot_duplicate_a_fragment():
    class Stutter:
        async def rerank(self, query, candidates):
            first, *rest = candidates
            return [first, first, *rest, first]

    assert [i.key for i in await _run(Stutter())] == ["a", "b", "c"]


async def test_an_empty_pool_is_a_no_op():
    class Explodes:
        async def rerank(self, query, candidates):
            assert candidates == []
            return []

    assert await _run(Explodes(), items=[]) == []


async def test_a_reranker_error_propagates():
    """Swallowing it here would hide a broken reranker behind a quietly
    unreranked answer; the retrieval callers already degrade on error."""

    class Broken:
        async def rerank(self, query, candidates):
            raise RuntimeError("judge unavailable")

    with pytest.raises(RuntimeError):
        await _run(Broken())
