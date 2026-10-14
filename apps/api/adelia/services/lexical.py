"""Shared plumbing for the full-text half of hybrid retrieval.

Both retrieval paths (the clinical evidence in enrichment/evidence_retrieval.py
and the user's own chunks in services/retrieval.py) need the same two things
before they can run a `tsvector` query: which Postgres text-search
configuration to parse the question with, and the question rewritten as a
tsquery. They live here so the two paths cannot drift apart.

Which configuration. The corpus is es/en/fr and Postgres stems and drops
stopwords per language, so a Spanish tsvector must be queried with the Spanish
configuration or "bajas" and "baja" never meet. The question's language is the
chat's `locale`, which the caller already has. A locale outside es/en/fr gets
no plan and the caller skips the lexical query altogether: the answer is then
the vector order alone, which is today's behaviour, instead of a guess in the
wrong language. A Spanish question is only matched lexically against Spanish
evidence rows (an English row's stems would not meet the Spanish ones, and
parsing the question twice would let one language's stopwords match the
other's text); crossing languages is the vector search's job.

Which tsquery. `plainto_tsquery` ANDs every term, so a natural question
("what dose of ibuprofen can I give my 8 month old with a fever") would demand
that one chunk contain all of them, and almost nothing does. Retrieval wants
the opposite, "rank by how many of these terms a chunk has", so the terms are
OR-ed. Postgres still does the language work (stemming, stopword removal) when
it parses the string below with `to_tsquery(config, ...)`; Python only splits
the question into words.

Injection: every term is a run of `\\w` characters wrapped in single quotes, so
it cannot contain a quote, a backslash or a tsquery operator, and the string
is passed to Postgres as a bound parameter, never interpolated into SQL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from adelia.config import settings

# language code -> Postgres text-search configuration. Closed on purpose: these
# names are also used as literals in the migration's generated columns, and
# they are the only ones the corpus is written in.
TS_CONFIG_BY_LANGUAGE: dict[str, str] = {
    "es": "spanish",
    "en": "english",
    "fr": "french",
}

# How many candidates each ranking contributes to the fusion. Wider than the
# top_k the caller returns, so a chunk that is third in one list and fourth in
# the other can still outrank one that is first in a single list, and so a
# reranker has something to reorder.
HYBRID_CANDIDATE_POOL = 20

# A question is a handful of words; a pasted lab report is not. Bounds the size
# of the tsquery sent to Postgres.
MAX_QUERY_TERMS = 32

_WORD = re.compile(r"\w+", re.UNICODE)


def supported_language(locale: str | None) -> str | None:
    """The es/en/fr code for a UI locale, or None if the corpus has no such language.

    Accepts "es", "es-ES", "ES" and the like: only the language subtag counts.
    """
    if not locale:
        return None
    language = re.split(r"[-_]", locale.strip().lower(), maxsplit=1)[0]
    return language if language in TS_CONFIG_BY_LANGUAGE else None


@dataclass(frozen=True)
class LexicalPlan:
    """Everything a retrieval path needs to run its full-text query."""

    language: str  # es / en / fr, matches evidence_chunks.language
    ts_config: str  # spanish / english / french, the regconfig to parse with
    tsquery: str  # OR-ed, quoted terms for to_tsquery (see or_tsquery_text)


def plan_lexical(query_text: str | None, locale: str | None) -> LexicalPlan | None:
    """Decide whether this retrieval call runs a lexical query, and with what.

    None means "vector order only, exactly as before", and it is the answer
    whenever ANY of these holds: the hybrid flag is off (the default), the
    caller gave no question text (briefings and the demo retrieve from an
    embedding alone), the locale is not es/en/fr, or the question has no
    usable term. The flag is read here, at call time, and nowhere else, so
    "flag off issues no lexical query" is a property of one function.
    """
    if not settings.retrieval_hybrid_enabled:
        return None
    if not query_text:
        return None
    language = supported_language(locale)
    if language is None:
        return None
    tsquery = or_tsquery_text(query_text)
    if tsquery is None:
        return None
    return LexicalPlan(
        language=language, ts_config=TS_CONFIG_BY_LANGUAGE[language], tsquery=tsquery
    )


def or_tsquery_text(question: str) -> str | None:
    """The question as an OR-ed, quoted tsquery string for `to_tsquery`.

    Returns None when the question has no usable term, so the caller can skip
    the lexical query instead of sending Postgres an empty one. One-character
    terms are dropped: they are stopwords or noise in all three languages and
    would match nearly every chunk.

    >>> or_tsquery_text("¿Qué dosis de Ibuprofeno?")
    "'qué' | 'dosis' | 'de' | 'ibuprofeno'"
    """
    terms: list[str] = []
    seen: set[str] = set()
    for word in _WORD.findall(question.lower()):
        if len(word) < 2 or word in seen:
            continue
        seen.add(word)
        terms.append(word)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    if not terms:
        return None
    return " | ".join(f"'{term}'" for term in terms)
