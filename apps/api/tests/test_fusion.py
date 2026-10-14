"""Reciprocal Rank Fusion: pure properties, no database, always runs.

RRF is the one piece of hybrid retrieval that decides ORDER, and it is a few
lines of arithmetic, so it is pinned down exactly: the score formula, what
beating means, tie-breaking, and the invariants that must hold for any input.
"""
from __future__ import annotations

import random

import pytest

from adelia.services.fusion import RRF_K, rrf


def test_default_k_is_the_papers_constant():
    assert RRF_K == 60


def test_no_rankings_or_only_empty_rankings_fuse_to_nothing():
    assert rrf([]) == []
    assert rrf([[], []]) == []


def test_a_single_ranking_keeps_its_order_and_scores_by_the_formula():
    fused = rrf([["a", "b", "c"]])
    assert [item for item, _ in fused] == ["a", "b", "c"]
    assert [score for _, score in fused] == pytest.approx([1 / 61, 1 / 62, 1 / 63])


def test_scores_add_across_lists():
    fused = dict(rrf([["a", "b"], ["b", "a"]]))
    # Both are first in one list and second in the other.
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_agreement_beats_a_single_first_place():
    """The reason to fuse at all: a chunk both retrievers like outranks one
    that only one of them put on top."""
    vector = ["only_vector", "both", "filler"]
    lexical = ["both", "only_lexical"]
    fused = [item for item, _ in rrf([vector, lexical])]
    assert fused[0] == "both"
    assert set(fused) == {"only_vector", "both", "filler", "only_lexical"}


def test_an_item_missing_from_a_list_simply_earns_nothing_from_it():
    fused = dict(rrf([["a"], ["b"]]))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 61)


def test_a_repeat_within_one_list_counts_once_at_its_best_position():
    once = dict(rrf([["a", "b"]]))
    repeated = dict(rrf([["a", "b", "a", "a"]]))
    assert repeated == once


def test_a_true_tie_goes_to_the_item_from_the_earlier_list():
    # Each is rank 1 in exactly one list: identical score, identical best rank.
    # The retriever listed first wins, so the output never depends on dict or
    # set iteration order.
    assert [i for i, _ in rrf([["a"], ["b"]])] == ["a", "b"]
    assert [i for i, _ in rrf([["b"], ["a"]])] == ["b", "a"]
    assert [i for i, _ in rrf([["a"], ["b"], ["c"]])] == ["a", "b", "c"]


def test_a_tie_is_broken_by_first_appearance_within_a_list_position():
    # b is rank 2 in list 1, a is rank 2 in list 2: equal scores, equal best
    # rank, and b was seen first because list 1 comes first.
    fused = rrf([["x", "b"], ["y", "a"]])
    scores = dict(fused)
    assert scores["a"] == pytest.approx(scores["b"])
    order = [item for item, _ in fused]
    assert order.index("b") < order.index("a")


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        rrf([["a"]], k=0)
    with pytest.raises(ValueError):
        rrf([["a"]], k=-5)


def test_smaller_k_sharpens_the_top_of_each_list():
    ranking = [["a", "b"]]
    gap_small_k = dict(rrf(ranking, k=1))
    gap_large_k = dict(rrf(ranking, k=1000))
    assert (gap_small_k["a"] - gap_small_k["b"]) > (gap_large_k["a"] - gap_large_k["b"])


def test_inputs_are_not_mutated():
    first, second = ["a", "b", "c"], ["c", "a"]
    rrf([first, second])
    assert first == ["a", "b", "c"]
    assert second == ["c", "a"]


def test_invariants_hold_for_random_rankings():
    rng = random.Random(20260901)
    universe = [f"id{i}" for i in range(25)]
    for _ in range(200):
        rankings = [
            rng.sample(universe, rng.randint(0, len(universe)))
            for _ in range(rng.randint(1, 4))
        ]
        fused = rrf(rankings)
        ids = [item for item, _ in fused]
        scores = [score for _, score in fused]

        # every id seen anywhere appears exactly once
        assert len(ids) == len(set(ids))
        assert set(ids) == {item for ranking in rankings for item in ranking}
        # best first
        assert scores == sorted(scores, reverse=True)
        # an id's score is exactly the sum of its per-list contributions
        for item, score in fused:
            expected = sum(
                1 / (RRF_K + ranking.index(item) + 1) for ranking in rankings if item in ranking
            )
            assert score == pytest.approx(expected)
        # the order of the lists changes tie-breaks, never a score
        reversed_scores = dict(rrf(list(reversed(rankings))))
        for item, score in fused:
            assert reversed_scores[item] == pytest.approx(score)


def test_the_same_input_always_gives_the_same_output():
    rankings = [["a", "b", "c", "d"], ["d", "c", "b", "a"]]
    assert rrf(rankings) == rrf(rankings)
