"""Markers and cards must agree (audit 3.7)."""
from __future__ import annotations

from adelia.services.citations import markers_in, prune_and_renumber


def _cites(n):
    return [{"tag": f"ev_{i}", "title": chr(64 + i)} for i in range(1, n + 1)]


def test_uncited_sources_are_dropped():
    text, patient, evidence = prune_and_renumber("solo cito [ev_2].", [], _cites(3))
    assert text == "solo cito [ev_1]."
    assert [c["title"] for c in evidence] == ["B"]
    assert patient == []


def test_an_invented_marker_is_deleted_not_left_dangling():
    text, _, evidence = prune_and_renumber("dice [ev_9] cosas.", [], _cites(2))
    assert "[ev_9]" not in text
    assert evidence == []


def test_offsets_continue_the_turn_numbering():
    """Two tool calls in one turn used to both come back numbered from 1, so
    the second call's [ev_1] silently pointed at the first call's source."""
    text, _, evidence = prune_and_renumber(
        "segun la guia [ev_1].", [], _cites(1), evidence_offset=2
    )
    assert text == "segun la guia [ev_3]."
    assert evidence[0]["tag"] == "ev_3"


def test_both_namespaces_are_numbered_independently():
    text, patient, evidence = prune_and_renumber(
        "el dato [2] y la guia [ev_2].",
        [{"chunk_id": "a"}, {"chunk_id": "b"}],
        _cites(2),
    )
    assert text == "el dato [1] y la guia [ev_1]."
    assert patient == [{"chunk_id": "b"}]
    assert evidence[0]["title"] == "B"


def test_the_input_lists_are_not_mutated():
    original = _cites(2)
    prune_and_renumber("cito [ev_2].", [], original)
    assert original[1]["tag"] == "ev_2"


def test_markers_in_reads_both_namespaces():
    assert markers_in("a [1] b [ev_3] c [1]") == ([1], [3])


def test_text_with_no_markers_keeps_nothing():
    text, patient, evidence = prune_and_renumber("sin citas", [{"chunk_id": "a"}], _cites(2))
    assert text == "sin citas"
    assert patient == [] and evidence == []
