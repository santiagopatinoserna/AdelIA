"""Marker bookkeeping shared by the answering surfaces (audit 3.7).

A citation is only worth anything if the marker in the prose and the card
under it point at the same thing. Two ways that breaks:

* **Orphan citations**: the payload carries four sources, the answer cites
  two. The other two render as cards nobody can trace back to a sentence,
  which is the exact shape of "looks sourced, is not" (risk 1 of the audit).
* **Colliding numbering**: the agent can call `buscar_en_expediente` more
  than once in a turn (MAX_STEPS is 5). Each call comes back numbered from
  [ev_1], so merging two of them silently makes the second call's [ev_1]
  point at the first call's source.

`prune_and_renumber` fixes both in one pass: it keeps only the citations the
text actually uses, renumbers them contiguously from an offset, and rewrites
the markers to match. What comes out satisfies, by construction, "one marker
per citation and one citation per marker".
"""
from __future__ import annotations

import re
from copy import deepcopy

#: `[3]` is a patient chunk, `[ev_3]` a clinical guideline. Two namespaces,
#: numbered independently, exactly as answer_contract asks the model to write
#: them.
MARKER = re.compile(r"\[(ev_)?(\d+)\]")


def markers_in(text: str) -> tuple[list[int], list[int]]:
    """(patient indices, evidence indices) used by `text`, sorted, deduped."""
    patient: set[int] = set()
    evidence: set[int] = set()
    for m in MARKER.finditer(text or ""):
        (evidence if m.group(1) else patient).add(int(m.group(2)))
    return sorted(patient), sorted(evidence)


def prune_and_renumber(
    text: str,
    citations: list[dict],
    evidence_citations: list[dict],
    *,
    citation_offset: int = 0,
    evidence_offset: int = 0,
) -> tuple[str, list[dict], list[dict]]:
    """Keep the cited sources, drop the rest, renumber text and payload alike.

    `*_offset` is how many citations of that namespace the turn already
    carries, so a second tool call continues the numbering instead of
    restarting it.

    A marker pointing past the end of its list (the model invented [ev_9])
    is deleted from the text rather than left dangling: an invented citation
    is worse than none.
    """
    used_patient, used_evidence = markers_in(text)
    valid_patient = [i for i in used_patient if 1 <= i <= len(citations)]
    valid_evidence = [i for i in used_evidence if 1 <= i <= len(evidence_citations)]

    map_patient = {old: citation_offset + n for n, old in enumerate(valid_patient, start=1)}
    map_evidence = {old: evidence_offset + n for n, old in enumerate(valid_evidence, start=1)}

    kept_patient = [deepcopy(citations[i - 1]) for i in valid_patient]
    kept_evidence = []
    for i in valid_evidence:
        cite = deepcopy(evidence_citations[i - 1])
        cite["tag"] = f"ev_{map_evidence[i]}"
        kept_evidence.append(cite)

    def _rewrite(match: re.Match[str]) -> str:
        old = int(match.group(2))
        if match.group(1):
            new = map_evidence.get(old)
            return f"[ev_{new}]" if new else ""
        new = map_patient.get(old)
        return f"[{new}]" if new else ""

    return MARKER.sub(_rewrite, text or ""), kept_patient, kept_evidence
