"""Compare two `golden_report.json` files: did this change make the product worse?

    cd apps/api
    uv run python scripts/compare_golden.py BASELINE.json CANDIDATE.json
    uv run python scripts/compare_golden.py BASELINE.json CANDIDATE.json --all

Until this script the report was written and asserted but never compared, so
"did swapping the model, the prompt or the retrieval settings help or hurt"
had no answer: each run only said whether it cleared the thresholds. A
change can clear every threshold and still break a question that used to
pass, and that is the case this exists for. It prints both views, because
they disagree exactly when it matters:

  * per metric: recall@4, refusal rate, red-flag rate, orphan citations and
    red-flag answers with a dose, with the threshold each is held to;
  * per question: which one newly passes, which one newly fails, and which
    metric moved by how much (per locale too, so a French regression cannot
    hide inside an aggregate that still clears the bar).

Groups B and C are the safety groups (a confident sourceless answer about a
baby; a red flag that fails to fire). A single question of either that
regressed blocks the change, whatever the aggregates say. Group A
regressions are printed and do not change the exit status on their own:
recall@4 is a statistical measure with a threshold of its own.

Exit status
    0  no group B or C question regressed
    1  at least one group B or C question regressed, or a B/C question that
       the baseline ran is missing from the candidate (deleting a safety
       question is not an approval)
    2  the comparison is not possible: unreadable file, or the candidate did
       not run a safety group that the baseline did (a skipped safety group
       is "unknown", never "no regression")

Reports written before the per-question `results` field existed still work:
the failing ids are read from `misses`, and a question counts as a
regression when the candidate misses it and the baseline ran its group
without missing it.

The baseline must come from the same set of questions as the candidate. Edit
the set in one change, record a fresh baseline, and only then change the
model: otherwise "new question" and "regression" are indistinguishable.
See docs/APROBAR_CAMBIO_DE_MODELO.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from adelia.clinical.golden import (
    ORPHAN_CITATIONS_MAX,
    RECALL_AT_4_MIN,
    RED_FLAG_DOSAGE_MAX,
    RED_FLAG_RATE_MIN,
    REFUSAL_RATE_MIN,
)

SAFETY_GROUPS = ("B", "C")

#: metric key in the report -> (label, group it belongs to, "higher"|"lower"
#: is better, threshold, kind). `kind` only picks the number format.
METRICS: tuple[tuple[str, str, str, str, float, str], ...] = (
    ("recall_at_4", "recall@4 (grupo A)", "A", "higher", RECALL_AT_4_MIN, "rate"),
    ("refusal_rate", "tasa de rechazo (grupo B)", "B", "higher", REFUSAL_RATE_MIN, "rate"),
    ("red_flag_rate", "banderas rojas (grupo C)", "C", "higher", RED_FLAG_RATE_MIN, "rate"),
    ("orphan_citations", "citas huérfanas", "-", "lower", ORPHAN_CITATIONS_MAX, "count"),
    ("red_flag_dosage", "respuestas C con dosis", "C", "lower", RED_FLAG_DOSAGE_MAX, "count"),
)
GROUP_METRIC = {"A": "recall_at_4", "B": "refusal_rate", "C": "red_flag_rate"}

_MISS_ID = re.compile(r"^([ABC]\d+):")


class CompareError(Exception):
    """The two reports cannot be compared (exit status 2)."""


@dataclass
class QuestionChange:
    id: str
    group: str
    before: str  # "pasa" | "falla" | "no estaba" | "no se ejecutó"
    after: str
    locale: str = ""

    @property
    def regressed(self) -> bool:
        return self.before == "pasa" and self.after == "falla"

    @property
    def fixed(self) -> bool:
        return self.before == "falla" and self.after == "pasa"


@dataclass
class Comparison:
    changes: list[QuestionChange] = field(default_factory=list)
    #: B/C questions the baseline ran that the candidate no longer has.
    dropped: list[QuestionChange] = field(default_factory=list)
    #: B/C questions that fail in the candidate and did not exist in the baseline.
    new_failing: list[QuestionChange] = field(default_factory=list)
    #: Groups the baseline ran and the candidate did not.
    not_run: list[str] = field(default_factory=list)

    def regressions(self, groups: tuple[str, ...] = SAFETY_GROUPS) -> list[QuestionChange]:
        return [c for c in self.changes if c.regressed and c.group in groups]

    @property
    def blocking(self) -> bool:
        return bool(self.regressions() or self.dropped)


def _group_of(qid: str) -> str:
    return qid[:1]


def _sort_key(qid: str) -> tuple[str, int]:
    digits = re.sub(r"\D", "", qid)
    return (_group_of(qid), int(digits) if digits else 0)


def _status(report: dict) -> dict[str, str]:
    """Question id -> "pasa" | "falla", for the questions this report knows about."""
    out: dict[str, str] = {}
    for qid, r in (report.get("results") or {}).items():
        if r.get("passed") is True:
            out[qid] = "pasa"
        elif r.get("passed") is False:
            out[qid] = "falla"
    for miss in report.get("misses") or []:
        m = _MISS_ID.match(str(miss))
        if m:
            out[m.group(1)] = "falla"
    return out


def _locales(report: dict) -> dict[str, str]:
    return {qid: r.get("locale", "") for qid, r in (report.get("results") or {}).items()}


def group_ran(report: dict, group: str) -> bool:
    """Whether the report measured `group` at all.

    A skipped group has a null aggregate and no results; it must read as
    "unknown", not as a pass.
    """
    if any(r.get("group") == group for r in (report.get("results") or {}).values()):
        return True
    if (report.get("questions_run") or {}).get(group):
        return True
    return report.get(GROUP_METRIC[group]) is not None


def compare(baseline: dict, candidate: dict) -> Comparison:
    result = Comparison()
    for group in SAFETY_GROUPS:
        if group_ran(baseline, group) and not group_ran(candidate, group):
            result.not_run.append(group)

    before, after = _status(baseline), _status(candidate)
    locales = {**_locales(baseline), **_locales(candidate)}
    ran_before = {g: group_ran(baseline, g) for g in "ABC"}
    ran_after = {g: group_ran(candidate, g) for g in "ABC"}
    detailed_before, detailed_after = _has_results(baseline), _has_results(candidate)

    for qid in sorted(set(before) | set(after), key=_sort_key):
        group = _group_of(qid)
        b, a = before.get(qid), after.get(qid)
        # A report without `results` only names its misses, so a question it
        # does not name passed, provided its group ran at all.
        if b is None and ran_before[group] and not detailed_before:
            b = "pasa"
        if a is None and ran_after[group] and not detailed_after:
            a = "pasa"
        change = QuestionChange(qid, group, b or "no estaba", a or "no estaba", locales.get(qid, ""))
        if b is None:
            # Only in the candidate. Failing and safety-critical is worth a
            # warning; it is not a regression, the baseline never had it.
            if a == "falla" and group in SAFETY_GROUPS and ran_before[group]:
                result.new_failing.append(change)
            continue
        if a is None:
            # Only in the baseline. Dropping a safety question is the cheapest
            # way to make a regression disappear, so it blocks.
            if group in SAFETY_GROUPS and ran_after[group]:
                result.dropped.append(change)
            continue
        result.changes.append(change)
    return result


def _has_results(report: dict) -> bool:
    return bool(report.get("results"))


def _fmt(value, kind: str) -> str:
    if value is None:
        return "no ejecutado"
    return f"{value:.2f}" if kind == "rate" else str(int(value))


def _metric_rows(baseline: dict, candidate: dict) -> list[str]:
    rows = [f"  {'métrica':32s} {'base':>13s} {'candidato':>13s} {'cambio':>9s}  umbral"]
    for key, label, _group, better, threshold, kind in METRICS:
        b, a = baseline.get(key), candidate.get(key)  # None: skipped, or the baseline predates the field
        if b is not None and a is not None:
            delta = a - b
            moved = "=" if delta == 0 else (f"{delta:+.2f}" if kind == "rate" else f"{int(delta):+d}")
            worse = (delta < 0) if better == "higher" else (delta > 0)
            mark = " peor" if worse and delta != 0 else (" mejor" if delta != 0 else "")
        else:
            moved, mark = "n/a", ""
        sign = ">=" if better == "higher" else "<="
        ok = ""
        if a is not None:
            clears = a >= threshold if better == "higher" else a <= threshold
            ok = "cumple" if clears else "NO CUMPLE"
        rows.append(
            f"  {label:32s} {_fmt(b, kind):>13s} {_fmt(a, kind):>13s} {moved:>9s}  "
            f"{sign} {threshold:g} {ok}{mark}"
        )
    return rows


def _locale_rows(baseline: dict, candidate: dict) -> list[str]:
    b_rates, a_rates = baseline.get("rates_by_locale"), candidate.get("rates_by_locale")
    if not b_rates or not a_rates:
        return []
    rows = ["", "  por idioma (informativo, ningún umbral lo lee)"]
    for group in sorted(set(b_rates) | set(a_rates)):
        for locale in sorted(set(b_rates.get(group, {})) | set(a_rates.get(group, {}))):
            b, a = b_rates.get(group, {}).get(locale), a_rates.get(group, {}).get(locale)
            if b is None or a is None:
                rows.append(f"    grupo {group} {locale}: {_fmt(b, 'rate')} -> {_fmt(a, 'rate')}")
                continue
            moved = "=" if a == b else f"{a - b:+.2f}"
            rows.append(f"    grupo {group} {locale}: {b:.2f} -> {a:.2f}  {moved}")
    return rows


def render(baseline: dict, candidate: dict, comparison: Comparison, *, show_all: bool = False) -> str:
    lines = ["Comparación del golden set", ""]
    lines += _metric_rows(baseline, candidate)
    lines += _locale_rows(baseline, candidate)

    lines += ["", "  por pregunta"]
    newly_failing = [c for c in comparison.changes if c.regressed]
    newly_passing = [c for c in comparison.changes if c.fixed]
    still_failing = [c for c in comparison.changes if c.before == "falla" and c.after == "falla"]
    for title, items in (
        ("pasan ahora (antes fallaban)", newly_passing),
        ("fallan ahora (antes pasaban)", newly_failing),
        ("siguen fallando", still_failing),
    ):
        lines.append(f"    {title}: {len(items)}")
        for c in items:
            lines.append(f"      {c.id} [{c.group}{'/' + c.locale if c.locale else ''}]")
    if show_all:
        same = [c for c in comparison.changes if c.before == c.after == "pasa"]
        lines.append(f"    sin cambio, pasan: {len(same)}  " + " ".join(c.id for c in same))
    for c in comparison.new_failing:
        lines.append(f"    ADVERTENCIA {c.id} [{c.group}] es nueva y falla (no existía en la base)")
    for c in comparison.dropped:
        lines.append(f"    BLOQUEA {c.id} [{c.group}] estaba en la base y ya no está en el candidato")

    lines.append("")
    a_regressed = [c for c in comparison.changes if c.regressed and c.group == "A"]
    if a_regressed:
        lines.append(
            "  grupo A, fallan ahora: " + ", ".join(c.id for c in a_regressed)
            + " (no bloquea por sí solo; recall@4 tiene su umbral)"
        )
    blocking = comparison.regressions()
    if comparison.not_run:
        lines.append(
            "  NO SE PUEDE APROBAR: el candidato no ejecutó el grupo "
            + ", ".join(comparison.not_run)
            + ", que la base sí ejecutó. Un grupo de seguridad sin medir no es una ausencia de regresiones."
        )
    elif blocking or comparison.dropped:
        ids = ", ".join(c.id for c in blocking + comparison.dropped)
        lines.append(
            f"  VEREDICTO: BLOQUEADO. Regresión en grupo B/C: {ids}. "
            "Ningún agregado que siga cumpliendo el umbral compensa esto."
        )
    else:
        lines.append("  VEREDICTO: sin regresiones en los grupos B y C.")
    return "\n".join(lines)


def _load(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompareError(f"no se puede leer {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompareError(f"{path} no es un golden_report.json (se esperaba un objeto JSON)")
    return data


def exit_status(comparison: Comparison) -> int:
    if comparison.not_run:
        return 2
    return 1 if comparison.blocking else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("baseline", help="golden_report.json de antes del cambio")
    parser.add_argument("candidate", help="golden_report.json de después del cambio")
    parser.add_argument("--all", action="store_true", help="lista también las preguntas sin cambio")
    args = parser.parse_args(argv)
    try:
        baseline, candidate = _load(args.baseline), _load(args.candidate)
    except CompareError as exc:
        print(f"compare_golden: {exc}", file=sys.stderr)
        return 2
    comparison = compare(baseline, candidate)
    print(render(baseline, candidate, comparison, show_all=args.all))
    return exit_status(comparison)


if __name__ == "__main__":
    raise SystemExit(main())
