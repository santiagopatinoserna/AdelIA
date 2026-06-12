"""Load + validate the evidence-grounded reflux questionnaire.

Invariant enforced here (the 'justify every question' rule): every question
carries a non-empty `why` (clinical rationale) and `source` (which guideline
backs it). Loading fails loudly if any question is unjustified — nothing
reaches the user without a fundament.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).parent.parent / "enrichment" / "data" / "reflux_questionnaire.json"


class UnjustifiedQuestionError(ValueError):
    """Raised when a question lacks its clinical rationale or source."""


@lru_cache(maxsize=1)
def load_reflux_questionnaire() -> dict:
    data = json.loads(_FILE.read_text(encoding="utf-8"))
    _validate(data)
    return data


def _validate(data: dict) -> None:
    sections = data.get("sections", [])
    if not sections:
        raise UnjustifiedQuestionError("questionnaire has no sections")
    seen_ids: set[str] = set()
    for sec in sections:
        for q in sec.get("questions", []):
            qid = q.get("id")
            if not qid or qid in seen_ids:
                raise UnjustifiedQuestionError(f"missing/duplicate question id: {qid!r}")
            seen_ids.add(qid)
            if not (q.get("why") or "").strip():
                raise UnjustifiedQuestionError(f"question {qid!r} has no 'why' (clinical rationale)")
            if not (q.get("source") or "").strip():
                raise UnjustifiedQuestionError(f"question {qid!r} has no 'source' (evidence backing)")


def question_count() -> int:
    return sum(len(s.get("questions", [])) for s in load_reflux_questionnaire()["sections"])


def section_ids() -> list[str]:
    return [s["id"] for s in load_reflux_questionnaire()["sections"]]
