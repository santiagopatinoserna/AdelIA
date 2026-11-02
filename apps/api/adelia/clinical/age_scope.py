"""A child of 3 years or more is outside AdelIA's scope, and code says so.

AdelIA is built for babies of 0 to 24 months, and so is its corpus. Measured
in production on 2026-10-27 with the development corpus as a candidate,
golden B12 ("How many hours of sleep does my 7-year-old need") reached a
sleep fragment under the 0.19 cut: the words of the question are the
corpus's, its child is not. Retrieval cannot tell a 7-year-old from a
7-month-old, the model would cite the infant guideline, and the answer would
read as sourced. So the age goes to code, like the red flags, and the graph's
guard refuses before the spending gate, the router or any embedding
(docs/HANDOFF_CLAUDE_CODE.md, 4.1).

What counts, narrow on purpose:

* An age in years tied to a child by its grammar, in digits or words, from 3
  to 17: "de 7 años", "tiene 4 años", "my 7-year-old", "6 years old",
  "aged 5", "de 10 ans", "il a 4 ans". A range counts by its lower end, so
  "de 1 a 3 años" still holds the toddler. Adults ("mi marido de 40 años",
  "tengo 35 años") and durations ("hace 3 años", "il y a 3 ans") do not.
* A baby anywhere else in the message cancels it: an age in months, weeks or
  days (`red_flags.age_months_in`), one or two years, or a word for a baby or
  a sibling. "Mi hijo de 4 años tiene celos del bebé" is a question about the
  baby's family, which the corpus answers. The word right in front of the
  age is the older child itself ("mi bebé de 3 años") and cancels nothing.

The profile's age is not read: a baby's profile does not make a question
about her 7-year-old brother answerable, and a missing profile must not make
one about a 13-year-old answerable either.

Known limit: a duration written like an age ("lleva 2 días con fiebre") reads
as a baby, as it does in the red flags, and lets an older child's question
through to retrieval. That is the behaviour before this filter, never a new
refusal.
"""
from __future__ import annotations

import re

from adelia.clinical.red_flags import age_months_in, normalize

#: Ages written as words, accent-free (the text is normalized first).
_WORDS: dict[str, int] = {
    "un": 1, "uno": 1, "una": 1, "one": 1, "a": 1,
    "dos": 2, "two": 2, "deux": 2,
    "tres": 3, "three": 3, "trois": 3,
    "cuatro": 4, "four": 4, "quatre": 4,
    "cinco": 5, "five": 5, "cinq": 5,
    "seis": 6, "six": 6,
    "siete": 7, "seven": 7, "sept": 7,
    "ocho": 8, "eight": 8, "huit": 8,
    "nueve": 9, "nine": 9, "neuf": 9,
    "diez": 10, "ten": 10, "dix": 10,
    "once": 11, "eleven": 11, "onze": 11,
    "doce": 12, "twelve": 12, "douze": 12,
    "trece": 13, "thirteen": 13, "treize": 13,
    "catorce": 14, "fourteen": 14, "quatorze": 14,
    "quince": 15, "fifteen": 15, "quinze": 15,
}
_N = r"(\d{1,2}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_RANGE = rf"{_N}(?:\s*(?:-|a|to|or|ou|o|y|et)\s*{_N})?"

#: Each pattern's first group is the age (or the lower end of a range).
_AGED: tuple[re.Pattern[str], ...] = (
    # "de 7 años", "tiene 4 años", "con 3 añitos", "cumplió 5 años"
    re.compile(
        rf"\b(?:de|tiene|tenia|cumple|cumplio|cumplira|con)\s+(?:unos\s+)?{_RANGE}"
        r"\s*(?:anos?|anitos?)\b"
    ),
    # "my 7-year-old", "6 years old", "a three year old"
    re.compile(rf"\b{_RANGE}[\s-]*(?:years?|yrs?)[\s-]*olds?\b"),
    re.compile(rf"\baged\s+{_RANGE}\b|\b{_RANGE}\s+years?\s+of\s+age\b"),
    # "de 10 ans", "il a 4 ans", "âgée de 5 ans"; not "il y a 3 ans"
    re.compile(rf"\b(?:de|(?<!\by )a|agee?s?)\s+{_RANGE}\s*ans?\b"),
)
#: Someone in the message who is, or may be, the baby.
_BABY = re.compile(
    r"\b(?:bebe\w*|recien nacid\w*|lactante\w*|babies|baby|newborn\w*|infants?|"
    r"nourrisson\w*|nouveau[- ]?ne\w*|herman\w*|siblings?|frere\w*|soeur\w*)\b"
)
_AGED_MARK = "\x00"


def _age(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token]


def child_outside_scope(message: str) -> bool:
    """Whether `message` is about a child of 3 years or more and no baby.

    True for "my 7-year-old", "Mon fils de 10 ans", "mi hija de 13 años".
    False for "mi bebé de 7 meses", "tengo 35 años", "hace 3 años" and for
    "mi hijo de 4 años tiene celos del bebé".
    """
    text = normalize(message)
    aged = False
    young = False
    for pattern in _AGED:
        for m in pattern.finditer(text):
            low = _age(m.group(1))
            if 3 <= low <= 17:
                aged = True
            elif low < 3:
                young = True
    if not aged:
        return False
    if young:
        return False
    # The older child's own words ("mi bebé de 3 años") are not a second child.
    marked = text
    for pattern in _AGED:
        marked = pattern.sub(_AGED_MARK, marked)
    marked = re.sub(rf"{_BABY.pattern}\s*{_AGED_MARK}", _AGED_MARK, marked)
    if _BABY.search(marked):
        return False
    months = age_months_in(marked.replace(_AGED_MARK, " "))
    return months is None or months > 24
