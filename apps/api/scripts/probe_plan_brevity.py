"""Is a plan shorter with settings.plan_brevity on, and does it keep every warning sign?

    cd apps/api            # inside the production API container
    python scripts/probe_plan_brevity.py
    python scripts/probe_plan_brevity.py --json /tmp/plan_brevity_1.json

For settings.plan_brevity (services/answer_contract.py, PLAN_BREVITY_RULE).
Measured on 29 prod plans of 2026-11-06 (~/dev/adelia-design/shots/subject-prod,
warnsigns-prod and the "on" answers of warning-signs-warnpara-{1,2}): median 365
words, up from 292 at the start of the night. "Cuándo ir al médico" is 26 % of
them and is the growth we wanted; the rest went to a two-sentence opening, loose
"Evita / No le des" paragraphs under Hoy and two-sentence bullets.

It asks the 13 questions of probe_warning_signs and one in French, through the
same demo wiring (`probe_warning_signs.answer_once`: the demo baby, its router, its
retrieval, the production model), each with plan_brevity OFF then ON, set in
memory for this process only. The other settings stay as the server has them, so
OFF is the answer production gives today. Per question it prints the words of the
whole answer and of each section, the bullets per section, the loose paragraphs,
the words of the first sentence, the bullets of more than one sentence, the doctor
bullets, where the coded refusal sits, and the doctor section of both modes side
by side, so a person can check that no sign was lost. A shrinking doctor section
is named in the summary; it is a reason to read, not proof of a loss.

Word counts are `answer.split()`, citation markers included, like
probe_warning_signs; sentence lengths leave the markers out.

Cheap on purpose: one call at a time, a pause between calls, 14 questions x 2
modes, so 28 generations per run. Read only, as probe_warning_signs: every session
is `SET TRANSACTION READ ONLY` before its first query, no spending gate is called
and nothing is persisted.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import re
import statistics
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_warning_signs as pw  # noqa: E402

from adelia.config import settings  # noqa: E402
from adelia.services.answer_contract import CONTRACTS, PLAN_HEADINGS  # noqa: E402

#: The warning-sign questions, then the French one measured in subject-prod.
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    *pw.ALL_QUESTIONS,
    ("diarrhee_fr", "fr", "Elle a la diarrhée depuis hier, que faire ?"),
)

SECTIONS = ("opening", "today", "watch", "doctor", "remember", "mothers", "other")

#: The same read-only demo answer as probe_warning_signs.
answer_once = pw.answer_once

_HEADING = re.compile(r"^\s*#{2,}\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_MARKER = re.compile(r"\s*\[(?:ev_|ex_)?\d+\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_REFUSALS = tuple(c.refusal for c in CONTRACTS.values())
_COLUMN = 60


@contextmanager
def brevity(on: bool) -> Iterator[None]:
    """plan_brevity at `on` for the block, in memory, restored whatever happens."""
    saved = settings.plan_brevity
    try:
        settings.plan_brevity = on
        yield
    finally:
        settings.plan_brevity = saved


def _section_key(title: str) -> str:
    wanted = title.strip().lower()
    for headings in PLAN_HEADINGS.values():
        for key, heading in headings.items():
            if heading.lower() == wanted:
                return key
    return "other"


def parts(answer: str) -> list[tuple[str, str, str]]:
    """(section, "bullet" | "para", text) in reading order; the opening is "opening"."""
    section, out, paragraph = "opening", [], []

    def flush():
        if paragraph:
            out.append((section, "para", " ".join(paragraph)))
            paragraph.clear()

    for line in answer.splitlines():
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        if heading:
            flush()
            section = _section_key(heading.group(1))
        elif bullet:
            flush()
            out.append((section, "bullet", bullet.group(1)))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    return out


def _sentences(text: str) -> list[str]:
    plain = _MARKER.sub("", text).replace("**", "")
    return [s for s in _SENTENCE_END.split(plain) if s.strip()]


def section_words(answer: str) -> dict[str, int]:
    words = dict.fromkeys(SECTIONS, 0)
    for section, _, text in parts(answer):
        words[section] += len(text.split())
    return words


def section_bullets(answer: str) -> dict[str, int]:
    bullets = dict.fromkeys(SECTIONS, 0)
    for section, kind, _ in parts(answer):
        bullets[section] += kind == "bullet"
    return bullets


def loose_paragraphs(answer: str) -> list[tuple[str, str]]:
    """Paragraphs that are not bullets, outside the opening and the doctor section
    (whose "Ve a urgencias si:" lines group its signs), the coded refusal aside."""
    return [
        (section, text) for section, kind, text in parts(answer)
        if kind == "para" and section not in ("opening", "doctor")
        and not any(r in text for r in _REFUSALS)
    ]


def first_sentence_words(answer: str) -> int:
    opening = " ".join(t for s, _, t in parts(answer) if s == "opening")
    sentences = _sentences(opening)
    return len(sentences[0].split()) if sentences else 0


def multi_sentence_bullets(answer: str) -> int:
    """Bullets of more than one sentence, outside the doctor section."""
    return sum(1 for s, kind, t in parts(answer)
               if kind == "bullet" and s != "doctor" and len(_sentences(t)) > 1)


def doctor_text(answer: str, locale: str) -> str:
    """The doctor section as written, lead-in lines included, up to the next heading."""
    title = PLAN_HEADINGS.get(locale, PLAN_HEADINGS["es"])["doctor"].lower()
    inside, lines = False, []
    for line in answer.splitlines():
        heading = _HEADING.match(line)
        if heading:
            inside = heading.group(1).strip().lower() == title
            continue
        if inside and line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def measure(row: pw.Row, locale: str) -> dict:
    return {
        "words": row.words,
        "section_words": section_words(row.answer),
        "section_bullets": section_bullets(row.answer),
        "loose_paragraphs": loose_paragraphs(row.answer),
        "first_sentence_words": first_sentence_words(row.answer),
        "multi_sentence_bullets": multi_sentence_bullets(row.answer),
        "doctor_bullets": len(pw.doctor_bullets(row.answer, locale)),
        "doctor_text": doctor_text(row.answer, locale),
        "refusal": pw.refusal_places(row.answer),
    }


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def run_all(questions) -> list[tuple[tuple[str, str, str], pw.Row, pw.Row]]:
    """Each question OFF then ON, one call at a time, a pause between calls."""
    rows, first = [], True
    for qid, locale, question in questions:
        pair = []
        for on in (False, True):
            if not first:
                await _pause(pw.PAUSE_SECONDS)
            first = False
            with brevity(on):
                pair.append(await answer_once(qid, locale, question))
        rows.append(((qid, locale, question), pair[0], pair[1]))
    return rows


def _wrap(text: str) -> list[str]:
    out = []
    for line in text.splitlines() or [""]:
        while len(line) > _COLUMN:
            out.append(line[:_COLUMN])
            line = "  " + line[_COLUMN:]
        out.append(line)
    return out


def print_row(q: tuple[str, str, str], off: pw.Row, on: pw.Row) -> None:
    qid, locale, question = q
    m = {"off": measure(off, locale), "on": measure(on, locale)}
    print(f"\n[{qid}] ({locale}) {question}")
    for name, row in (("off", off), ("on ", on)):
        x = m[name.strip()]
        sections = "  ".join(f"{s} {x['section_words'][s]}w/{x['section_bullets'][s]}b"
                             for s in SECTIONS if x["section_words"][s])
        print(f"  {name} kind {row.kind}  intent {row.intent}  words {x['words']}  "
              f"first sentence {x['first_sentence_words']}w  "
              f"multi-sentence bullets {x['multi_sentence_bullets']}  "
              f"loose {len(x['loose_paragraphs'])}  "
              f"refusal {'yes: ' + ' | '.join(x['refusal']) if x['refusal'] else 'no'}")
        print(f"       {sections}")
        for section, text in x["loose_paragraphs"]:
            print(f"       loose   {section}: {text:.100}")
    print(f"  doctor bullets {m['off']['doctor_bullets']} -> {m['on']['doctor_bullets']}")
    left, right = _wrap(m["off"]["doctor_text"]), _wrap(m["on"]["doctor_text"])
    print(f"  {'OFF':<{_COLUMN}} | ON")
    for a, b in itertools.zip_longest(left, right, fillvalue=""):
        print(f"  {a:<{_COLUMN}} | {b}")


def summarize(rows) -> dict:
    """Medians and totals per mode, and the questions whose doctor section shrank."""
    out: dict = {"fewer_doctor_bullets": []}
    for name, pick in (("off", 1), ("on", 2)):
        ms = [measure(r[pick], r[0][1]) for r in rows]
        out[name] = {
            "median_words": statistics.median(m["words"] for m in ms) if ms else 0,
            "median_section_words": {
                s: statistics.median(m["section_words"][s] for m in ms) if ms else 0
                for s in SECTIONS
            },
            "doctor_bullets": sum(m["doctor_bullets"] for m in ms),
            "refusals_inside": sum(1 for r, m in zip(rows, ms)
                                   if r[pick].kind == "answer" and m["refusal"]),
            "loose_paragraphs": sum(len(m["loose_paragraphs"]) for m in ms),
            "multi_sentence_bullets": sum(m["multi_sentence_bullets"] for m in ms),
        }
    for q, off, on in rows:
        if len(pw.doctor_bullets(on.answer, q[1])) < len(pw.doctor_bullets(off.answer, q[1])):
            out["fewer_doctor_bullets"].append(q[0])
    return out


async def main_async(args) -> int:
    rows = await run_all(QUESTIONS)
    for q, off, on in rows:
        print_row(q, off, on)
    summary = summarize(rows)
    print("\n== summary (plan_brevity off -> on; other settings as the server has them: "
          f"warning_signs_retrieval {settings.warning_signs_retrieval}, "
          f"no_unasked_refusals {settings.no_unasked_refusals})")
    for name in ("off", "on"):
        s = summary[name]
        sections = "  ".join(f"{k} {v}" for k, v in s["median_section_words"].items() if v)
        print(f"  {name:<3} median words {s['median_words']}  doctor bullets "
              f"{s['doctor_bullets']}  refusal inside {s['refusals_inside']}/{len(rows)}  "
              f"loose {s['loose_paragraphs']}  multi-sentence bullets "
              f"{s['multi_sentence_bullets']}")
        print(f"      median words per section: {sections}")
    print(f"  fewer doctor bullets with it on (read those side by side): "
          f"{', '.join(summary['fewer_doctor_bullets']) or 'none'}")
    if args.json:
        payload = {
            "summary": summary,
            "answers": [
                {"id": q[0], "locale": q[1], "question": q[2],
                 **{name: asdict(r) | measure(r, q[1]) for name, r in (("off", off), ("on", on))}}
                for q, off, on in rows
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", help="also write every answer and its measures to this file")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
