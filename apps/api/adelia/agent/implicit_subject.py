"""The baby she does not name, put back for the search only.

Measured in production on 2026-11-06 (demo and container, read only, cut-off
0.19): "Tiene 38,3 de fiebre desde esta mañana, ¿qué hago?" was refused, its
three fever sources at 0.197-0.205 ("¿Qué debo saber sobre la fiebre?" of AEPap,
"Cómo actuar si un bebé tiene fiebre", "Fiebre en el niño, ¿cuándo hay que
llevarlo al hospital?"); "Tiene diarrea desde ayer, ¿qué hago?" too, AEPap at
0.218 and AAP at 0.229. "Mi bebé de 10 meses tiene 38,5 de fiebre pero juega"
found five sources at 0.12-0.14. A mother writes without a subject because it
is obvious who she means, and the fragments are written about "el bebé": her
sentence lands just past the cut on the questions she asks most.

So, behind settings.implicit_subject_expansion (off by default), the retrieve
step embeds one more text when hers names nobody: "Mi bebé: <her text>", with
the profile's age when there is one ("Mi bebé de 5 meses: ..."; in the demo,
the demo baby's). It is searched under the same cut-offs and each fragment keeps
its better distance (evidence_retrieval.merge_by_best_distance), so it can find
a fragment her sentence missed and cannot lose one it found. No threshold moves.

It is its own search, not merged into the lay lexicon's (lay_terms.py): each
setting then searches exactly the text its own measurement saw, and turning one
on cannot change what the other finds. The cost is one more vector in the same
embedding call and one more pgvector query.

Rules, each pinned in tests/test_implicit_subject.py:

* deterministic, no model: word lists over her text, accents and case folded,
  per language (Spanish "son" is a verb, English "son" a son);
* any word for the child (bebé, hija, niño, nena, peque, my 4-month-old, mon
  fils...) or the child's own name means she already said who: nothing added;
* anyone else (yo, tengo fiebre, estoy embarazada, mi pareja, mi madre, I have,
  j'ai, mon mari...) means it may not be the baby: nothing added either. Worry
  and doubt ("estoy preocupada", "tengo una duda", "tengo que") do not count;
* an age she wrote ("tiene 4 meses") is not contradicted by the profile's: the
  prefix then carries no age;
* a French or English question is searched in its Spanish rendering
  (corpus_query.py): both her words and the rendering must name nobody, and the
  prefix follows the language of the text it is put on;
* the guard has already run on her original text: a red flag never gets here.
"""
from __future__ import annotations

import re

from adelia.agent.lay_terms import fold

DEFAULT_LANG = "es"


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


#: Words for the child, folded. Adjectives that are also nouns ("pequeño",
#: "petit") count only with a determiner, so "un bulto pequeño" is no subject.
_CHILD = {
    "es": _rx(
        r"\b(bebes?|bebit[oa]s?|hij[oa]s?|nin[oa]s?|nen[ea]s?|peques?|criaturas?|"
        r"lactantes?|recien\s+nacid[oa]s?|neonat[oa]s?|chiquitin[ea]?s?|melliz[oa]s?|"
        r"gemel[oa]s?)\b",
        r"\b(el|la|los|las|mi|mis|nuestr[oa]s?)\s+pequen(o|a|os|as|in|ina)\b",
    ),
    "en": _rx(
        r"\b(baby|babies|bub|bubs|sons?|daughters?|child|children|kids?|toddlers?|"
        r"infants?|newborns?|boy|girl|twins?)\b",
        r"\blittle\s+one\b",
        r"\b\d+[- ](day|week|month|year)s?[- ]old\b",
    ),
    "fr": _rx(
        r"\b(bebes?|fils|filles?|enfants?|nourrissons?|nouveau-nes?|nouveau\s+nes?|"
        r"loulous?|jumeaux|jumelles|garcons?)\b",
        r"\b(mon|ma|mes|le|la|les|notre|nos)\s+(petit|petite|petits|petites|puce)\b",
    ),
}

#: Someone else is the subject: she herself, a partner, a relative, a pet.
_SOMEONE_ELSE = {
    "es": _rx(
        r"\byo\b",
        r"\b(tengo|estoy|he\s+tenido|me\s+duele\w*|me\s+siento|me\s+encuentro|me\s+noto|"
        r"me\s+han?\s+salido)\b",
        r"\b(embarazada|embarazo|posparto|postparto)\b",
        r"\bmis?\s+(pareja|marido|mujer|espos[oa]|novi[oa]|madre|padre|mama|papa|"
        r"suegr[oa]s?|abuel[oa]s?|herman[oa]s?|ti[oa]s?|prim[oa]s?|amig[oa]s?|"
        r"perr[oa]s?|gat[oa]s?|padres)\b",
    ),
    "en": _rx(
        r"\bi\s+(have|am|feel|got|had)\b|\bi'(m|ve)\b|\bmyself\b",
        r"\b(pregnant|pregnancy|postpartum)\b",
        r"\bmy\s+(husband|wife|partner|boyfriend|girlfriend|mother|father|mom|mum|dad|"
        r"sister|brother|mother-in-law|father-in-law|parents|friend|dog|cat)\b",
    ),
    "fr": _rx(
        r"\bj'ai\b|\bje\s+(suis|me\s+sens|tousse)\b|\bmoi\b",
        r"\b(enceinte|grossesse|post-partum)\b",
        r"\bmon\s+(mari|conjoint|compagnon|copain|pere|frere|chien|chat)\b",
        r"\bma\s+(femme|compagne|copine|mere|soeur|belle-mere)\b",
    ),
}

#: First-person phrases that are about her worry, not about her body. They are
#: removed before the someone-else check.
_HERS_BUT_ABOUT_THE_BABY = {
    "es": _rx(
        r"\bestoy\s+(muy\s+|un\s+poco\s+)?(preocupad|agobiad|asustad|nervios|desesperad)\w*",
        r"\btengo\s+(una\s+|un\s+par\s+de\s+|muchas\s+)?(duda|pregunta|consulta)s?\b",
        r"\btengo\s+que\b",
    ),
    "en": _rx(
        r"\bi\s+(have|had|got)\s+(a|one|some)\s+(question|doubt)s?\b",
        r"\bi\s+(have|had)\s+to\b",
        r"\bi('m|\s+am)\s+(so\s+|very\s+|really\s+|a\s+bit\s+)?(worried|scared|anxious|"
        r"concerned|nervous)\b",
    ),
    "fr": _rx(
        r"\bj'ai\s+(une|des|quelques)\s+(questions?|doutes?)\b",
        r"\bj'ai\s+peur\b",
        r"\bje\s+suis\s+(tres\s+|un\s+peu\s+)?(inquiete?|angoissee?|stressee?)\b",
    ),
}

#: An age she wrote. The prefix then carries none, so it never says two ages.
_AGE_IN_TEXT = re.compile(r"\b\d+\s*(mes|meses|semanas?|months?|weeks?|mois|semaines?)\b")

#: Past this the active profile is no baby (her own "Mi perfil" with her date of
#: birth): the prefix then carries no age. AdelIA covers 0-24 months.
MAX_PREFIX_AGE_MONTHS = 36


def _lang(locale: str | None) -> str:
    key = (locale or DEFAULT_LANG).split("-")[0].lower()
    return key if key in _CHILD else DEFAULT_LANG


def _folded(text: str) -> str:
    return fold((text or "").replace("’", "'"))


def names_someone(text: str, locale: str | None, *, name: str | None = None) -> bool:
    """True when `text` says who it is about: the child, or anyone else."""
    lang = _lang(locale)
    folded = _folded(text)
    if name and len(fold(name).strip()) >= 2:
        if re.search(rf"\b{re.escape(fold(name).strip())}\b", folded):
            return True
    if _CHILD[lang].search(folded):
        return True
    return bool(_SOMEONE_ELSE[lang].search(_HERS_BUT_ABOUT_THE_BABY[lang].sub(" ", folded)))


def subject_prefix(locale: str | None, age_months: int | None = None) -> str:
    """"Mi bebé: " or "Mi bebé de N meses: ", in the language of the text it goes on."""
    lang = _lang(locale)
    age = (
        age_months
        if age_months is not None and 1 <= age_months <= MAX_PREFIX_AGE_MONTHS
        else None
    )
    if lang == "en":
        return "My baby: " if age is None else f"My {age}-month-old baby: "
    if lang == "fr":
        return "Mon bébé : " if age is None else f"Mon bébé de {age} mois : "
    if age is None:
        return "Mi bebé: "
    return f"Mi bebé de {age} {'mes' if age == 1 else 'meses'}: "


def subject_query(
    text: str,
    *,
    locale: str | None,
    spoken: str | None = None,
    age_months: int | None = None,
    name: str | None = None,
) -> str | None:
    """`text` with the baby put back, or None when it already says who it is about.

    `text` is what the corpus search embeds; `spoken` is her own words before
    the Spanish rendering (corpus_query.py), in `locale`. When the rendering
    changed them, `text` is Spanish and gets the Spanish prefix; either way
    both must name nobody.
    """
    if not (text or "").strip():
        return None
    spoken = text if spoken is None else spoken
    text_lang = _lang(locale) if text == spoken else DEFAULT_LANG
    if names_someone(text, text_lang, name=name):
        return None
    if spoken != text and names_someone(spoken, locale, name=name):
        return None
    if _AGE_IN_TEXT.search(_folded(text)) or _AGE_IN_TEXT.search(_folded(spoken)):
        age_months = None
    return f"{subject_prefix(text_lang, age_months)}{text.strip()}"
