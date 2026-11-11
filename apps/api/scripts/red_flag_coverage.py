"""Measure the red-flag guard against the coverage set, per flag.

    python scripts/red_flag_coverage.py                 # this tree
    python scripts/red_flag_coverage.py --ref origin/main

`--ref` loads adelia/clinical/red_flags.py as it is at that git ref, so the
same phrases measure the guard before and after a change. Two numbers per flag:
"fires" (any referral, which is the safety question: the frame and the 112 are
the same for every flag) and "right flag" (the reason line matches what she
told). Look-alikes count the ones that fired. A flag the old guard did not have
can still "fire" under another code; it never counts as right.

Also checks the questions that must never fire: golden groups A and B and the
battery turns that do not expect a referral.

Pure code, no model, no database.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from tests.red_flag_phrasings import LOOKALIKES, POSITIVES  # noqa: E402

MODULE = "apps/api/adelia/clinical/red_flags.py"


def _load(ref: str | None):
    if ref is None:
        from adelia.clinical import red_flags

        return red_flags
    source = subprocess.run(
        ["git", "show", f"{ref}:{MODULE}"], check=True, capture_output=True, text=True, cwd=API
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(source)
    spec = importlib.util.spec_from_file_location("red_flags_at_ref", fh.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def _battery_quiet_turns() -> list[tuple[str, str, int | None]]:
    """Battery turns that expect anything but a referral, with their profile age."""
    out = []
    for name in ("conversation_scenarios.json", "conversation_regressions.json"):
        data = json.loads((API / "scripts" / name).read_text(encoding="utf-8"))
        scenarios = data if isinstance(data, list) else data.get("scenarios", [])
        for s in scenarios:
            profile = s.get("profile") if isinstance(s.get("profile"), dict) else {}
            age = s.get("age_months", profile.get("age_months"))
            referred = False
            for t in s.get("turns", []):
                kind = t.get("expect", {}).get("kind")
                referred = referred or kind == "red_flag"
                if "say" in t and kind != "red_flag" and not referred:
                    out.append((s.get("locale", "es"), t["say"], age))
    return out


def measure(ref: str | None) -> dict:
    rf = _load(ref)
    fires: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # total, fired, right
    misses = []
    for code, locale, sentence, age, _origin in POSITIVES:
        flag = rf.detect(sentence, locale=locale, age_months=age)
        row = fires[code]
        row[0] += 1
        if flag is not None:
            row[1] += 1
        if flag is not None and flag.code == code:
            row[2] += 1
        else:
            misses.append((code, locale, sentence, flag.code if flag else None))
    false_alarms = [
        (loc, s, rf.detect(s, locale=loc, age_months=a).code)
        for loc, s, a, _w in LOOKALIKES
        if rf.detect(s, locale=loc, age_months=a) is not None
    ]
    from adelia.clinical.golden import questions

    golden = [
        (q.id, rf.detect(q.question, locale=q.locale, age_months=q.age_months).code)
        for g in ("A", "B")
        for q in questions(g)
        if rf.detect(q.question, locale=q.locale, age_months=q.age_months) is not None
    ]
    battery = [
        (s, rf.detect(s, locale=loc, age_months=a).code)
        for loc, s, a in _battery_quiet_turns()
        if rf.detect(s, locale=loc, age_months=a) is not None
    ]
    return {
        "fires": dict(fires), "misses": misses, "false_alarms": false_alarms,
        "golden": golden, "battery": battery,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", help="git ref to measure instead of this tree")
    parser.add_argument("--misses", action="store_true", help="list every miss")
    args = parser.parse_args()
    result = measure(args.ref)
    print("| flag | phrases | fires | right flag |\n|---|---|---|---|")
    total = [0, 0, 0]
    for code in sorted(result["fires"]):
        n, fired, right = result["fires"][code]
        total = [total[0] + n, total[1] + fired, total[2] + right]
        print(f"| {code} | {n} | {fired} | {right} |")
    print(f"| **total** | {total[0]} | {total[1]} | {total[2]} |")
    print(f"\nlook-alikes fired: {len(result['false_alarms'])} of {len(LOOKALIKES)}")
    for loc, s, code in result["false_alarms"]:
        print(f"  [{loc}] {s!r} -> {code}")
    print(f"golden A/B fired: {len(result['golden'])} {result['golden']}")
    print(f"battery quiet turns fired: {len(result['battery'])} {result['battery']}")
    if args.misses:
        print("\nmisses:")
        for code, loc, s, got in result["misses"]:
            print(f"  {code} [{loc}] {s!r} -> {got}")


if __name__ == "__main__":
    main()
