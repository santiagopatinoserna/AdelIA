"""Lenient ground-truth matching: did the extraction capture the finding?"""

from __future__ import annotations

from collections.abc import Iterable

from tests.clinical_corpus.cases import Finding


def _entity_text(entity) -> str:
    name = getattr(entity, "name", "") or ""
    quote = getattr(entity, "raw_quote", "") or ""
    return f"{name}\n{quote}".lower()


def finding_satisfied(finding: Finding, entities: Iterable) -> bool:
    for e in entities:
        if getattr(e, "entity_type", None) != finding.entity_type:
            continue
        text = _entity_text(e)
        if any(token.lower() in text for token in finding.name_contains):
            return True
    return False


def missing_findings(findings: Iterable[Finding], entities: list) -> list[Finding]:
    return [f for f in findings if not finding_satisfied(f, entities)]
