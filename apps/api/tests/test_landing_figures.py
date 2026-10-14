"""No hand-written corpus figure in the message catalogs (audit 1.1, third time).

The first fix for "the landing quotes a corpus size nobody checks" corrected
the number and left it a literal in apps/web/messages/{es,en,fr}.json, so six
weeks later the page said 118 sources and 258 passages while production held
127 and 301 (2026-10-14). A corrected literal drifts again by construction.
The figure now comes from GET /clinical/corpus-stats and the catalogs keep
only the sentence around it, with ICU placeholders ({count}, {from}, {to}).

This test is what stops a third repetition: it fails when a catalog says "N
fuentes", "N guidelines", "N études" and the like, when a catalog holds a bare
number or percentage as a value, or when it spells out a span of publication
years. It reads the catalogs the web build reads, so it needs no server.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

MESSAGES = Path(__file__).resolve().parents[3] / "apps" / "web" / "messages"
LOCALES = ("es", "en", "fr")

# What a corpus figure counts, in the three languages of the catalogs. "documentos"
# is deliberately absent: "sube hasta 10 documentos" counts the mother's own
# uploads, not the corpus.
_NOUNS = (
    r"fuentes?|gu[ií]as?|estudios?|fragmentos?|referencias?|publicaciones|recomendaciones|"
    r"sources?|guidelines?|studies|passages?|fragments?|chunks?|references|publications|"
    r"recommandations?|[ée]tudes?|extraits?|guides?|passages?|r[ée]f[ée]rences?"
)
# A number that could be a corpus size. 0 and 1 are left out: they are the
# literal branches of an ICU plural ("=1 {1 fragmento}", which counts the
# pieces of ONE of the mother's documents) and no corpus has one source.
_SIZE = r"(?<![\w=#])(?!(?:0|1)(?![\d.,]))\d[\d.,]*"
# "118 guías y estudios", "118 fuentes", "Tu historia × 118 sources": a number,
# at most three words, then a corpus noun.
_NUMBER_THEN_NOUN = re.compile(rf"{_SIZE}\s+(?:[^\W\d_]+\s+){{0,3}}(?:{_NOUNS})\b", re.IGNORECASE)
# "fuentes: 118", "sources (118)": a corpus noun, a little glue, then a number.
_NOUN_THEN_NUMBER = re.compile(rf"\b(?:{_NOUNS})\b[\s:(]{{1,3}}{_SIZE}", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"^\s*[\d.,]+\s*%?\s*$")
_YEAR_SPAN = re.compile(r"\b(?:19|20)\d{2}\s*[–-]\s*(?:19|20)\d{2}\b")


def _leaves(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, f"{path}.{key}" if path else key)
    elif isinstance(value, str):
        yield path, value


def figure_problems(text: str) -> list[str]:
    """Why `text` contains a hand-written corpus figure; empty when it does not."""
    problems = []
    if _BARE_NUMBER.match(text):
        problems.append("is a bare number")
    if _NUMBER_THEN_NOUN.search(text) or _NOUN_THEN_NUMBER.search(text):
        problems.append("puts a number next to a corpus noun")
    if _YEAR_SPAN.search(text):
        problems.append("spells out a span of years")
    return problems


@pytest.mark.parametrize("locale", LOCALES)
def test_no_catalog_holds_a_hand_written_corpus_figure(locale):
    catalog = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
    found = [
        f"{locale}.json {path}: {problem}: {text[:90]!r}"
        for path, text in _leaves(catalog)
        for problem in figure_problems(text)
    ]
    assert not found, (
        "the corpus figures come from GET /clinical/corpus-stats (apps/web/lib/corpus-stats.ts), "
        "never from a catalog:\n" + "\n".join(found)
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_corpus_sentence_is_a_template_that_takes_the_figures(locale):
    """The positive half: the table cell still has somewhere to put the count,
    and it also has a sentence for when the API cannot answer."""
    home = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))["home"]
    for placeholder in ("{count", "{from}", "{to}"):
        assert placeholder in home["vsR5A"], f"{locale}: home.vsR5A lost {placeholder}"
    assert not any(c in home["vsR5AFallback"] for c in "{}0123456789")


@pytest.mark.parametrize(
    "old_text",
    [
        "118",
        "100%",
        "1980–2026",
        "118 guías y estudios (1980–2026)",
        "Tu historia × 118 fuentes",
        "118 guidelines and studies",
        "Their history × 118 sources",
        "118 recommandations et études",
        "Son histoire × 118 sources",
        "con la evidencia del corpus (118 fuentes), citada",
        "evidence from 258 passages",
        "fuentes: 127",
        "sources (127)",
    ],
)
def test_the_guard_catches_what_the_catalogs_used_to_say(old_text):
    """The strings that reached production on 2026-10-14, plus the shapes a
    next edit could take. If this fails the guard went blind, not the catalog."""
    assert figure_problems(old_text)


@pytest.mark.parametrize(
    "fine_text",
    [
        "{count, plural, one {# fuente publicada} other {# fuentes publicadas}} entre {from} y {to}",
        "Guías clínicas y estudios revisados por pares",
        "Tu historia × las fuentes",
        "Gratis 30 días",
        "Sube hasta 10 documentos",
        "21:00",
        "8€",
    ],
)
def test_the_guard_leaves_ordinary_copy_alone(fine_text):
    assert not figure_problems(fine_text)
