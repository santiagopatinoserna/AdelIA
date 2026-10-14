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

Languages. Matching is language-agnostic, but a pattern table written from
the Spanish side is not the same as one that knows how a French or an English
parent writes the sentence. The golden-set work (tests/test_red_flags_languages.py)
failed 38 of its first 101 cases against this module, among them
"il a avalé de travers", "her eyes rolled back", "spots that don't fade" (the
plural "don't", where the pattern only knew "doesn't"), "œdème" (a ligature
that accent folding leaves whole), "a 2-month-old" (the hyphen hid the age
from the fever rule), "dos meses" written as words, and a Fahrenheit reading.
Each is now a pattern or a parser rule, and the test file keeps at least two
parent-written positives per flag per language so the next flag cannot ship
in one language only.
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
    parent typing without accents at 3 a.m. is not a miss. The ligatures
    œ and æ are spelled out, because accent folding does not touch them.
    """
    folded = unicodedata.normalize("NFD", text or "")
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = folded.replace("’", "'").replace("ʼ", "'")
    # NFD leaves the ligatures whole, so "œdème de Quincke" and "l'œuf" would
    # never meet a pattern written "oedeme" and "oeuf". French writes them
    # with the ligature far more often than without.
    folded = folded.replace("œ", "oe").replace("æ", "ae")
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
        r"\b(?:can'?t|cannot|unable to) make (?:a|any) (?:sound|noise)\b",
        # fr
        r"\betouffe\w*\b", r"\bfausse route\b", r"\bcorps etranger\b", r"\ba avale (?:un|une)\b",
        r"\bs'?etrangl\w*", r"\bavale(?:e)? de travers\b",
        r"\bn'?arrive (?:plus|pas) a (?:tousser|crier)\b",
    ),
    "anaphylaxis": (
        # es
        r"\banafilaxi\w*", r"\breaccion alergica grave\b", r"\bedema de glotis\b",
        r"\bshock anafilactico\b",
        r"\b(?:se le )?(?:ha )?hinch\w+ (?:la |las |los |el )?(?:cara|lengua|labios|garganta)\b",
        r"\bhinchazon de (?:la )?(?:cara|lengua|labios|garganta)\b",
        r"\badrenalina autoinyect\w*", r"\bautoinyector de adrenalina\b",
        # en
        r"\banaphyla\w*", r"\bepipen\b", r"\bswollen (?:lips|tongue|face|throat)\b",
        r"\bsevere allergic reaction\b",
        r"\b(?:swelling|swelled)(?: up)?\b[^.,;]{0,15}\b(?:lips?|tongue|face|throat)\b",
        r"\b(?:lips?|tongue|face|throat)\b[^.,;]{0,20}\b(?:swelled|swollen|swelling|puffed up)\b",
        # fr
        r"\banaphyla\w*", r"\boedeme de quincke\b", r"\breaction allergique grave\b",
        r"\bgonflement (?:des levres|de la langue|du visage|de la gorge)\b",
        r"\b(?:visage|levres?|langue|gorge)\b[^.,;]{0,25}\b(?:gonfl|enfl)\w+",
    ),
    "cyanosis": (
        # es
        r"\bcianosis\b", r"\bcianotic\w*",
        r"\b(?:labios|lengua|piel|cara|manos|pies|u[nñ]as)[^.,;]{0,24}(?:azul\w*|morad\w*|violet\w*)",
        r"\b(?:se (?:ha )?(?:pone|puso|puesto)|esta)[^.,;]{0,16}(?:azul\w*|morad\w*)",
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
        r"\bojos en blanco\b", r"\bse (?:quedo|puso) rigid\w*",
        # en
        r"\bseizur\w*", r"\bconvuls\w*", r"\bfebrile fit\b", r"\bhad a fit\b",
        r"\beyes? roll(?:ed|ing)? (?:back|up)\b", r"\b(?:went|goes|going|gone) (?:completely )?stiff\b",
        # fr
        r"\bconvuls\w*", r"\bcrise convulsive\b", r"\bcrise febrile\b",
        r"\byeux (?:reverses|revulses)\b", r"\bs'?est raidi\w*",
    ),
    "respiratory_distress": (
        # es
        r"\bquejido\w*\b", r"\bse queja al respirar\b", r"\btiraje\b", r"\bretraccion\w*\b",
        r"\baleteo nasal\b", r"\bse le marcan las costillas\b", r"\bhunde (?:el pecho|las costillas)\b",
        r"\b(?:le cuesta|no puede|dificultad para) respirar\b", r"\brespira (?:muy )?(?:rapid|agitad)\w*",
        r"\bdistres respiratori\w*", r"\bapnea\w*\b", r"\bdeja de respirar\b",
        r"\bno respira\b",
        # en
        r"\bgrunting\b", r"\bchest (?:in)?drawing\b", r"\bretractions?\b", r"\bnasal flaring\b",
        r"\b(?:struggling|working hard|difficulty) (?:to )?breath\w*",
        r"\bcan(?:'?t|not| not) breathe\b", r"\bapnoea\b", r"\bapnea\b", r"\bstops breathing\b",
        r"\bribs (?:are )?(?:showing|sucking in)\b",
        r"\bbreathing (?:really |very |so |too |extremely )?(?:fast|quickly|rapidly)\b",
        r"\b(?:skin|belly|tummy|chest|stomach)\b[^.,;]{0,25}\b(?:pull|suck|sink|draw)\w* in\b",
        # fr
        r"\bgeignement\w*\b", r"\bgeint\b", r"\btirage\b", r"\bbattement des ailes du nez\b",
        r"\b(?:du mal|difficulte\w*) a respirer\b", r"\bne respire (?:plus|pas)\b",
        r"\bapnee\w*\b", r"\bdetresse respiratoire\b",
        r"\bgemi\w*", r"\bn'?arrive (?:plus|pas) a respirer\b",
        r"\brespire (?:tres |trop |si )?(?:vite|rapidement)\b",
        r"\b(?:ventre|cotes|thorax)\b[^.,;]{0,20}\bse (?:creus|rentr)\w*",
    ),
    "non_blanching_rash": (
        # es
        r"\bno (?:se )?(?:blanquea|blanquean)\b",
        r"\b(?:manchas?|puntos?|erupcion|sarpullido)[^.,;]{0,40}no (?:se )?(?:van|desaparec\w+|blanque\w+)",
        r"\bno desaparec\w+ al (?:presionar|apretar|estirar)\b",
        r"\bpetequia\w*\b", r"\bpurpur\w*\b", r"\bprueba del vaso\b",
        # en
        r"\bnon[- ]?blanching\b", r"\b(?:does|do) ?n'?o?t (?:fade|blanch)\b",
        r"\b(?:rash|spots)[^.,;]{0,40}(?:(?:does|do) ?n'?o?t|won'?t) (?:fade|blanch|go away when)",
        r"\bpetechia\w*\b", r"\bpurpur\w*\b", r"\bglass test\b", r"\btumbler test\b",
        r"\b(?:press|roll)\w* (?:a |the )?(?:drinking )?glass\b",
        # fr
        r"\bne s'?efface(?:nt)? pas\b", r"\bne blanchi(?:t|ssent) pas\b",
        r"\bne (?:disparai(?:t|ssent)|part|partent) pas (?:a la pression|quand)\b",
        r"\bpetechi\w*\b", r"\bpurpur\w*\b", r"\btest du verre\b",
        r"\b(?:appuy\w+|appuie|presse\w*|roule\w*)[^.,;]{0,25}\bverre\b",
    ),
    "bulging_fontanelle": (
        # es
        r"\bfontanela\w*[^.,;]{0,40}(?:abombad|abultad|tensa|hinchad|salient)\w*",
        r"\bmollera[^.,;]{0,40}(?:abombad|abultad|hinchad|salient)\w*",
        # en
        r"\bbulging (?:fontanel\w*|soft spot)", r"\bfontanel\w*[^.,;]{0,40}(?:bulg|swollen|raised|tense)\w*",
        r"\bsoft spot[^.,;]{0,40}(?:bulg|swollen|raised|tense)\w*",
        # fr
        r"\bfontanelle[^.,;]{0,40}(?:bombee|tendue|gonflee|bombe)\b",
    ),
    "lethargy": (
        # es
        r"\bletargi\w*", r"\bletargic\w*", r"\bno (?:se )?despierta\b", r"\bno hay forma de despertarl\w*",
        r"\bno reacciona\b", r"\bno responde a (?:nada|est[ií]mulos|mi voz|la voz)\b",
        r"\bmuy decaid\w*", r"\bno se mantiene despiert\w*", r"\bmuy flojit\w*", r"\bhipotoni\w*",
        r"\bno (?:consigo|puedo|logro) despertarl\w*", r"\bcuesta (?:mucho )?despertarl\w*",
        # en
        r"\blethargi\w*", r"\bwon'?t wake\b", r"\bwill not wake\b", r"\bnot waking\b",
        r"\bunresponsive\b", r"\bfloppy\b", r"\bdoes ?n'?o?t respond to\b",
        r"\bcan(?:'?t|not| not) (?:\w+ )?(?:wake|rouse)\b", r"\bhard to (?:wake|rouse)\b",
        # fr
        r"\blethargi\w*", r"\bne se reveille pas\b", r"\bne reagit pas\b", r"\btres abattu\w*",
        r"\bhypotoni\w*", r"\bmou et ne reagit\b",
        r"\bn'?arrive (?:plus|pas) a (?:le |la |l')?reveiller\b", r"\bdifficile a reveiller\b",
        r"\bimpossible de (?:le |la |l')?reveiller\b", r"\best (?:tout |tres |completement )?(?:molle?|flasque)\b",
    ),
    "dehydration": (
        # es
        r"\bdeshidrat\w*", r"\bojos hundid\w*", r"\bfontanela hundid\w*", r"\bmollera hundid\w*",
        r"\bllora sin lagrimas\b", r"\bsin lagrimas\b", r"\bboca (?:muy )?seca\b",
        r"\bla piel no vuelve\b",
        # en
        r"\bdehydrat\w*", r"\bsunken (?:eyes|fontanel\w*|soft spot)\b", r"\bno tears\b",
        r"\bdry mouth\b", r"\bskin turgor\b",
        r"\beyes?\b[^.,;]{0,20}\bsunken\b", r"\b(?:cries|crying|cried) without (?:any )?tears\b",
        # fr
        r"\bdeshydrat\w*", r"\byeux creux\b", r"\byeux enfonces\b", r"\bfontanelle creuse\b",
        r"\bpleure sans larmes\b", r"\bbouche seche\b",
    ),
    "no_wet_nappy_12h": (
        # es
        r"\bno ha (?:mojado|manchado) (?:el )?pa[nñ]al\b",
        r"\bpa[nñ]al(?:es)? (?:esta |sigue |continua |lleva )?(?:todo el dia )?(?:completamente )?sec\w*",
        r"\bno (?:orina|hace pis|ha orinado|ha hecho pis)\b", r"\bsin (?:orinar|hacer pis|mojar)\b",
        # en
        r"\bno wet (?:nappy|nappies|diaper|diapers)\b", r"\bdry (?:nappy|nappies|diaper|diapers)\b",
        r"\bhas ?n'?o?t (?:peed|weed|wee'?d|urinated|had a wet)\b", r"\bnot passed urine\b",
        r"\b(?:nappy|nappies|diaper|diapers)\b (?:has |have |had )?(?:been |stayed |remained |is |was |are )?"
        r"(?:still )?(?:completely |totally )?dry\b",
        # fr
        r"\bcouches? seches?\b", r"\bpas de couche mouillee\b", r"\bn'?a pas (?:urine|fait pipi)\b",
        r"\bn'?a pas mouille\b", r"\bcouche\w* (?:est |sont |reste |restent )?(?:toujours |encore )?seche",
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
    # How a parent says "fever" without the word. NG143 1.1.6 treats the
    # parent's perception as valid, and "feels hot" / "il est brulant" is
    # what an English or French parent types before they reach for a
    # thermometer. Subject-anchored in both languages ("she feels hot", "il
    # est chaud", never "the bath water feels hot" or "l'eau est chaude") so
    # a bath-temperature question is not a fever.
    r"|\b(?:she|he|baby|forehead|head|skin|body) (?:really |just |still )?feels? "
    r"(?:really |very |so |quite |extremely )?hot\b|\bfeels? hot to (?:the )?touch\b"
    r"|\bburning (?:hot|up)\b"
    r"|\b(?:il|elle) est (?:tres |tout |bien |vraiment )?chaud(?:e)?\b|\bbrulant\w*"
)

#: A thermometer in the sentence makes a bare 35..43 a reading, the same way
#: the word "fever" does: "le thermometre indique 38".
_THERMOMETER = re.compile(r"\b(?:thermometer|termometro|thermometre)\b")

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
# English-speaking parents read Fahrenheit. Only a number with its own unit is
# taken ("100.8 F", "101°F"): a bare 100 is a weight in grams, a count, a price.
_TEMPERATURE_F = re.compile(
    r"(?<![\d,.])(9[5-9]|10[0-9])(?:[.,](\d))?\s*(?:°|º)?\s*(?:f\b|fahrenheit\b)"
)
_TEMPERATURE_BARE = re.compile(
    r"(?<![\d,.])(3[5-9]|4[0-3])(?![\d,.])"
    r"(?!\s*(?:mes|month|mois|semana|week|semaine|dia|day|jour|ano|year|an\b|h\b|hora|hour|heure"
    r"|cm|mm|kg|g\b|ml|l\b|%|sg\b|sem\b))"
)

# "[\s-]*" and not "\s*": "my 2-month-old" and "a 6-week-old" are how English
# writes an age, and before this a hyphen hid the age from the fever rule.
_AGE_MONTHS = re.compile(r"\b(\d{1,2})[\s-]*(?:mes(?:es)?|months?|mois)\b")
_AGE_WEEKS = re.compile(r"\b(\d{1,2})[\s-]*(?:semanas?|weeks?|semaines?)\b")
_AGE_DAYS = re.compile(r"\b(\d{1,3})[\s-]*(?:dias?|days?|jours?)\b")

# "mi bebe de dos meses" is how a parent writes it at least as often as "2
# meses", in all three languages. Only a number word directly before an age
# unit is read, so "once a day" and "un poco" never become a 1 or an 11.
_NUMBER_WORDS: dict[str, int] = {
    "un": 1, "uno": 1, "una": 1, "one": 1,
    "dos": 2, "deux": 2, "two": 2,
    "tres": 3, "trois": 3, "three": 3,
    "cuatro": 4, "quatre": 4, "four": 4,
    "cinco": 5, "cinq": 5, "five": 5,
    "seis": 6, "six": 6,
    "siete": 7, "sept": 7, "seven": 7,
    "ocho": 8, "huit": 8, "eight": 8,
    "nueve": 9, "neuf": 9, "nine": 9,
    "diez": 10, "dix": 10, "ten": 10,
    "once": 11, "onze": 11, "eleven": 11,
    "doce": 12, "douze": 12, "twelve": 12,
}
_NUMBER_WORD_BEFORE_AGE_UNIT = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
    r"(?=[\s-]*(?:mes(?:es)?|months?|mois|semanas?|weeks?|semaines?|dias?|days?|jours?)\b)"
)
_NEWBORN = re.compile(r"\b(?:recien nacid\w*|neonat\w*|newborn|nouveau[- ]?nes?)\b")

_HOURS = re.compile(r"\b(\d{1,3})\s*(?:h\b|horas?|hours?|heures?)\b")


def age_months_in(text: str) -> int | None:
    """Age of the child as the parent stated it, in whole months, or None.

    "3 semanas" and "20 dias" both round DOWN to 0 months, which is the safe
    direction: it keeps a neonate under the <3 months rule.

    Known limit, kept on purpose: a DURATION written like an age ("lleva 2
    dias con fiebre", "fever for two days") reads as an age, and so makes the
    fever rule fire for an older baby. Digits always did this; number words
    ("dos", "two", "deux") now do too. Telling "mi bebe de dos semanas con
    fiebre" (a neonate) from "dos semanas con fiebre" (a duration) takes more
    than a regex, and the wrong answer in the neonate's direction is the one
    this module exists to avoid. A false positive costs a phone call.
    """
    n = _NUMBER_WORD_BEFORE_AGE_UNIT.sub(lambda m: str(_NUMBER_WORDS[m.group(1)]), normalize(text))
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
    for m in _TEMPERATURE_F.finditer(n):
        fahrenheit = float(f"{m.group(1)}.{m.group(2) or 0}")
        values.append(round((fahrenheit - 32) * 5 / 9, 1))
    if not values and (_FEVER_WORDS.search(n) or _THERMOMETER.search(n)):
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
