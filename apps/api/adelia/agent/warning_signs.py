"""The warning-signs search: when to see a doctor, read from the library.

Measured in production on 2026-11-06 (demo, Claude, 30 real questions,
~/dev/adelia-design/shots/prod-domains-eval-after.json). "Tiene tos de perro por
la noche, ¿qué puedo hacer en casa?" got a correct croup plan cited to AEP,
AEPap and SEUP, then "Señales de alarma y cuándo acudir a urgencias: No tengo
evidencia...". The croup guides for parents do say when to go; that paragraph
was not among the four fragments retrieved, because her question is about home
care and the search found home care.

So, behind settings.warning_signs_retrieval (off by default), the retrieve node
of a plan embeds one more text in the same call: the topic as it was searched,
then these words on a second line. That vector is searched under the same two
cut-offs (evidence_max_distance and the relative margin, untouched) and up to
two fragments the main search did not hold are appended after it
(evidence_retrieval.add_warning_fragments), those of the sources already
retrieved first. What it can and cannot do:

* it runs only when the main search found evidence: a question with nothing
  under the cut-off is refused by the code as before, never answered from a
  warning-signs paragraph (B4 of the golden set, tests/test_agent_graph.py);
* it runs only for a plan: a short answer has no "Cuándo ir al médico";
* the guard has already run on her words: a red flag never gets here;
* the main fragments keep their order and their [ev_N] numbers.

The words are in the question's language, as agreed. The corpus is Spanish and
an English or French question is usually translated before the search
(corpus_query.py), so for those the probe in scripts/probe_warning_signs.py is
what tells whether Spanish words would serve them better.
"""
from __future__ import annotations

#: The warning-sign words added to the topic, per locale.
WARNING_TERMS: dict[str, str] = {
    "es": "signos de alarma, cuándo consultar, urgencias",
    "en": "warning signs, when to see a doctor, emergency",
    "fr": "signes d’alerte, quand consulter, urgences",
}

DEFAULT_LOCALE = "es"


def warning_query(text: str, locale: str | None) -> str:
    """The topic as searched, then the warning-sign words on a second line."""
    lang = (locale or DEFAULT_LOCALE).split("-")[0].lower()
    terms = WARNING_TERMS.get(lang, WARNING_TERMS[DEFAULT_LOCALE])
    return f"{text.strip()}\n{terms}"
