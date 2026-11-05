"""A mother's words, rendered in the corpus's clinical Spanish, for the search only.

Measured in production on 2026-11-05 (30 real questions, mistral-embed, cut-off
0.19, ~/dev/adelia-design/shots/prod-domains-eval.json): the library holds
diaper dermatitis, hand-foot-mouth, conjunctivitis, constipation and croup, and
"Tiene el culito muy rojo del pañal", "Le han salido granitos en las manos y en
la boca", "Tiene un ojo con legañas amarillas" and "Lleva 4 días sin hacer caca
y toma pecho" were refused as if it had none. Nothing filtered them: every
fragment is Spanish and tagged pediatrics, there is no age filter, and the
relative margin only acts once something passed. Each fragment opens by naming
the condition ("Tema: síntomas y causas de la dermatitis del pañal"); her
sentence names what she sees, and a short sentence without the name of the
condition lands past the cut-off. The full diagnosis, question by question, is
in docs/specs/RECUPERACION_LENGUAJE_MADRE.md.

So, behind settings.lay_query_expansion (off by default), the retrieve step
embeds a second text: her sentence followed by the clinical terms this lexicon
reads in it. Both vectors are searched with the same cut-offs and the better
distance of each fragment wins (evidence_retrieval.merge_by_best_distance):
the expansion can find a fragment the original missed, it cannot lose one the
original found, and it never loosens a threshold.

Rules the lexicon keeps, each pinned in tests/test_lay_terms.py:

* deterministic, no model: a regex over her text with accents and case folded;
* every term is written in the pediatric corpus, so it can only point at what
  the library holds;
* no false friends: "cacahuete" is not "caca", a red stool in the nappy is not
  diaper dermatitis, a navel that sticks out is the hernia and not the cord;
* none of the 15 group B questions of the golden set gets a term. That is why
  there is no entry for crawling (B2, and the fragments already say gatear),
  yellow skin (B8), trapped wind (B11), French diarrhoea (B13) or first teeth
  in French (B14);
* the guard has already run on her original text: a red flag never gets here.

Patterns are written folded (no accents, ñ as n). French and English entries
are for when the translation (corpus_query.py) fell back to her own words; the
terms are Spanish either way, the corpus's language.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class LayEntry:
    name: str
    #: Any one of these, searched in the folded text, makes the entry match.
    patterns: tuple[re.Pattern[str], ...]
    #: Spanish clinical terms the corpus uses for it, in the order they are added.
    terms: tuple[str, ...]
    #: Any of these in the folded text vetoes the entry (the false friend).
    unless: tuple[re.Pattern[str], ...] = ()
    #: Entries of the same message that, when they match, veto this one.
    yields_to: tuple[str, ...] = ()


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


def fold(text: str) -> str:
    """Lower case, accents and tildes removed: "Legañas" and "LEGANAS" read the same."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_SPOTS_ES = r"(granit\w*|granos?|ampoll\w*|llag\w*|pupas?|vejigas?|puntitos|sarpullido|manchitas)"
_RED_ES = (
    r"(roj[oa]s?|rojez|rojit[oa]s?|irritad[oa]s?|irritacion|rozad[oa]s?|rozaduras?|"
    r"escoc\w*|en carne viva|granit[oa]s|pupas?)"
)
_BOTTOM_ES = r"\b(culito|culete|culo|pompis|nalg\w*)\b"


def _two_of(words: tuple[str, ...]) -> str:
    """A lookahead pattern true when at least two of `words` appear anywhere."""
    pairs = [
        rf"(?=.*\b{a}\b)(?=.*\b{b}\b)"
        for i, a in enumerate(words) for b in words[i + 1:]
    ]
    return "^(?:" + "|".join(pairs) + ")"


_HFM_ES = _two_of(("manos?", "pies?", "boca"))
_HFM_EN = _two_of(("hands?", "feet|foot", "mouth"))
_HFM_FR = _two_of(("mains?", "pieds?", "bouche"))


LEXICON: tuple[LayEntry, ...] = (
    LayEntry(
        "estrenimiento",
        _rx(
            r"\b(sin|no)\s+(ha\s+)?(hacer|hace|hecho|hizo)\s+(caca|popo|deposicion)",
            r"\bcuesta\w*\s+(\w+\s+){0,2}hacer\s+caca",
            r"\bcacas?\s+(muy\s+)?dur[oa]s?\b|\bcacas?\s+(\w+\s+){0,2}(muy\s+)?dur[oa]s?\b",
            r"\b(hasn'?t|has not|not|no|without)\s+(had\s+a\s+|done\s+a\s+)?poo",
            r"\bpas\s+(fait\s+)?(de\s+)?(caca|selles)\b",
        ),
        ("estreñimiento", "deposiciones", "heces"),
    ),
    LayEntry(
        "deposiciones",
        _rx(r"\bcacas?\b", r"\bpopos?\b", r"\bcagarrinas?\b", r"\bpoo(p|s)?\b"),
        ("deposiciones", "heces"),
    ),
    LayEntry(
        "dermatitis_panal",
        _rx(
            rf"{_BOTTOM_ES}.*\b{_RED_ES}|\b{_RED_ES}\b.*{_BOTTOM_ES}",
            rf"\b{_RED_ES}\s+(del|por el|con el)\s+panal\b",
            r"\bfesses\s+(\w+\s+)?(rouges|irritees)\b|\berytheme\s+fessier\b",
            r"\b(red|sore)\s+(\w+\s+)?(bottom|bum)\b|\b(nappy|diaper)\s+rash\b",
        ),
        ("dermatitis del pañal", "área del pañal"),
    ),
    LayEntry(
        "mano_pie_boca",
        _rx(
            rf"{_HFM_ES}.*\b{_SPOTS_ES}\b",
            rf"{_HFM_EN}.*\b(spots|blisters|sores|rash)\b",
            rf"{_HFM_FR}.*\b(boutons|cloques|aphtes|plaques)\b",
        ),
        ("síndrome boca mano pie", "manos, pies y boca", "exantema", "ampollas"),
    ),
    LayEntry(
        "exantema",
        _rx(r"\b(granitos|sarpullido|puntitos\s+rojos|manchitas\s+rojas)\b"),
        ("exantema",),
        unless=_rx(r"\bpanal\b", _BOTTOM_ES),
    ),
    LayEntry(
        "conjuntivitis",
        _rx(
            r"\blegan\w*",
            r"\bojos?\s+(\w+\s+)?pegad[oa]s?\b|\bpegad[oa]s?\s+(\w+\s+){0,2}ojos?\b",
            r"\bpus\s+en\s+(el|los|un)\s+ojos?\b|\bojos?\s+con\s+pus\b",
            r"\byeux\s+colles\b|\b(oeil|œil)\s+colle\b|\bchassie\b",
            r"\b(sticky|gunky|goopy|crusty)\s+eyes?\b",
        ),
        ("conjuntivitis", "secreción", "conducto lagrimal"),
    ),
    LayEntry(
        "lagrimeo",
        _rx(
            r"\b(llora|lloran|lagrimea|lagrimean)\s+(el|un|los|sus)\s+ojos?\b",
            r"\bojos?\s+(que\s+)?(llora|lloran|lagrimea\w*|llorosos?)\b",
        ),
        ("lagrimeo", "obstrucción del conducto lagrimal"),
    ),
    LayEntry(
        "mocos",
        _rx(
            r"\bmoc(os|o)\b|\bmoque\w*",
            r"\bnariz\s+(tapada|taponada|congestionada)\b",
            r"\bnez\s+(bouche|qui coule|encombre)\b|\bmorve\b",
            r"\b(runny|stuffy|blocked)\s+nose\b|\bsnott?y\b|\bsnot\b",
        ),
        ("congestión nasal", "rinorrea", "catarro"),
    ),
    LayEntry(
        "crup",
        _rx(
            r"\btos\s+(de\s+perro|perruna|de\s+foca|ronca)\b",
            r"\btos\w*\s+como\s+(un\s+|una\s+)?(perro|foca|ladrido)\b",
            r"\btoux\s+(de|comme un)\s+phoque\b|\btoux\s+(aboyante|rauque)\b",
            r"\bbark\w*\s+cough\b|\bseal(-like)?\s+cough\b|\bcough\w*\s+like\s+a\s+seal\b",
            r"\bcroupy\b",
        ),
        ("laringitis", "crup", "tos perruna"),
    ),
    LayEntry(
        "hernia_umbilical",
        _rx(
            r"\bombligu?i?t?o\b.*\b(salido|sale|sobresale|bulto|abultado|hinchado|hernia)\b",
            r"\b(bulto|hernia)\b.*\bombligu?i?t?o\b",
        ),
        ("hernia umbilical",),
    ),
    LayEntry(
        "cordon_umbilical",
        _rx(
            r"\bombligu?i?t?o\b",
            r"\bumbilical\b",
            r"\bmunon\b",
            r"\bcordon\b.{0,40}\b(ca[eiy]\w*|cur\w*|limpi\w*|sangr\w*|huele|olor|pinza|sec\w*|supur\w*)",
            r"\b(ca[eiy]\w*|cur\w*|limpi\w*)\b.{0,20}\bcordon\b",
            r"\bnombril\b|\bcordon\s+ombilical\b|\bchute\s+du\s+cordon\b",
            r"\bbelly\s+button\b|\bcord\s+stump\b",
        ),
        ("cordón umbilical", "muñón", "cuidados del cordón"),
        yields_to=("hernia_umbilical",),
    ),
    LayEntry(
        "regurgitacion",
        _rx(
            r"\b(echa|devuelve|vomita)\s+(\w+\s+){0,2}leche\b",
            r"\bbocanadas?\b",
            r"\ble\s+sale\s+(la\s+)?leche\s+por\s+(la\s+)?(boca|nariz)\b",
        ),
        ("regurgitación", "reflujo"),
    ),
    LayEntry(
        "denticion",
        _rx(
            r"\b(salen|sale|saliendo|asoma\w*)\s+(\w+\s+){0,2}(dientes?|muelas?|colmillos?)\b",
            r"\bbabea\w*\b",
        ),
        ("dentición", "erupción dentaria"),
    ),
    LayEntry(
        "otitis",
        _rx(
            r"\b(toca|tira|rasca)\w*\s+(\w+\s+){0,2}(oreja|orejas|oido|oidos)\b",
            r"\bduele\w*\s+(el|un|los)\s+oidos?\b",
            r"\b(supura|sale\s+\w+\s+del)\s+(el\s+|un\s+)?oido\b",
        ),
        ("otitis",),
    ),
    LayEntry(
        "estrabismo",
        _rx(
            r"\bbizc\w*|\bbizque\w*",
            r"\b(va|desvia|tuerce)\s+(un|el)\s+ojo\b|\bojo\s+vago\b",
        ),
        ("estrabismo",),
    ),
    LayEntry(
        "plagiocefalia",
        _rx(r"\bcabeza\s+(\w+\s+)?(plana|aplanada)\b|\b(plana|aplanada)\s+(la\s+)?cabeza\b"),
        ("plagiocefalia",),
    ),
    LayEntry(
        "costra_lactea",
        _rx(r"\b(costras?|costritas?|escamas|caspa)\b.*\b(cabeza|cuero cabelludo)\b"),
        ("costra láctea", "dermatitis seborreica"),
    ),
    LayEntry(
        "infeccion_orina",
        _rx(
            r"\b(pis|pipi|orina)\b.*\b(huele|olor|escuece|duele)\b",
            r"\b(llora|duele|escuece)\w*\s+al\s+hacer\s+(pis|pipi)\b",
        ),
        ("infección de orina",),
    ),
    LayEntry(
        "hernia_inguinal",
        _rx(
            r"\bbulto\s+(en|de)\s+(la\s+|las\s+|los\s+|el\s+)?"
            r"(ingle|ingles|huevos?|escroto|testiculos?)\b",
            r"\bhuevo\s+hinchado\b",
        ),
        ("hernia inguinal", "hidrocele"),
    ),
    LayEntry(
        "dermatitis_atopica",
        _rx(
            r"\bpiel\s+(muy\s+)?(seca|aspera|rugosa)\b",
            r"\brojeces\s+en\s+(las\s+)?mejillas\b",
        ),
        ("dermatitis atópica", "eccema"),
    ),
)


def _matches(entry: LayEntry, folded: str) -> bool:
    if any(p.search(folded) for p in entry.unless):
        return False
    return any(p.search(folded) for p in entry.patterns)


def clinical_terms(text: str) -> tuple[str, ...]:
    """The corpus's terms for what she wrote, once each, in lexicon order.

    A term she already wrote is not repeated. Empty when nothing matches,
    which is the answer for every group B question of the golden set.
    """
    folded = fold(text or "")
    if not folded.strip():
        return ()
    matched = {e.name for e in LEXICON if _matches(e, folded)}
    terms: list[str] = []
    for entry in LEXICON:
        if entry.name not in matched or matched.intersection(entry.yields_to):
            continue
        for term in entry.terms:
            if term not in terms and fold(term) not in folded:
                terms.append(term)
    return tuple(terms)


def expanded_query(text: str) -> str | None:
    """Her text, then the clinical terms on a second line; None when none apply."""
    terms = clinical_terms(text)
    if not terms:
        return None
    return f"{text.strip()}\n{', '.join(terms)}"
