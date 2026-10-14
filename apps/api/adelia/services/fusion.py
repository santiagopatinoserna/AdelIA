"""Reciprocal Rank Fusion: merge ranked lists that do not share a scale.

Hybrid retrieval produces two rankings of the same corpus: pgvector orders by
cosine distance (0 to 2, lower is closer) and Postgres full-text search orders
by `ts_rank_cd` (an unbounded, corpus-dependent weight, higher is closer). The
two numbers cannot be compared, added or averaged: a distance of 0.07 and a
rank of 0.07 mean opposite things, and neither scale is stable from one query
to the next.

The obvious fix is a weighted blend, `a * (1 - distance) + b * rank`, and it is
the wrong one. It needs both scores normalised to a common range first, and
every normalisation (min-max over the candidate pool, z-score, a fixed
divisor) depends on the pool it was computed from, so one extreme candidate
rescales every other. It also adds two knobs, `a` and `b`, that would have to
be tuned per corpus and re-tuned whenever the corpus or the embedding model
changes, with no honest way to do it before there is an eval harness.

RRF throws the scores away and keeps only the ranks. A document scores
`1 / (k + rank)` in every list it appears in and the contributions are summed
(Cormack, Clarke and Buettcher, SIGIR 2009). Nothing has to be normalised, a
document that is high in both lists beats one that is first in only one of
them, and the single constant `k` (60 in the paper, and what the field has
used since) only controls how quickly the contribution decays down the list.
That is the property wanted here: lexical agreement is a cross-check on the
vector order, not a second opinion with its own units.

Pure by design: ids in, ids and scores out. No database, no settings, no I/O,
so the properties below are unit-tested without Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

# The constant from the original paper. Larger k flattens the difference
# between rank 1 and rank 10; smaller k lets the top of each list dominate.
RRF_K = 60


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Fuse ranked id lists, best first, into one list of `(id, score)`.

    Args:
        rankings: one sequence of ids per retriever, each ordered best first.
            Ranks are 1-based positions in that order. An id may be missing
            from a list (it simply earns nothing from it). An id repeated
            WITHIN one list counts once, at its first (best) position: a
            retriever that returns the same chunk twice has not voted twice.
        k: damping constant, must be positive. The default is the paper's.

    Returns:
        Every id seen in any list, highest fused score first. Ties are broken
        by the best rank the id reached in any single list, then by first
        appearance across the lists in the order given, so the output is
        deterministic and the earlier retriever wins a true tie.

    An empty `rankings`, or lists that are all empty, return `[]`.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    first_seen: dict[str, int] = {}

    for ranking in rankings:
        seen_in_list: set[str] = set()
        for position, item in enumerate(ranking, start=1):
            if item in seen_in_list:
                continue
            seen_in_list.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position)
            if item not in best_rank or position < best_rank[item]:
                best_rank[item] = position
            first_seen.setdefault(item, len(first_seen))

    return sorted(
        scores.items(),
        key=lambda pair: (-pair[1], best_rank[pair[0]], first_seen[pair[0]]),
    )
