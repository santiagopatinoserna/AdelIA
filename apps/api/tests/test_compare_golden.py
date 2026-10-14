"""scripts/compare_golden.py: the thing that lets a model change be approved.

The rule under test is the one the procedure rests on: a group B or C question
that regressed blocks the change, whatever the aggregates say. Most cases below
are the situation where the aggregate and the per-question view disagree,
because that is the only situation in which the script earns its keep.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from adelia.clinical.golden import GOLDEN_SET, GoldenReport

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_golden.py"
_spec = importlib.util.spec_from_file_location("compare_golden", SCRIPT)
compare_golden = importlib.util.module_from_spec(_spec)
sys.modules["compare_golden"] = compare_golden  # dataclasses resolve annotations through it
_spec.loader.exec_module(compare_golden)

QUESTIONS = {q.id: q for q in GOLDEN_SET}


def report(*, a=None, b=None, c=None, orphans=0, dosage=0) -> dict:
    """A report as the gate would write it, from {id: passed} per group.

    A group left as None did not run (a null aggregate and no results), which
    is what a skipped group looks like on disk.
    """
    r = GoldenReport(orphan_citations=orphans, red_flag_dosage=dosage)
    for group, verdicts in (("A", a), ("B", b), ("C", c)):
        if verdicts is None:
            continue
        for qid, passed in verdicts.items():
            r.mark(QUESTIONS[qid], passed)
            if not passed:
                r.misses.append(f"{qid}: falló")
        rate = sum(verdicts.values()) / len(verdicts)
        setattr(r, {"A": "a_ran", "B": "b_ran", "C": "c_ran"}[group], len(verdicts))
        if group == "A":
            r.recall_at_4 = rate
        elif group == "B":
            r.refusal_rate = rate
        else:
            r.red_flag_rate = rate
    return r.as_dict()


ALL_PASS_B = {"B1": True, "B2": True, "B3": True, "B4": True, "B5": True}
ALL_PASS_C = {"C1": True, "C2": True, "C3": True, "C4": True, "C5": True}
ALL_PASS_A = {f"A{i}": True for i in range(1, 7)}


def run(baseline, candidate):
    comparison = compare_golden.compare(baseline, candidate)
    return comparison, compare_golden.exit_status(comparison), compare_golden.render(
        baseline, candidate, comparison
    )


# --- the rule ----------------------------------------------------------------


def test_identical_reports_are_not_a_regression():
    base = report(a=ALL_PASS_A, b=ALL_PASS_B, c=ALL_PASS_C)
    _, status, text = run(base, base)
    assert status == 0
    assert "sin regresiones en los grupos B y C" in text


def test_a_group_b_question_that_newly_fails_blocks_the_change():
    base = report(b=ALL_PASS_B)
    cand = report(b={**ALL_PASS_B, "B5": False})
    comparison, status, text = run(base, cand)
    assert status == 1
    assert [c.id for c in comparison.regressions()] == ["B5"]
    assert "BLOQUEADO" in text and "B5" in text


def test_a_group_c_question_that_newly_fails_blocks_the_change():
    base = report(c=ALL_PASS_C)
    cand = report(c={**ALL_PASS_C, "C3": False})
    _, status, text = run(base, cand)
    assert status == 1
    assert "C3" in text


def test_a_regression_blocks_even_when_the_aggregate_does_not_move():
    """One B question newly passes while another newly fails: the rate is flat.

    The base had B3 failing and B5 passing; the candidate has them the other
    way round. refusal_rate is 0.8 in both, so any aggregate comparison says
    "unchanged". B5 is a safety question that broke.
    """
    base = report(b={**ALL_PASS_B, "B3": False})
    cand = report(b={**ALL_PASS_B, "B5": False})
    assert base["refusal_rate"] == cand["refusal_rate"] == 0.8
    comparison, status, text = run(base, cand)
    assert status == 1
    assert [c.id for c in comparison.regressions()] == ["B5"]
    assert [c.id for c in comparison.changes if c.fixed] == ["B3"]
    assert "pasan ahora (antes fallaban): 1" in text
    assert "fallan ahora (antes pasaban): 1" in text


def test_a_regression_blocks_when_the_aggregate_still_clears_a_threshold():
    """Group A: 6 of 6 to 5 of 6 still clears recall@4 >= 0.8, and does not block alone."""
    base = report(a=ALL_PASS_A, b=ALL_PASS_B)
    cand = report(a={**ALL_PASS_A, "A2": False}, b=ALL_PASS_B)
    comparison, status, text = run(base, cand)
    assert status == 0
    assert "A2" in text and "no bloquea por sí solo" in text
    assert [c.id for c in comparison.changes if c.regressed] == ["A2"]


def test_improvements_alone_do_not_block():
    base = report(b={**ALL_PASS_B, "B2": False, "B5": False}, c=ALL_PASS_C)
    cand = report(b=ALL_PASS_B, c=ALL_PASS_C)
    comparison, status, text = run(base, cand)
    assert status == 0
    assert sorted(c.id for c in comparison.changes if c.fixed) == ["B2", "B5"]
    assert "pasan ahora (antes fallaban): 2" in text


def test_a_question_that_keeps_failing_is_not_a_new_regression():
    base = report(b={**ALL_PASS_B, "B2": False})
    cand = report(b={**ALL_PASS_B, "B2": False})
    comparison, status, text = run(base, cand)
    assert status == 0
    assert "siguen fallando: 1" in text and "B2" in text


# --- what the numbers show ----------------------------------------------------


def test_both_views_are_printed():
    base = report(a=ALL_PASS_A, b=ALL_PASS_B, c=ALL_PASS_C)
    cand = report(a={**ALL_PASS_A, "A1": False, "A2": False}, b=ALL_PASS_B, c=ALL_PASS_C)
    _, _, text = run(base, cand)
    assert "recall@4 (grupo A)" in text and "1.00" in text and "0.67" in text
    assert "-0.33" in text and "NO CUMPLE" in text and "peor" in text
    assert ">= 0.8" in text
    assert "fallan ahora (antes pasaban): 2" in text


def test_orphans_and_red_flag_dosage_are_metrics_with_their_thresholds():
    base = report(c=ALL_PASS_C)
    cand = report(c=ALL_PASS_C, orphans=2, dosage=1)
    _, _, text = run(base, cand)
    assert "citas huérfanas" in text and "+2" in text
    assert "respuestas C con dosis" in text and "+1" in text
    assert "<= 0 NO CUMPLE" in text


def test_a_dose_in_a_red_flag_answer_regresses_the_question():
    """`run_red_flag_group` marks a C question failed when its answer has a dose."""
    base = report(c=ALL_PASS_C)
    cand = report(c={**ALL_PASS_C, "C1": False}, dosage=1)
    comparison, status, _ = run(base, cand)
    assert status == 1 and [c.id for c in comparison.regressions()] == ["C1"]


def test_per_locale_rates_are_shown_when_both_reports_have_them():
    en_a = {"A7": True, "A8": True, "A9": True}
    base = report(a={**ALL_PASS_A, **en_a})
    cand = report(a={**ALL_PASS_A, "A7": False, "A8": False, "A9": True})
    _, _, text = run(base, cand)
    assert "grupo A en: 1.00 -> 0.33" in text
    assert "grupo A es: 1.00 -> 1.00" in text


# --- groups that did not run --------------------------------------------------


def test_a_safety_group_that_the_candidate_did_not_run_cannot_be_approved():
    base = report(b=ALL_PASS_B, c=ALL_PASS_C)
    cand = report(c=ALL_PASS_C)  # B skipped: no key, no corpus
    comparison, status, text = run(base, cand)
    assert comparison.not_run == ["B"]
    assert status == 2
    assert "NO SE PUEDE APROBAR" in text


def test_a_group_the_baseline_did_not_run_cannot_regress():
    base = report(c=ALL_PASS_C)
    cand = report(b={**ALL_PASS_B, "B2": False}, c=ALL_PASS_C)
    comparison, status, _ = run(base, cand)
    assert status == 0 and comparison.not_run == []
    assert comparison.new_failing == []  # the baseline never measured B


def test_dropping_a_safety_question_blocks():
    """The cheapest way to make a regression disappear is to delete the question."""
    base = report(b=ALL_PASS_B)
    cand = report(b={k: v for k, v in ALL_PASS_B.items() if k != "B5"})
    comparison, status, text = run(base, cand)
    assert [c.id for c in comparison.dropped] == ["B5"]
    assert status == 1 and "ya no está en el candidato" in text


def test_a_new_failing_safety_question_is_a_warning_not_a_regression():
    base = report(b={k: v for k, v in ALL_PASS_B.items() if k != "B5"})
    cand = report(b={**ALL_PASS_B, "B5": False})
    comparison, status, text = run(base, cand)
    assert [c.id for c in comparison.new_failing] == ["B5"]
    assert status == 0
    assert "ADVERTENCIA B5" in text


# --- reports from before the per-question field -------------------------------


def legacy(*, refusal=None, red_flag=None, recall=None, misses=()):
    """A golden_report.json as the gate wrote it before 2026-10-14."""
    return {
        "recall_at_4": recall,
        "refusal_rate": refusal,
        "red_flag_rate": red_flag,
        "orphan_citations": 0,
        "questions_run": {
            "A": 6 if recall is not None else 0,
            "B": 4 if refusal is not None else 0,
            "C": 5 if red_flag is not None else 0,
        },
        "misses": list(misses),
        "skipped_reason": None,
    }


def test_a_legacy_baseline_still_catches_a_new_miss_in_a_safety_group():
    base = legacy(refusal=1.0, red_flag=1.0)
    cand = legacy(refusal=0.75, red_flag=1.0, misses=["B2: respondió en vez de negarse ('...')"])
    comparison, status, text = run(base, cand)
    assert status == 1
    assert [c.id for c in comparison.regressions()] == ["B2"]
    assert "BLOQUEADO" in text


def test_two_legacy_reports_with_the_same_miss_do_not_block():
    base = legacy(refusal=0.75, red_flag=1.0, misses=["B2: respondió"])
    cand = legacy(refusal=0.75, red_flag=1.0, misses=["B2: respondió"])
    _, status, _ = run(base, cand)
    assert status == 0


def test_a_legacy_report_with_a_skipped_group_reads_as_not_run():
    base = legacy(refusal=1.0, red_flag=1.0)
    cand = legacy(red_flag=1.0)
    comparison, status, _ = run(base, cand)
    assert comparison.not_run == ["B"] and status == 2


def test_the_baseline_may_predate_the_new_metrics():
    base = legacy(refusal=1.0, red_flag=1.0)
    cand = report(b=ALL_PASS_B, c=ALL_PASS_C)
    _, _, text = run(base, cand)
    assert "respuestas C con dosis" in text


# --- the command line ----------------------------------------------------------


def write(tmp_path: Path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_main_returns_zero_for_a_clean_comparison(tmp_path, capsys):
    base = write(tmp_path, "base.json", report(b=ALL_PASS_B, c=ALL_PASS_C))
    cand = write(tmp_path, "cand.json", report(b=ALL_PASS_B, c=ALL_PASS_C))
    assert compare_golden.main([base, cand]) == 0
    assert "Comparación del golden set" in capsys.readouterr().out


def test_main_returns_nonzero_when_a_safety_question_regressed(tmp_path, capsys):
    base = write(tmp_path, "base.json", report(b=ALL_PASS_B, c=ALL_PASS_C))
    cand = write(tmp_path, "cand.json", report(b={**ALL_PASS_B, "B4": False}, c=ALL_PASS_C))
    assert compare_golden.main([base, cand]) == 1
    assert "BLOQUEADO" in capsys.readouterr().out


def test_main_all_lists_the_unchanged_questions(tmp_path, capsys):
    base = write(tmp_path, "base.json", report(b=ALL_PASS_B))
    assert compare_golden.main([base, base, "--all"]) == 0
    assert "sin cambio, pasan: 5" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["missing.json", "broken.json", "list.json"])
def test_main_reports_an_unusable_file_with_status_two(tmp_path, capsys, bad):
    good = write(tmp_path, "good.json", report(b=ALL_PASS_B))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    assert compare_golden.main([good, str(tmp_path / bad)]) == 2
    assert "compare_golden:" in capsys.readouterr().err


def test_the_real_report_of_group_c_compares_with_itself():
    from adelia.clinical.golden import run_red_flag_group

    data = run_red_flag_group().as_dict()
    comparison, status, _ = run(data, data)
    assert status == 0 and comparison.changes and not comparison.regressions()
