"""Run the routing evaluation set through `route()` and print a confusion matrix.

    cd apps/api
    uv run python scripts/eval_routing.py                 # es, rules + model
    uv run python scripts/eval_routing.py --locale en     # another set
    uv run python scripts/eval_routing.py --rules-only    # no key, no network
    uv run python scripts/eval_routing.py --json out.json # also write the per-item results

Read-only: it never touches the database and writes nothing unless --json is
given. The model layer is reached only when the rules abstain, so with a key
this measures what production would do; without one the model falls back to
`plan` (via=fallback) and the matrix shows it.

Red-flag items are not routed: they are passed to `clinical/red_flags.detect`
and counted as caught or missed, because on every surface the guard runs
first and `route` never sees them.

Exit status: 0 when the accuracy over routed items is at least the threshold
(default 0.90, the figure in docs/specs/AGENT_GRAPH.md) and every red flag
was caught; 1 otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from adelia.agent import route as r
from adelia.clinical import red_flags
from adelia.enrichment.profile_service import ProfileFacts

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
LABELS = (*r.INTENTS,)


def load(locale: str) -> list[dict]:
    doc = json.loads((DATA / f"routing_{locale}.json").read_text(encoding="utf-8"))
    default = doc.get("default", {})
    return [{**default, **item} for item in doc["items"]]


def facts_for(item: dict) -> ProfileFacts | None:
    age = item.get("age_months")
    if age is None and not item.get("has_account"):
        return None
    return ProfileFacts(None, None, None, None, age)


async def run(items: list[dict], *, locale: str, rules_only: bool, timeout_s: float) -> list[dict]:
    out: list[dict] = []
    for item in items:
        text, expected = item["text"], item["intent"]
        if expected == "red_flag":
            flag = red_flags.detect(text, locale=locale, age_months=item.get("age_months"))
            out.append({"text": text, "expected": expected,
                        "got": "red_flag" if flag else "MISSED", "via": "guard"})
            continue
        kwargs = dict(locale=locale, has_account=item["has_account"], facts=facts_for(item))
        if rules_only:
            d = r.route_by_rules(text, **kwargs)
            got, via = (d.intent, d.via) if d else ("(abstain)", "none")
        else:
            d = await r.route(text, timeout_s=timeout_s, **kwargs)
            got, via = d.intent, d.via
        out.append({"text": text, "expected": expected, "got": got, "via": via})
    return out


def print_matrix(results: list[dict]) -> None:
    routed = [x for x in results if x["expected"] != "red_flag"]
    cols = [*LABELS, "(abstain)"]
    matrix: dict[str, Counter] = defaultdict(Counter)
    for x in routed:
        matrix[x["expected"]][x["got"]] += 1
    width = max(len(c) for c in cols) + 1
    print("expected \\ got".ljust(14) + "".join(c.rjust(width) for c in cols))
    for row in LABELS:
        print(row.ljust(14) + "".join(str(matrix[row][c] or ".").rjust(width) for c in cols))
    print()
    via = Counter(x["via"] for x in routed)
    print("via:", ", ".join(f"{k}={v}" for k, v in sorted(via.items())))
    hits = sum(1 for x in routed if x["got"] == x["expected"])
    print(f"accuracy: {hits}/{len(routed)} = {hits / len(routed):.1%}")
    flags = [x for x in results if x["expected"] == "red_flag"]
    caught = sum(1 for x in flags if x["got"] == "red_flag")
    print(f"red flags caught by the guard: {caught}/{len(flags)}")
    wrong = [x for x in routed if x["got"] != x["expected"]]
    if wrong:
        print("\nmisses:")
        for x in wrong:
            print(f"  [{x['expected']:>8} -> {x['got']:<9} via {x['via']}] {x['text']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--locale", default="es", choices=["es", "en", "fr"])
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--timeout", type=float, default=20.0, help="per-message model deadline")
    ap.add_argument("--threshold", type=float, default=0.90)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    items = load(args.locale)
    results = asyncio.run(
        run(items, locale=args.locale, rules_only=args.rules_only, timeout_s=args.timeout)
    )
    print_matrix(results)
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwritten: {args.json}")

    routed = [x for x in results if x["expected"] != "red_flag"]
    accuracy = sum(1 for x in routed if x["got"] == x["expected"]) / len(routed)
    all_flags = all(x["got"] == "red_flag" for x in results if x["expected"] == "red_flag")
    return 0 if accuracy >= args.threshold and all_flags else 1


if __name__ == "__main__":
    sys.exit(main())
