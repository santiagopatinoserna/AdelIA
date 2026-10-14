"""Display metadata of the evidence corpus: one canonical name per institution.

Why this exists (audit 1.1, follow-up of 2026-10-14): production held 127
sources and nobody could say how many organizations stood behind them,
because the `organization` field had grown by hand, file by file. NICE came
in three spellings, the American Academy of Pediatrics in four, and one
source carried "https://www" there: a piece of its own URL, cut by whoever
filled the field, which the citation card would have printed as the publisher.
The landing now names real institutions instead of quoting a count of
"organizations", and that claim is only checkable if each institution is ONE
string.

What is and is not normalized, on purpose:

* Institutional documents (a guideline, a protocol, a family page) take the
  institution's name. The committee, the web section or the journal that
  carried it is dropped from the field: the title already names the
  publication where it matters ("(HealthyChildren.org)", "Bright Futures"),
  and the first line of every chunk repeats the full attribution. Titles are
  NOT touched here, because the loader is idempotent by title: renaming one
  inserts a second copy of the source with its chunks and its embeddings.
* Journal articles keep the journal as their organization. A teething
  cohort study published in "Pediatrics" is not a document of the American
  Academy of Pediatrics, and attributing it to the Academy would put an
  endorsement on the card that nobody gave. Only variants of the SAME journal
  are unified ("Pediatrics" with "Pediatrics (American Academy of
  Pediatrics)") and volume or page locators are cut off ("Viruses
  13(11):2245" is "Viruses").
* The field still mixes publishers and journals. Separating them cleanly
  needs a column of its own (and a migration); until then the count of
  institutions is a count of institutional strings, not of authors.

The table is applied twice: tests/test_evidence_files.py fails when a corpus
file still holds an alias, and the loader applies it again to whatever it
reads, so a source added later with a stray spelling lands canonical anyway.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# canonical name -> spellings found in the corpus files before 2026-10-14.
CANONICAL_ORGANIZATIONS: dict[str, tuple[str, ...]] = {
    "National Institute for Health and Care Excellence (NICE)": (
        "NICE",
        "NICE Guideline NG143",
    ),
    "American Academy of Pediatrics": (
        "American Academy of Pediatrics (Bright Futures)",
        "American Academy of Pediatrics (HealthyChildren.org)",
        "American Academy of Pediatrics, Committee on Nutrition (HealthyChildren.org)",
        "American Academy of Pediatrics / Pediatrics",
        "Pediatrics (American Academy of Pediatrics, Committee on Nutrition)",
    ),
    # The journal of the Academy. Kept apart from the Academy itself, see the
    # module docstring.
    "Pediatrics (American Academy of Pediatrics)": ("Pediatrics",),
    "World Health Organization (WHO)": (
        "WHO",
        "Organización Mundial de la Salud",
    ),
    "Asociación Española de Pediatría": (
        "Asociación Española de Pediatría (Comité de Lactancia Materna y Comité de Nutrición)",
        "Comité de Lactancia Materna, Asociación Española de Pediatría",
    ),
    "Asociación Española de Pediatría de Atención Primaria (AEPap)": (
        "AEPap",
        "AEPap (Asociación Española de Pediatría de Atención Primaria)",
        "Familia y Salud (AEPap)",
        "Familia y Salud (Asociación Española de Pediatría de Atención Primaria, AEPap)",
    ),
    "European Society for Paediatric Gastroenterology, Hepatology and Nutrition (ESPGHAN)": (
        "ESPGHAN / Journal of Pediatric Gastroenterology and Nutrition",
        "Journal of Pediatric Gastroenterology and Nutrition (ESPGHAN)",
    ),
    "Société française de pédiatrie": (
        "Comité de nutrition de la Société française de pédiatrie (Archives de Pédiatrie, "
        "Elsevier Masson)",
        "Comité de nutrition de la Société française de pédiatrie; Perfectionnement en "
        "Pédiatrie 2022;5(2):127-133 (Elsevier Masson /",
        "Archives de Pédiatrie (groupe de travail sur le fer de la Société française de "
        "pédiatrie)",
    ),
    "GOV.UK": ("GOV",),
    "BMC Medicine": ("BMC Medicine 12:107",),
    "Microorganisms": ("Microorganisms 10(1):111",),
    "Viruses": ("Viruses 13(11):2245",),
}

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in CANONICAL_ORGANIZATIONS.items() for alias in aliases
}

# "https://www", "http://x", "//cdn", "www.example.org": a URL, or the start of
# one. A site name written as a publisher ("mpedia.fr (AFPA)", "Assurance
# Maladie (ameli.fr)") is fine and does not match.
_URL_LIKE = re.compile(r"^\s*(?:[a-z][a-z0-9+.\-]*:)?//|^\s*(?:https?:|www\.)", re.IGNORECASE)


def looks_like_url(value: str | None) -> bool:
    return bool(value) and _URL_LIKE.match(value) is not None


def canonical_organization(organization: str | None) -> str | None:
    """The canonical spelling of `organization`, or None when it has to go.

    A URL-like value is refused, never stored: the card prints this field as
    the publisher, and "https://www" is not one. Blank becomes None, so the
    citation falls back to the title alone. Anything not in the alias table
    is returned as it came (a journal, an institution nobody has duplicated).
    """
    if organization is None:
        return None
    value = organization.strip()
    if not value:
        return None
    if looks_like_url(value):
        logger.warning("evidence organization looks like a URL, stored empty: %r", value)
        return None
    return _ALIAS_TO_CANONICAL.get(value, value)
