"""Deterministic red-flag detector, in code, ahead of the RAG.

Audit 2026-08-31, item 3.3. Risk 1 of the report is "clinical harm to a baby
from an answer that looks sourced and is not". The single most dangerous
shape it takes is a parent asking a routine-sounding question about a baby
who needs to be seen *now*: "my 2-month-old is at 38.2, do I give her
paracetamol?". Retrieval will happily find a paracetamol fragment, the model
will happily dose it, and the answer will read as evidence-backed.

So the decision is taken before any of that, by code, from patterns:

* `detect(question, locale=..., age_months=...)` returns a `RedFlag` or None.
* When it returns a flag, the answering surface returns
  `answer_contract.red_flag_reply(...)` and **never calls the generative
  model**. A prompt clause is a request; this is a guarantee.

Why not a prompt clause: the model is the component that fails under exactly
the conditions that matter (a long context, a confident parent, a question
that has an easy wrong answer). `chat_orchestrator` already refuses in code
when retrieval is empty, for the same reason (v0.1.1, audit 1.3); this is the
mirror case, where retrieval finds plenty and is beside the point.

Scope: this module answers "must a human see this baby now?", never "what is
wrong with the baby". It over-triggers on purpose. A false positive costs a
parent a phone call to a nurse; a false negative is the reason the project
would not survive.

The eleven flags come from the audit's list and each is anchored in a primary
guideline (the wording the parent gets lives in services/answer_contract, the
supporting fragments in enrichment/data/evidence_urgencias_lactante.json):

  fever_under_3_months  NICE NG143 1.2.12 (<3 months, >=38 C, high risk)
  non_blanching_rash    NICE NG143 1.2.18 / NG240 (meningococcal disease)
  respiratory_distress  NICE NG9 1.2.1 (grunting, recession, RR >70)
  cyanosis              NICE NG9 1.2.1 / NG143 table 2 (red)
  seizure               NICE NG143 table 2 (status, focal seizures)
  choking               ERC 2021 Paediatric Life Support (FBAO)
  anaphylaxis           AEP Anafilaxia en Pediatria 2019 (IM adrenaline)
  bulging_fontanelle    NICE NG143 1.2.5 / 1.2.19 (bacterial meningitis)
  lethargy              NICE NG143 1.2.5 (does not wake / no response)
  no_wet_nappy_12h      NICE NG9 1.6.1 (no wet nappy for 12 hours)
  dehydration           NICE CG84 table 1 (sunken eyes, no tears, turgor)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# Highest first. A question can carry several flags ("she had a fit and her
# lips went blue"); the parent gets one answer, so the most time-critical
# wins. Choking and anaphylaxis are minutes; fever in a neonate is hours.
PRIORITY: tuple[str, ...] = (
    "choking",
    "anaphylaxis",
    "cyanosis",
    "seizure",
    "respiratory_distress",
    "non_blanching_rash",
    "bulging_fontanelle",
    "lethargy",
    "fever_under_3_months",
    "dehydration",
    "no_wet_nappy_12h",
)

#: Age below which an axillary temperature of 38 C is, on its own, a red flag
#: (NICE NG143 recommendation 1.2.12).
FEVER_AGE_LIMIT_MONTHS = 3
#: The temperature that makes it one, in Celsius (NICE NG143 table 2, red).
FEVER_THRESHOLD_C = 38.0


@dataclass(frozen=True)
class RedFlag:
    """One fired flag. `matched` is the literal fragment, for the log."""

    code: str
    matched: str
    age_months: int | None = None
    temperature_c: float | None = None


def normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace.

    Patterns are written accent-free so that "fiebre"/"fièvre", "pañal"/
    "panal" and "étouffe"/"etouffe" need one spelling each, and so that a
    parent typing without accents at 3 a.m. is not a miss.
    """
    folded = unicodedata.normalize("NFD", text or "")
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = folded.replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", " ", folded).lower().strip()


# --------------------------------------------------------------------------
# Patterns. Written per language but matched all together: a Spanish-locale
# session where the mother types "he's grunting" must still fire. Locale only
# picks the language of the ANSWER (answer_contract.red_flag_reply).
# --------------------------------------------------------------------------

_PATTERNS: dict[str, tuple[str, ...]] = {
    "choking": (
        # es
        r"\batragant\w*", r"\bse (?:le )?atragant\w*", r"\bcuerpo extra[nñ]o\b",
        r"\bse (?:ha )?trag\w+ (?:un|una|el|la)\b", r"\bobstruccion de (?:la )?via aerea\b",
        r"\bmaniobra de heimlich\b", r"\bno puede (?:respirar|toser) (?:desde que|tras)\b",
        # en
        r"\bchok(?:ing|ed|es)\b", r"\bfor?eign body\b", r"\bairway obstruction\b",
        r"\bswallowed a\b", r"\bheimlich\b",
        # fr
        r"\betouffe\w*\b", r"\bfausse route\b", r"\bcorps etranger\b", r"\ba avale (?:un|une)\b",
        r"\bs'?etrangl\w*",
    ),
    "anaphylaxis": (
        # es
        r"\banafilaxi\w*", r"\breaccion alergica grave\b", r"\bedema de glotis\b",
        r"\bshock anafilactico\b",
        r"\b(?:se le )?(?:ha )?hinch\w+ (?:la )?(?:cara|lengua|labios|garganta)\b",
        r"\bhinchazon de (?:la )?(?:cara|lengua|labios|garganta)\b",
        r"\badrenalina autoinyect\w*", r"\bautoinyector de adrenalina\b",
        # en
        r"\banaphyla\w*", r"\bepipen\b", r"\bswollen (?:lips|tongue|face|throat)\b",
        r"\bsevere allergic reaction\b",
        # fr
        r"\banaphyla\w*", r"\boedeme de quincke\b", r"\breaction allergique grave\b",
        r"\bgonflement (?:des levres|de la langue|du visage|de la gorge)\b",
    ),
    "cyanosis": (
        # es
        r"\bcianosis\b", r"\bcianotic\w*",
        r"\b(?:labios|lengua|piel|cara|manos|pies|u[nñ]as)[^.,;]{0,24}(?:azul\w*|morad\w*|violet\w*)",
        r"\b(?:se (?:pone|puso)|esta)[^.,;]{0,16}(?:azul\w*|morad\w*)",
        # en
        r"\bcyanosis\b", r"\bcyanotic\b", r"\bblue (?:lips|tongue|around the mouth)\b",
        r"\b(?:lips|tongue|skin)[^.,;]{0,20}(?:blue|dusky|grey|gray)\b",
        r"\bturning blue\b", r"\bwent blue\b",
        # fr
        r"\bcyanose\w*\b", r"\b(?:levres|langue|peau)[^.,;]{0,20}bleu\w*",
        r"\bdevient bleu\w*", r"\bbleuit\b",
    ),
    "seizure": (
        # es
        r"\bconvulsion\w*", r"\bconvulsiv\w*", r"\bconvulsion\w*",
        r"\bcrisis (?:febril|convulsiva|epileptica)\w*", r"\bha convulsionado\b",
        r"\bataque epileptic\w*", r"\bespasmo\w* febril\w*",
        # en
        r"\bseizur\w*", r"\bconvuls\w*", r"\bfebrile fit\b", r"\bhad a fit\b",
        # fr
        r"\bconvuls\w*", r"\bcrise convulsive\b", r"\bcrise febrile\b",
    ),
    "respiratory_distress": (
        # es
        r"\bquejido\w*\b", r"\bse queja al respirar\b", r"\btiraje\b", r"\bretraccion\w*\b",
        r"\baleteo nasal\b", r"\bse le marcan las costillas\b", r"\bhunde (?:el pecho|las costillas)\b",
        r"\b(?:le cuesta|no puede|dificultad para) respirar\b", r"\brespira (?:muy )?(?:rapid|agitad)\w*",
        r"\bdistres respiratori\w*", r"\bapnea\w*\b", r"\bdeja de respirar\b",
        # en
        r"\bgrunting\b", r"\bchest (?:in)?drawing\b", r"\bretractions?\b", r"\bnasal flaring\b",
        r"\b(?:struggling|working hard|difficulty) (?:to )?breath\w*",
        r"\bcan'?t breathe\b", r"\bapnoea\b", r"\bapnea\b", r"\bstops breathing\b",
        r"\bribs (?:are )?(?:showing|sucking in)\b",
        # fr
        r"\bgeignement\w*\b", r"\bgeint\b", r"\btirage\b", r"\bbattement des ailes du nez\b",
        r"\b(?:du mal|difficulte\w*) a respirer\b", r"\bne respire (?:plus|pas)\b",
        r"\bapnee\w*\b", r"\bdetresse respiratoire\b",
    ),
    "non_blanching_rash": (
        # es
        r"\bno (?:se )?(?:blanquea|blanquean)\b",
        r"\b(?:manchas?|puntos?|erupcion|sarpullido)[^.,;]{0,40}no (?:se )?(?:van|desaparec\w+|blanque\w+)",
        r"\bno desaparec\w+ al (?:presionar|apretar|estirar)\b",
        r"\bpetequia\w*\b", r"\bpurpur\w*\b", r"\bprueba del vaso\b",
        # en
        r"\bnon[- ]?blanching\b", r"\bdoes ?n'?o?t (?:fade|blanch)\b",
        r"\b(?:rash|spots)[^.,;]{0,40}(?:does ?n'?o?t|won'?t) (?:fade|blanch|go away when)",
        r"\bpetechia\w*\b", r"\bpurpur\w*\b", r"\bglass test\b", r"\btumbler test\b",
        # fr
        r"\bne s'?efface(?:nt)? pas\b", r"\bne blanchi(?:t|ssent) pas\b",
        r"\bne disparai(?:t|ssent) pas (?:a la pression|quand)\b",
        r"\bpetechi\w*\b", r"\bpurpur\w*\b", r"\btest du verre\b",
    ),
    "bulging_fontanelle": (
        # es
        r"\bfontanela\w*[^.,;]{0,20}(?:abombad|abultad|tensa|hinchad|salient)\w*",
        r"\bmollera[^.,;]{0,20}(?:abombad|abultad|hinchad|salient)\w*",
        # en
        r"\bbulging fontanel\w*", r"\bfontanel\w*[^.,;]{0,16}(?:bulg|swollen|raised|tense)\w*",
        r"\bsoft spot[^.,;]{0,20}(?:bulg|swollen|raised|tense)\w*",
        # fr
        r"\bfontanelle[^.,;]{0,20}(?:bombee|tendue|gonflee|bombe)\b",
    ),
    "lethargy": (
        # es
        r"\bletargi\w*", r"\bletargic\w*", r"\bno (?:se )?despierta\b", r"\bno hay forma de despertarl\w*",
        r"\bno reacciona\b", r"\bno responde a (?:nada|est[ií]mulos|mi voz|la voz)\b",
        r"\bmuy decaid\w*", r"\bno se mantiene despiert\w*", r"\bmuy flojit\w*", r"\bhipotoni\w*",
        # en
        r"\blethargi\w*", r"\bwon'?t wake\b", r"\bwill not wake\b", r"\bnot waking\b",
        r"\bunresponsive\b", r"\bfloppy\b", r"\bdoes ?n'?o?t respond to\b",
        # fr
        r"\blethargi\w*", r"\bne se reveille pas\b", r"\bne reagit pas\b", r"\btres abattu\w*",
        r"\bhypotoni\w*", r"\bmou et ne reagit\b",
    ),
    "dehydration": (
        # es
        r"\bdeshidrat\w*", r"\bojos hundid\w*", r"\bfontanela hundid\w*", r"\bmollera hundid\w*",
        r"\bllora sin lagrimas\b", r"\bsin lagrimas\b", r"\bboca (?:muy )?seca\b",
        r"\bla piel no vuelve\b",
        # en
        r"\bdehydrat\w*", r"\bsunken (?:eyes|fontanel\w*|soft spot)\b", r"\bno tears\b",
        r"\bdry mouth\b", r"\bskin turgor\b",
        # fr
        r"\bdeshydrat\w*", r"\byeux creux\b", r"\byeux enfonces\b", r"\bfontanelle creuse\b",
        r"\bpleure sans larmes\b", r"\bbouche seche\b",
    ),
    "no_wet_nappy_12h": (
        # es
        r"\bno ha (?:mojado|manchado) (?:el )?pa[nñ]al\b", r"\bpa[nñ]al(?:es)? sec\w*",
        r"\bno (?:orina|hace pis|ha orinado|ha hecho pis)\b", r"\bsin (?:orinar|hacer pis|mojar)\b",
        # en
        r"\bno wet (?:nappy|nappies|diaper|diapers)\b", r"\bdry (?:nappy|nappies|diaper|diapers)\b",
        r"\bhas ?n'?o?t (?:peed|weed|urinated|had a wet)\b", r"\bnot passed urine\b",
        # fr
        r"\bcouches? seches?\b", r"\bpas de couche mouillee\b", r"\bn'?a pas (?:urine|fait pipi)\b",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    code: tuple(re.compile(p) for p in patterns) for code, patterns in _PATTERNS.items()
}

#: The one flag that is computed rather than pattern-matched: it needs the
#: age and the temperature together (NICE NG143 1.2.12), so no single regex
#: can express it.
COMPUTED_CODES = frozenset({"fever_under_3_months"})

# A code in PRIORITY with neither patterns nor a computation is a flag that
# silently never fires; a pattern set with no place in PRIORITY never wins.
assert set(_COMPILED) | COMPUTED_CODES == set(PRIORITY), (
    "red-flag codes and patterns disagree"
)


# --- fever ----------------------------------------------------------------

_FEVER_WORDS = re.compile(
    r"\b(?:fiebre|febril|febricula|destemplad\w*|decimas?\b|temperatura|"
    r"fever|feverish|temperature|"
    r"fievre|febrile|temperature)\b"
)

# A temperature is only read where it cannot be anything else. Two passes:
#
# _TEMPERATURE_MARKED wants a decimal ("38,2") or a unit ("38 C", "38 grados"),
# which no age or duration ever carries.
# _TEMPERATURE_BARE accepts a naked 35..43 but ONLY when it is not followed by
# a unit of its own, and only when the sentence also says "fever". Without
# that guard "mi bebe de 40 dias" and "38 semanas de gestacion" both read as
# a temperature, which is how a newborn's age becomes a fever.
_TEMPERATURE_MARKED = re.compile(
    r"(?<![\d,.])(3[5-9]|4[0-3])(?:[.,](\d))"
    r"|"
    r"(?<![\d,.])(3[5-9]|4[0-3])()\s*(?:o|°|º)?\s*(?:c\b|celsius\b|grados?\b|degres?\b|degrees?\b)"
)
_TEMPERATURE_BARE = re.compile(
    r"(?<![\d,.])(3[5-9]|4[0-3])(?![\d,.])"
    r"(?!\s*(?:mes|month|mois|semana|week|semaine|dia|day|jour|ano|year|an\b|h\b|hora|hour|heure"
    r"|cm|mm|kg|g\b|ml|l\b|%|sg\b|sem\b))"
)

_AGE_MONTHS = re.compile(r"\b(\d{1,2})\s*(?:mes(?:es)?|months?|mois)\b")
_AGE_WEEKS = re.compile(r"\b(\d{1,2})\s*(?:semanas?|weeks?|semaines?)\b")
_AGE_DAYS = re.compile(r"\b(\d{1,3})\s*(?:dias?|days?|jours?)\b")
_NEWBORN = re.compile(r"\b(?:recien nacid\w*|neonat\w*|newborn|nouveau[- ]?nes?)\b")

_HOURS = re.compile(r"\b(\d{1,3})\s*(?:h\b|horas?|hours?|heures?)\b")


def age_months_in(text: str) -> int | None:
    """Age of the child as the parent stated it, in whole months, or None.

    "3 semanas" and "20 dias" both round DOWN to 0 months, which is the safe
    direction: it keeps a neonate under the <3 months rule.
    """
    n = normalize(text)
    if (m := _AGE_MONTHS.search(n)) is not None:
        return int(m.group(1))
    if (m := _AGE_WEEKS.search(n)) is not None:
        return int(m.group(1)) * 7 // 30
    if (m := _AGE_DAYS.search(n)) is not None:
        return int(m.group(1)) // 30
    if _NEWBORN.search(n):
        return 0
    return None


def temperature_in(text: str) -> float | None:
    """Highest temperature stated in the text, in Celsius, or None."""
    n = normalize(text)
    values: list[float] = []
    for a_whole, a_frac, b_whole, b_frac in _TEMPERATURE_MARKED.findall(n):
        whole, frac = (a_whole or b_whole), (a_frac or b_frac)
        if whole:
            values.append(float(f"{whole}.{frac or 0}"))
    if not values and _FEVER_WORDS.search(n):
        values.extend(float(m.group(1)) for m in _TEMPERATURE_BARE.finditer(n))
    return max(values) if values else None


def _effective_age(question: str, age_months: int | None) -> int | None:
    """The age the rules run against.

    The profile's age and the age written in the question can disagree (a
    sibling, a friend's baby, a stale profile). Take the smaller of the two:
    the whole point of the detector is to fail towards "see a doctor", and
    every age-gated rule here gets STRICTER as the age falls.
    """
    stated = age_months_in(question)
    candidates = [a for a in (stated, age_months) if a is not None]
    return min(candidates) if candidates else None


def _fever_flag(question: str, age: int | None) -> RedFlag | None:
    """NICE NG143 1.2.12: under 3 months at 38 C or more is high risk."""
    if age is None or age >= FEVER_AGE_LIMIT_MONTHS:
        return None
    n = normalize(question)
    temp = temperature_in(question)
    if temp is not None and temp >= FEVER_THRESHOLD_C:
        return RedFlag("fever_under_3_months", f"{temp:g} C", age, temp)
    if temp is not None and temp < FEVER_THRESHOLD_C and not _FEVER_WORDS.search(n):
        return None
    if (m := _FEVER_WORDS.search(n)) is not None:
        # The word "fever" from the parent of a baby this young is enough:
        # NG143 1.1.6 says reported parental perception of fever is valid.
        return RedFlag("fever_under_3_months", m.group(0), age, temp)
    return None


def _hours_in(text: str) -> int | None:
    """The largest number of hours the parent mentions, or None."""
    values = [int(m.group(1)) for m in _HOURS.finditer(text)]
    return max(values) if values else None


def detect(
    question: str,
    *,
    locale: str = "es",
    age_months: int | None = None,
) -> RedFlag | None:
    """The one entry point. Returns the highest-priority flag, or None.

    `locale` is accepted for symmetry with the answering surfaces and for
    future language-specific tuning; matching itself is language-agnostic on
    purpose (see the note above _PATTERNS).
    """
    del locale  # matching is language-agnostic; the ANSWER is localized
    if not question or not question.strip():
        return None
    n = normalize(question)
    age = _effective_age(question, age_months)

    hits: dict[str, RedFlag] = {}
    for code, patterns in _COMPILED.items():
        for pattern in patterns:
            if (m := pattern.search(n)) is not None:
                hits[code] = RedFlag(code, m.group(0), age)
                break

    # "no wet nappy" is only a flag past 12 hours (NICE NG9 1.6.1). A parent
    # writing "3 horas sin mojar el panal" is describing a normal morning.
    if "no_wet_nappy_12h" in hits:
        hours = _hours_in(n)
        if hours is not None and hours < 12:
            hits.pop("no_wet_nappy_12h")

    if (fever := _fever_flag(question, age)) is not None:
        hits["fever_under_3_months"] = fever

    for code in PRIORITY:
        if code in hits:
            return hits[code]
    return None


# ---------------------------------------------------------------------------
# The guideline behind each flag.
#
# The red-flag answer skips retrieval entirely (no embedding call, no vector
# search, no model), so it would otherwise be the ONE answer in the product
# with nothing to check it against. These four fields are rendered by the
# same evidence card as a retrieved citation, so a parent who wants to know
# where "38 C under 3 months" comes from can open NG143 and read 1.2.12.
#
# `title` must match a source in enrichment/data/evidence_urgencias_lactante.json
# verbatim; tests/test_red_flags.py asserts it, so a corpus rename cannot
# leave the flag pointing at a source that no longer exists.
# ---------------------------------------------------------------------------

_NG143 = {
    "title": "Fiebre en menores de 5 años: valoración y manejo inicial (NICE NG143)",
    "organization": "National Institute for Health and Care Excellence (NICE)",
    "year": 2021,
    "url": "https://www.nice.org.uk/guidance/ng143",
}
_NG9 = {
    "title": "Bronquiolitis en niños: diagnóstico y manejo (NICE NG9)",
    "organization": "National Institute for Health and Care Excellence (NICE)",
    "year": 2021,
    "url": "https://www.nice.org.uk/guidance/ng9",
}
_NG240 = {
    "title": (
        "Meningitis bacteriana y enfermedad meningocócica: reconocimiento, "
        "diagnóstico y manejo (NICE NG240)"
    ),
    "organization": "National Institute for Health and Care Excellence (NICE)",
    "year": 2024,
    "url": "https://www.nice.org.uk/guidance/ng240",
}
_CG84 = {
    "title": (
        "Diarrea y vómitos por gastroenteritis en menores de 5 años: "
        "diagnóstico y manejo (NICE CG84)"
    ),
    "organization": "National Institute for Health and Care Excellence (NICE)",
    "year": 2009,
    "url": "https://www.nice.org.uk/guidance/cg84",
}
_AEP_CF = {
    "title": "Convulsiones febriles (Protocolos diagnóstico-terapéuticos de la AEP, 2022)",
    "organization": "Asociación Española de Pediatría",
    "year": 2022,
    "url": "https://static.aeped.es/38_0_702f0d52ca.pdf",
}
_AEP_ANAF = {
    "title": "Anafilaxia en Pediatría (Protocolos diagnóstico-terapéuticos de la AEP, 2019)",
    "organization": "Asociación Española de Pediatría",
    "year": 2019,
    "url": "https://static.aeped.es/25_anafilaxia_a74b17c771.pdf",
}
_ERC = {
    "title": "Soporte vital pediátrico: guías 2021 del European Resuscitation Council",
    "organization": "European Resuscitation Council",
    "year": 2021,
    "url": "https://www.resuscitationjournal.com/article/S0300-9572(21)00068-X/fulltext",
}

RED_FLAG_SOURCES: dict[str, dict[str, object]] = {
    "fever_under_3_months": _NG143,
    "non_blanching_rash": _NG240,
    "respiratory_distress": _NG9,
    "cyanosis": _NG9,
    "seizure": _AEP_CF,
    "choking": _ERC,
    "anaphylaxis": _AEP_ANAF,
    "bulging_fontanelle": _NG143,
    "lethargy": _NG143,
    "no_wet_nappy_12h": _NG9,
    "dehydration": _CG84,
}

assert set(RED_FLAG_SOURCES) == set(PRIORITY), "a red flag has no guideline behind it"


def citation_for(flag: RedFlag) -> dict:
    """The flag's guideline, in the shape the chat's evidence card expects.

    Mirrors `evidence_retrieval.evidence_citations_for_response`, minus the
    fields that only make sense for a vector hit: there is no chunk and no
    distance, because nothing was retrieved. `source_id` and `chunk_id` carry
    the flag code so a support question ("where did this come from?") is
    answerable from a log line.
    """
    src = RED_FLAG_SOURCES[flag.code]
    return {
        "tag": "ev_1",
        "source_id": f"red_flag:{flag.code}",
        "chunk_id": f"red_flag:{flag.code}",
        "title": src["title"],
        "organization": src["organization"],
        "year": src["year"],
        "url": src["url"],
        "snippet": "",
    }
