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

Calibration. Over-triggering stops only where the sources say the answer is
a visit, not 112. One case so far: a pause in the sleep of a snoring child of
6 months or more, with no acute illness, no long pause and no other alarm
sign, goes to the RAG, whose sleep sources send it to the pediatrician
(`_sleep_pause_only`).

Head injury and green or bloody vomit (2026-11-11, the #retr4 finding). "Se
ha dado un golpe en la cabeza y ha perdido el conocimiento", "se ha desmayado",
"ha vomitado varias veces" after a knock and "le sale sangre por el oido" all
reached the model; only "no reacciona" fired. Two flags were added, each sign
written next to the corpus source that sends it to the emergency department:

  head_injury            SEUP "Traumatismo craneal" (cited), NHS head injury,
                         HSE emergency department, SBP, Bambino Gesu
  green_or_bloody_vomit  NHS "Diarrhoea and vomiting" (cited), SEUP
                         gastroenteritis, KidsDoc newborn, reflux red flags

and the unconscious or fainted baby with no fall in the message joined
`lethargy` (NHS "What to do if your child has an accident": unconscious, floppy
or does not wake is 999). tests/red_flag_phrasings.py holds how mothers tell
every flag, with her spelling ("q", "se a puesto", "bomita", "inconciente"),
which `_mother_spelling` reads before the patterns; scripts/red_flag_coverage.py
prints the table per flag, against this tree or any git ref.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# Highest first. A question can carry several flags ("she had a fit and her
# lips went blue"); the parent gets one answer, so the most time-critical
# wins. Choking and anaphylaxis are minutes; fever in a neonate is hours.
#
# head_injury sits above seizure and lethargy because it only fires when the
# message tells a knock or a fall: a fit or a faint after one is answered with
# the head-injury reason and the SEUP sheet, not the febrile-seizure protocol.
PRIORITY: tuple[str, ...] = (
    "choking",
    "anaphylaxis",
    "cyanosis",
    "head_injury",
    "seizure",
    "respiratory_distress",
    "non_blanching_rash",
    "bulging_fontanelle",
    "green_or_bloody_vomit",
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

# Breathing that stops. Part of respiratory_distress, kept apart because one
# context the sources give turns it from 112 into a visit to the pediatrician:
# see _sleep_pause_only.
_PAUSES: tuple[str, ...] = (
    # es
    r"\bapnea\w*\b", r"\bdej(?:a|o|aba|ado) de respirar\b", r"\bpar(?:a|o|aba|ado) de respirar\b",
    # en
    r"\bapnoea\w*\b", r"\bapnea\w*\b", r"\bstop(?:s|ped)? breathing\b",
    # fr
    r"\bapnee\w*\b", r"\barret(?:e|ait) de respirer\b",
)

_PATTERNS: dict[str, tuple[str, ...]] = {
    "choking": (
        # es
        r"\batragant\w*", r"\bse (?:le )?atragant\w*", r"\bcuerpo extra[nñ]o\b",
        r"\bse (?:ha )?trag\w+ (?:un|una|el|la)\b", r"\bobstruccion de (?:la )?via aerea\b",
        r"\bmaniobra de heimlich\b", r"\bno puede (?:respirar|toser) (?:desde que|tras)\b",
        # "se le fue por mal sitio" alone is a cough that clears it (ERC: let
        # him cough); it is the flag once he cannot cough.
        r"\bno (?:puede|consigue) ni toser\b",
        r"\b(?:atascad|atorad|trabad|clavad)\w*[^.;]{0,15}\bgarganta\b",
        r"\bpor mal sitio\b[^.;]{0,40}\bno (?:puede|consigue) (?:toser|respirar|llorar)\b",
        # en
        r"\bchok(?:ing|ed|es)\b", r"\bfor?eign body\b", r"\bairway obstruction\b",
        r"\bswallowed a\b", r"\bheimlich\b",
        r"\b(?:can'?t|cannot|unable to) make (?:a|any) (?:sound|noise)\b",
        r"\bstuck in (?:his|her|their|the|its) throat\b",
        # fr
        r"\betouffe\w*\b", r"\bfausse route\b", r"\bcorps etranger\b", r"\ba avale (?:un|une)\b",
        r"\bs'?etrangl\w*", r"\bavale(?:e)? de travers\b",
        r"\bn'?arrive (?:plus|pas) a (?:tousser|crier)\b",
        r"\b(?:coince|bloque)\w* dans (?:la|sa) gorge\b",
    ),
    "anaphylaxis": (
        # es
        r"\banafilaxi\w*", r"\breaccion alergica grave\b", r"\bedema de glotis\b",
        r"\bshock anafilactico\b",
        r"\b(?:se le )?(?:ha )?hinch\w+ (?:la |las |los |el )?(?:cara|lengua|labios|garganta)\b",
        r"\bhinchazon de (?:la )?(?:cara|lengua|labios|garganta)\b",
        r"\badrenalina autoinyect\w*", r"\bautoinyector de adrenalina\b",
        # Hives with the throat or the breath in it (AEP 2019: skin plus a
        # second system is anaphylaxis).
        r"\b(?:ronchas|habones|urticaria)\b[^.;]{0,60}"
        r"\b(?:(?:cuesta|no puede) (?:tragar|respirar)|pitos|silb\w*)",
        r"\b(?:hives|welts)\b[^.;]{0,60}"
        r"\b(?:wheez\w*|(?:trouble|difficulty|struggling)(?: to)? (?:swallow|breath)\w*)",
        r"\b(?:plaques|urticaire)\b[^.;]{0,60}\b(?:mal a (?:avaler|respirer)|siffl\w*)",
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
        r"\b(?:labios|lengua|piel|cara|manos|pies|u[nñ]as|boca)[^.,;]{0,24}"
        r"(?:azul\w*|morad\w*|violet\w*|grisace\w*|gris\b)",
        r"\b(?:se (?:le |les )?(?:ha |han )?(?:pone|ponen|puso|pusieron|puesto)|esta)"
        r"[^.,;]{0,16}(?:azul\w*|morad\w*)",
        # en
        r"\bcyanosis\b", r"\bcyanotic\b", r"\bblue (?:lips|tongue|around the mouth)\b",
        r"\b(?:lips|tongue|skin)[^.,;]{0,20}(?:blue|dusky|grey|gray)\b",
        r"\bturning blue\b", r"\bwent blue\b",
        r"\b(?:turning|turned|went|gone|going|goes) (?:blue|purple|grey|gray)\b",
        # fr
        r"\bcyanose\w*\b", r"\b(?:levres|langue|peau|visage)[^.,;]{0,20}(?:bleu|violet|gris)\w*",
        r"\bdevien\w* (?:bleu|violet|gris)\w*", r"\bbleuit\b",
        r"\b(?:il|elle) est (?:tout|toute|completement) (?:bleu|violet|gris)\w*",
    ),
    "seizure": (
        # es
        r"\bconvulsion\w*", r"\bconvulsiv\w*", r"\bconvulsion\w*",
        r"\bcrisis (?:febril|convulsiva|epileptica)\w*", r"\bha convulsionado\b",
        r"\bataque epileptic\w*", r"\bespasmo\w* febril\w*",
        r"\bojos en blanco\b", r"\bse (?:quedo|puso) rigid\w*",
        r"\bse (?:ha )?(?:quedado|quedo|puesto|puso) (?:rigid|ties)\w*",
        r"\bojos (?:para |hacia )(?:atras|arriba)\b",
        # en
        r"\bseizur\w*", r"\bconvuls\w*", r"\bfebrile fit\b", r"\bhad a fit\b",
        r"\b(?:having|has) a fit\b", r"\bwhole body (?:was |is )?(?:jerking|shaking|twitching)\b",
        r"\beyes? roll(?:ed|ing)? (?:back|up)\b",
        r"\b(?:went|goes|going|gone) (?:completely )?stiff\b",
        # fr
        r"\bconvuls\w*", r"\bcrise convulsive\b", r"\bcrise febrile\b",
        r"\byeux (?:reverses|revulses)\b", r"\bs'?est raidi\w*",
    ),
    "respiratory_distress": (
        # es
        r"\bquejido\w*\b", r"\bse queja al respirar\b", r"\btiraje\b", r"\bretraccion\w*\b",
        r"\baleteo nasal\b", r"\bse le marcan las costillas\b",
        r"\bhunde (?:el pecho|las costillas)\b",
        r"\b(?:le cuesta|no puede|dificultad para) respirar\b",
        r"\brespira (?:muy |super |demasiado |tan )?(?:rapid|agitad)\w*",
        r"\ble cuesta (?:mucho |muchisimo |bastante )respirar\b",
        r"\brespira con (?:mucho |mucha |gran )?(?:esfuerzo|dificultad)\b",
        r"\bdistres respiratori\w*", r"\bno respira\b",
        # en
        r"\bgrunting\b", r"\bchest (?:in)?drawing\b", r"\bretractions?\b", r"\bnasal flaring\b",
        r"\b(?:struggling|working hard|difficulty) (?:to )?breath\w*",
        r"\bcan(?:'?t|not| not) breathe\b",
        r"\bcan(?:'?t|not| not) catch (?:his|her|their|a) breath\b",
        r"\bribs (?:are )?(?:showing|sucking in)\b",
        r"\bbreathing (?:really |very |so |too |extremely )?(?:fast|quickly|rapidly)\b",
        r"\b(?:skin|belly|tummy|chest|stomach)\b[^.,;]{0,25}\b(?:pull|suck|sink|draw)\w* in\b",
        # fr
        r"\bgeignement\w*\b", r"\bgeint\b", r"\btirage\b", r"\bbattement des ailes du nez\b",
        r"\b(?:du mal|difficulte\w*) a respirer\b", r"\bne respire (?:plus|pas)\b",
        r"\bdetresse respiratoire\b",
        r"\bgemi\w*", r"\bn'?arrive (?:plus|pas) a respirer\b",
        r"\brespire (?:tres |trop |si |super |hyper )?(?:vite|rapidement)\b",
        r"\b(?:ventre|cotes|thorax)\b[^.,;]{0,20}\bse (?:creus|rentr)\w*",
        *_PAUSES,
    ),
    "non_blanching_rash": (
        # es
        r"\bno (?:se )?(?:blanquea|blanquean)\b",
        r"\b(?:manchas?|puntos?|erupcion|sarpullido)[^.,;]{0,40}no (?:se )?(?:van|desaparec\w+|blanque\w+)",
        # "manchitas", "puntitos" and the verbs a mother uses for "fade".
        r"\b(?:manch|punt)it\w*[^.,;]{0,40}no (?:se )?(?:van|quitan|borran|desaparec\w+)",
        r"\bno (?:se )?(?:van|quitan|borran) al (?:presionar|apretar|estirar)\b",
        r"\bno desaparec\w+ al (?:presionar|apretar|estirar)\b",
        r"\bpetequia\w*\b", r"\bpurpur\w*\b", r"\bprueba del vaso\b",
        r"\blo del vaso\b[^.;]{0,40}\bno (?:se )?(?:van|quitan|borran|desaparec\w+)",
        # en
        r"\bnon[- ]?blanching\b", r"\b(?:does|do) ?n'?o?t (?:fade|blanch|disappear)\b",
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
        r"\bbulging (?:fontanel\w*|soft spot)",
        r"\bfontanel\w*[^.,;]{0,40}(?:bulg|swollen|raised|tense|puffy)\w*",
        r"\bsoft spot[^.,;]{0,40}(?:bulg|swollen|raised|tense|puffy)\w*",
        # fr
        r"\bfontanelle[^.,;]{0,40}(?:bombee|tendue|gonflee|bombe)\b",
    ),
    "lethargy": (
        # es
        r"\bletargi\w*", r"\bletargic\w*", r"\bno (?:se )?despierta\b",
        r"\bno hay forma de despertarl\w*",
        r"\bno reacciona\b", r"\bno responde a (?:nada|est[ií]mulos|mi voz|la voz)\b",
        r"\bmuy decaid\w*", r"\bno se mantiene despiert\w*", r"\bmuy flojit\w*", r"\bhipotoni\w*",
        r"\bno (?:consigo|puedo|logro) despertarl\w*", r"\bcuesta (?:mucho )?despertarl\w*",
        r"\bno hay (?:manera|quien) de despertarl\w*",
        r"\bno hay quien (?:lo|la|le) despierte\b",
        r"\bno me reconoce\b", r"\bmuneco de trapo\b",
        r"\bno responde cuando (?:la |le |lo )?(?:llamo|hablo|llamamos|hablamos)\b",
        r"\bcuesta (?:muchisimo|much\w+|bastante) despertarl\w*",
        r"\besta (?:muy |tan |super )?floj(?:o|a|ito|ita)\b",
        # Unconscious or fainted, with no fall in the message (a fall makes it
        # head_injury). NHS "What to do if your child has an accident" sends
        # an unconscious, floppy or unwakeable child to 999; KidsDoc sends a
        # faint to 112. Subject-anchored: "casi me desmayo" is the mother, and
        # "de forma inconsciente" is an adverb.
        r"(?<!no )\bse (?:ha |habia )?desmay\w*",
        r"\b(?:ha tenido|tuvo|le (?:ha )?dado|le dio) un desmayo\b",
        r"(?<!no )(?<!no ha )(?<!sin )\bperd\w* el (?:conocimiento|sentido)\b",
        r"\bperdida (?:de )?(?:la )?(?:conciencia|consciencia|conocimiento)\b",
        r"(?<!no )\b(?:esta|estaba|se (?:ha )?quedado|se quedo|se queda|parece) inconscient\w*",
        r"\bse (?:ha )?quedado sin sentido\b",
        # en
        r"\blethargi\w*", r"\bwon'?t wake\b", r"\bwill not wake\b", r"\bnot waking\b",
        r"\bunresponsive\b", r"\bfloppy\b", r"\bdoes ?n'?o?t respond to\b",
        r"\bcan(?:'?t|not| not) (?:\w+ )?(?:wake|rouse)\b", r"\bhard to (?:wake|rouse)\b",
        r"\b(?:won'?t|wouldn'?t) respond\b(?! to (?:the )?(?:antibiotic|treatment|medicine))",
        # "has a limp" is a gait; "is limp" is tone.
        r"\b(?:is|was|'s|very|so|really|all|gone|went) limp\b",
        r"\b(?:he|she|baby|they|it)(?:'s| has| had| just)? (?:passed out|fainted|blacked out)\b",
        r"\band (?:then )?(?:passed out|fainted|blacked out)\b",
        r"(?<!never )\blost consciousness\b", r"\b(?:is|was|went|been|'s) unconscious\b",
        r"(?<!n't )(?<!not )(?<!never )\bknocked out\b",
        # fr
        r"\blethargi\w*", r"\bne se reveille pas\b", r"\bne reagit pas\b", r"\btres abattu\w*",
        r"\bhypotoni\w*", r"\bmou et ne reagit\b",
        r"\bn'?arrive (?:plus|pas) a (?:le |la |l')?reveiller\b", r"\bdifficile a reveiller\b",
        r"\bimpossible de (?:le |la |l')?reveiller\b",
        r"\best (?:tout |tres |completement )?(?:molle?|flasque)\b",
        r"\bs'?(?:est|etait) evanoui\w*", r"(?<!pas )(?<!jamais )\bperdu connaissance\b",
        r"(?<!pas de )(?<!sans )\bperte de connaissance\b",
        r"\best inconscient\w*", r"\b(?:il|elle) est tombee? dans les pommes\b",
    ),
    "dehydration": (
        # es
        r"\bdeshidrat\w*", r"\bojos hundid\w*", r"\bfontanela hundid\w*", r"\bmollera hundid\w*",
        r"\bllora sin lagrimas\b", r"\bsin lagrimas\b", r"\bboca (?:muy )?seca\b",
        r"\bla piel no vuelve\b", r"\bhundid\w* (?:la )?(?:mollera|fontanela)\b",
        # en
        r"\bdehydrat\w*", r"\bsunken (?:eyes|fontanel\w*|soft spot)\b", r"\bno tears\b",
        r"\bdry mouth\b", r"\bskin turgor\b",
        r"\beyes?\b[^.,;]{0,20}\bsunken\b", r"\b(?:cries|crying|cried) without (?:any )?tears\b",
        r"\bmouth (?:is |looks |feels )?(?:really |very |so )?dry\b",
        # fr
        r"\bdeshydrat\w*", r"\byeux creux\b", r"\byeux enfonces\b", r"\bfontanelle creuse\b",
        r"\bpleure sans larmes\b", r"\bbouche seche\b",
        r"\byeux\b[^.,;]{0,15}\b(?:creux|enfonces)\b",
    ),
    "no_wet_nappy_12h": (
        # es
        r"\bno ha (?:mojado|manchado) (?:el )?pa[nñ]al\b",
        r"\bpa[nñ]al(?:es)? (?:esta |sigue |continua |lleva )?(?:todo el dia )?(?:completamente )?sec\w*",
        r"\bno (?:orina|hace pis|ha orinado|ha hecho pis)\b", r"\bsin (?:orinar|hacer pis|mojar)\b",
        r"\bno moja (?:el |los )?pa[nñ]al\w*",
        # en
        r"\bno wet (?:nappy|nappies|diaper|diapers)\b", r"\bdry (?:nappy|nappies|diaper|diapers)\b",
        r"\bhas ?n'?o?t (?:peed|weed|wee'?d|urinated|had a wet)\b", r"\bnot passed urine\b",
        r"\b(?:nappy|nappies|diaper|diapers)\b (?:has |have |had )?(?:been |stayed |remained |is |was |are )?"
        r"(?:still )?(?:completely |totally )?dry\b",
        # fr
        r"\bcouches? seches?\b", r"\bpas de couche mouillee\b", r"\bn'?a pas (?:urine|fait pipi)\b",
        r"\bn'?a pas mouille\b",
        r"\bcouche\w* (?:est |sont |reste |restent )?(?:toujours |encore )?seche",
        r"\bpas de pipi\b",
    ),
    # NHS "Diarrhoea and vomiting": green or yellow-green vomit, blood or
    # something like coffee grounds is A&E or 999. SEUP gastroenteritis
    # ("verdosos, con sangre o como posos de cafe": back to urgencias), KidsDoc
    # newborn ("vomita bilis": urgencias ahora mismo) and the reflux red flags
    # ("vomito bilioso ... emergencia quirurgica") say the same. The colour has
    # to be the vomit's: up to three words between, none of them "y", "mocos"
    # or "caca", so "vomita y tiene mocos verdes" is not it.
    "green_or_bloody_vomit": (
        # es
        r"\b(?:vomit\w*|devuelt\w*|devuelve|regurgit\w*)"
        r"(?: (?!y\b|e\b|o\b|ni\b|no\b|sin\b|nunca\b|pero\b|mocos?\b|cacas?\b|heces\b|pis\b)"
        r"\w+){0,3}?"
        r" (?:verd(?:e|os|us)\w*|bilis|bilios\w*|(?:con |de )?sangre|(?:como )?posos de cafe)\b",
        r"\b(?:sangre|bilis) (?:en|de) (?:el |los |su |sus )?vomit\w*",
        # "vomito y era verde", "ha vomitado y traia sangre": the colour told after it.
        r"\bvomit\w*[^.;]{0,30}\by (?:era|es|estaba|salio|sale)(?: \w+)? (?:verde\w*|bilis)\b",
        r"\bvomit\w*[^.;]{0,30}\by (?:tenia|tiene|traia|trae|llevaba|lleva|habia|hay)"
        r" (?:hilos de |un poco de |algo de )?sangre\b"
        r"(?! en (?:las |la |el |los )?(?:heces|cacas?|pa[nñ]al\w*|deposicion\w*))",
        # en
        r"\b(?:vomit\w*|threw up|throw\w* up|thrown up|puk\w*|spat up|spit\w* up|"
        r"(?:his|her|the|their) sick)"
        r"(?: (?!and\b|but\b|not\b|no\b|never\b|without\b|snot\b|poo\w*|nappy\b|diaper\b)\w+){0,3}?"
        r" (?:green\w*|bile|bilious|blood\w*|coffee grounds?)\b",
        r"\b(?:blood|bile)\b (?:in|on) (?:his |her |the |their )?(?:vomit|sick)\b",
        r"\b(?:vomit\w*|threw up|thrown up|been sick|was sick|puked)\b[^.;]{0,30}"
        r"\b(?:it|the vomit|the sick)(?:'s| is| was| looks?| looked)(?: \w+){0,2}"
        r" (?:green\w*|bloody|blood\w*)\b(?! (?:poo\w*|stools?|nappy|diaper|snot))",
        r"\b(?:vomit\w*|threw up|thrown up|been sick|was sick|puked)\b[^.;]{0,30}"
        r"\b(?:blood|bile) in it\b",
        # fr
        r"\b(?:vomi\w*|rejet\w*|regurgit\w*)"
        r"(?: (?!et\b|mais\b|pas\b|sans\b|jamais\b|morve\b|selles?\b|caca\b)[\w']+){0,3}?"
        r" (?:vert\w*|verdatre\w*|bile|bilieu\w*|sang\b|sanglant\w*|marc de cafe)",
        r"\b(?:sang|bile) dans (?:le |les |ses )?vomi\w*",
        r"\bvomi\w*[^.;]{0,30}\b(?:c'etait|c'est|il y avait|il y a)(?: \w+)?"
        r" (?:vert\w*|du sang|sang)\b(?! dans (?:les |la |ses )?(?:selles|couche\w*))",
    ),
}

#: Blood the baby swallowed from a cracked nipple comes back up and is not a
#: bleed: the reflux red-flag sheet counts hematemesis "no por sangre
#: deglutida". With one of these in the message, blood in the vomit goes to
#: the RAG, whose sources say so; a green vomit still fires.
_SWALLOWED_BLOOD = re.compile(
    r"\bgrieta\w*|\bpezon\w*|\bsangre (?:deglutida|tragada)\b"
    r"|\bcracked nipple\w*|\bswallowed blood\b|\bcrevasse\w*|\bmamelon\w*"
)
_GREEN_OR_BILE = re.compile(r"\bverd(?:e|os|us)\w*|\bbili\w*|\bgreen\w*|\bvert\w*|\bverdatre\w*")

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    code: tuple(re.compile(p) for p in patterns) for code, patterns in _PATTERNS.items()
}

#: The one flag that is computed rather than pattern-matched: it needs the
#: age and the temperature together (NICE NG143 1.2.12), so no single regex
#: can express it.
#: head_injury is computed too: a sign that is an alarm after a knock (a vomit,
#: a sleepy child, a lump) is ordinary without one, so it needs both.
COMPUTED_CODES = frozenset({"fever_under_3_months", "head_injury"})

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
    # The same, the way Spanish mothers say it ("esta ardiendo", "tiene
    # calentura", "la noto muy caliente"), "running a temp" and "fievreux".
    # Subject-anchored like the rest: "el agua esta caliente" is a bath.
    r"|\bcalentura\b|\besta ardiendo\b|\b(?:lo|la|le) noto (?:muy |super )?caliente\b"
    r"|\brunning a (?:temp|temperature|fever)\b|\b(?:has|got) a temp\b"
    r"|\bfievreu\w*"
)

#: "38 y pico" is how a Spanish mother reads a thermometer past 38.
_TEMPERATURE_Y_PICO = re.compile(r"(?<![\d,.])(3[89]|4[0-3]) y (?:pico|algo|medio)\b")

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
    if temp is None and (m := _TEMPERATURE_Y_PICO.search(n)) is not None:
        temp = float(m.group(1))
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


# --- pauses in a snoring child's sleep --------------------------------------

#: From this age the sleep sources treat snoring with pauses as a consult
#: (Familia y Salud, "Trastornos del sueño en el niño de 6 a 12 meses"). Below
#: it the newborn guidance treats a pause as urgent (HealthyChildren, NHS
#: Healthier Together) and NICE NG9 1.2.3 counts under 3 months as a risk.
SLEEP_PAUSE_MIN_AGE_MONTHS = 6

# "tos ronca", "voz ronca" and "esta ronca" are a croupy cough and a hoarse
# voice, which only share the word with snoring.
_SNORING = re.compile(
    r"(?<!tos )(?<!voz )(?<!esta )(?<!quedado )\bronc(?:a|an|aba|aban|ar|ando)\b|\bronquid\w*"
    r"|\bsnor\w*|\bronfl\w*"
)

# What keeps the pause under the emergency rule even in a snoring child: an
# acute respiratory illness (NICE NG9 1.2.1 sends apnoea in bronchiolitis by
# ambulance, and croup and a cold are how it starts) and a long pause
# (Familia y Salud "respira con pausas largas", HealthyChildren "más de 10
# segundos"). Fever is checked with _FEVER_WORDS.
_PAUSE_STAYS_URGENT = re.compile(
    # es
    r"\bbronquiolit\w*|\blaringit\w*|\bestridor\b|\btos\b|\bcatarr\w*|\bresfriad\w*"
    r"|\bconstipad\w*|\bmocos?\b"
    r"|\bpausas? (?:muy |bastante )?larg\w*|\blarg\w* pausas?\b"
    r"|\bmas de (?:10|diez|\d{2}) segundos\b"
    # en
    r"|\bbronchiolit\w*|\bcroup\b|\bstridor\b|\bcough\w*|\bcold\b|\bflu\b"
    r"|\blong (?:pause|gap)s?\b|\bmore than (?:10|ten|\d{2}) seconds\b"
    # fr
    r"|\blaryngit\w*|\btoux\b|\btouss\w*|\brhume\b|\benrhum\w*"
    r"|\blongues? pauses?\b|\bpauses? (?:tres |trop )?longues?\b"
    r"|\bplus de (?:10|dix|\d{2}) secondes\b"
    # es, en, fr
    r"|\bminut\w*"
)

_DISTRESS_WITHOUT_PAUSES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in _PATTERNS["respiratory_distress"] if p not in _PAUSES
)


def _sleep_pause_only(n: str, age: int | None) -> bool:
    """True when the only distress in `n` is a pause in a snoring child's sleep.

    Handoff section 5: "ronca y a veces para de respirar" at 18 months got the
    112 answer. The sleep sources in evidence_respiratorio_sueno.json all send
    it to the pediatrician: AEP EnFamilia ("Mi hijo ronca", "comentárselo a su
    pediatra"), Familia y Salud for 6-12 months and for 1-2 years, and
    HealthyChildren on sleep apnoea ("cuanto antes"). The question then goes to
    the RAG, which holds those sources. Without an age the flag stays: this
    module fails towards the phone call.
    """
    if age is None or age < SLEEP_PAUSE_MIN_AGE_MONTHS:
        return False
    if not _SNORING.search(n) or _PAUSE_STAYS_URGENT.search(n) or _FEVER_WORDS.search(n):
        return False
    return not any(p.search(n) for p in _DISTRESS_WITHOUT_PAUSES)


# --- a knock to the head -----------------------------------------------------
#
# Every sign below is written in the source that makes it an emergency AFTER A
# KNOCK, so it only counts when the message tells one (_HEAD_BLOW):
#
#   lost consciousness, even briefly   NHS head injury (999), SBP, Bambino Gesu
#   vomiting more than once            HSE ("vomita mas de una vez": urgencias),
#                                      SEUP ("vomitos repetidos"), SBP (3+)
#   blood or clear fluid, ear or nose  SEUP, NHS (999), SBP
#   a seizure                          NHS (999), SBP ("convulsion tras el golpe")
#   sleepiness that does not pass      NHS ("no consigue mantenerse despierto"),
#                                      SEUP ("dificultad para despertarlos"),
#                                      SBP ("somnolencia excesiva"); a child who
#                                      is just sleepy may sleep (NHS), so plain
#                                      "tiene sueno" is not it
#   a fall over a metre or down stairs SEUP (>1 m), NHS (>1 m or 5 steps)
#   any knock under 3 months           SEUP ("siempre que tenga menos de 3 meses")
#   a big lump under 1 year, a soft    NHS (under 1: a large lump, swelling or
#   one at any age                     cut, 999 or A&E), Bambino Gesu
#                                      ("hinchazon blanda del craneo")
#
# One vomit after a knock is not here: NHS makes it same-day advice and HSE
# starts at more than one, so it goes to the RAG, which holds both. Blood from
# inside the ear needs no knock in the message (NHS: bleeding from the ears),
# unless an ear infection explains it (NHS ear infections: same-day advice).

_HEAD_BLOW = re.compile(
    # es. "golpe de tos / de calor" is a cough fit and heatstroke; "se le cayo
    # el chupete" and "se cae el pelo" are things falling, not the baby.
    r"\bgolpe(?:s|cit\w*|ad\w*|o)?\b(?! de (?:tos|calor|aire|frio|sol|suerte))"
    r"|\bse golpe\w*|\bcabezazo\w*|\btrompazo\w*|\bporrazo\w*|\bcostalazo\w*|\bcoscorron\w*"
    r"|\bchichon\w*|\btraumatismo\w*"
    r"|\bse (?:ha |habia )?(?:caido|cayo|callo|cae)\b"
    r"(?! (?:el|la|los|las|un|una|unos|unas|su|sus|mi|mis|algo)\b)"
    r"|\b(?:caerse|al caer)\b|\bcaida\b(?! del? (?:pelo|cabello|diente|ombligo|cordon))"
    r"|\bse (?:ha )?(?:dado|dio) (?:con|en|contra)\b|\bdarse (?:con|en|contra)\b"
    # en. "fell asleep" and "fell ill" are not falls.
    r"|\b(?:hit|hitting|bump|bumped|bumping|bang|banged|banging|knock|knocked|smacked)\b"
    r" (?:his |her |their |its |the )?head\b"
    r"|\bhead (?:injury|injuries|bump|knock|trauma)\b"
    r"|\bfell\b(?! (?:asleep|ill|sick|pregnant|in love|for\b))"
    r"|\bfall(?:en|ing|s)? (?:off|from|out|down|over|on|onto)\b|\bhad a (?:fall|tumble)\b"
    r"|\brolled off\b|\bknocked out\b"
    # fr. "tombe malade" is falling ill; "tombe dans les pommes" is a faint.
    r"|\btombe\w*\b(?! (?:malade|enceinte|amoureu\w*|de sommeil|dans les pommes))"
    r"|\bchute\b|\bcogne\w*|\bs'?est tape\w*|\btape la tete\b"
    r"|\b(?:choc|coup) (?:a|sur) la tete\b|\btraumatisme cranien\w*"
)

_HEAD_SIGNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    # vomiting more than once
    r"\bvomit\w*[^.;]{0,20}\b(?:varias|muchas|dos|tres|cuatro|cinco|[2-9]|\d{2}) veces\b",
    r"\bno (?:para|deja) de vomitar\b", r"\b(?:sigue|no para de) vomitando\b",
    r"\bvomit\w* (?:sin parar|una y otra vez|todo el rato|otra vez|de nuevo)\b",
    r"\b(?:ha vuelto|volvio) a vomitar\b",
    r"\b(?:dos|tres|cuatro|varios|muchos|[2-9]|\d{2}) vomitos\b", r"\bvomitos repetidos\b",
    r"\b(?:vomited|been sick|thrown up|threw up|puked|was sick)[^.;]{0,20}\b(?:twice|two times|"
    r"three times|[2-9] times|several times|a few times|more than once|again|repeatedly|"
    r"multiple times)\b",
    r"\bkeeps? (?:on )?(?:vomiting|being sick|throwing up|puking)\b",
    r"\b(?:won'?t|can'?t) stop (?:vomiting|being sick|throwing up)\b",
    r"\b(?:still|repeatedly) (?:vomiting|throwing up|being sick)\b",
    r"\bvomi\w*[^.;]{0,20}\b(?:plusieurs|deux|trois|quatre|[2-9]) fois\b",
    r"\bn'?arrete (?:pas|plus) de vomir\b", r"\bvomit sans arret\b",
    r"\b(?:encore|de nouveau) vomi\b", r"\brevomi\w*", r"\bvomissements (?:repetes|a repetition)\b",
    # blood or clear fluid from the ear or the nose
    r"\b(?:sangre|sangr\w*|liquido\w*)\b[^.;]{0,30}\b(?:oido|oidos|oreja|orejas|nariz)\b",
    r"\b(?:oido|oidos|oreja|nariz)\b[^.;]{0,15}\b(?:sangr\w*|liquido)",
    r"\b(?:blood|bleeding|fluid|liquid)\b[^.;]{0,30}\b(?:ears?|nose)\b",
    r"\b(?:ears?|nose)\b[^.;]{0,15}\b(?:bleed\w*|leak\w*|blood)",
    r"\b(?:sang|saign\w*|liquide)\b[^.;]{0,30}\b(?:oreilles?|nez)\b",
    r"\b(?:oreilles?|nez)\b[^.;]{0,15}\b(?:saign\w*|coule)",
    # sleepiness that does not pass
    # "muy dormido" is a child asleep, which NHS says he may be.
    r"\b(?:muy|super|tan|demasiado) (?:somnolient\w*|adormilad\w*)",
    r"\bsomnolencia (?:excesiva|intensa|que no)\b",
    r"\bmucho sueno\b[^.;]{0,30}\bno se (?:le )?pasa\b", r"\bno se (?:le )?pasa el sueno\b",
    r"\bno (?:se )?(?:mantiene|consigue mantenerse|puede mantenerse|aguanta) despiert\w*",
    r"\bno hay quien (?:lo|la|le) mantenga despiert\w*", r"\bse (?:le )?cierran los ojos\b",
    r"\b(?:very|really|so|unusually|extremely|super) (?:drowsy|sleepy)\b",
    r"\b(?:can'?t|cannot|won'?t|unable to) stay awake\b",
    r"\bkeeps? (?:falling|nodding) (?:asleep|off)\b",
    r"\b(?:tres|super|trop|anormalement) (?:somnolent\w*|endormi\w*)",
    r"\bn'?arrive (?:pas|plus) a rester eveill\w*", r"\bs'endort tout le temps\b",
    r"\bsomnolence (?:excessive|anormale|inhabituelle)\b",
    # a high fall
    r"\b(?:mas de|desde mas de) (?:un|1) metro\b", r"\bpor las escaleras\b",
    r"\bdesde (?:una |la )?(?:ventana|litera|altura)\b",
    r"\b(?:down|off) the stairs\b", r"\bdown a flight\b",
    r"\bmore than (?:a|one|1) (?:metre|meter)\b", r"\bfrom a (?:window|height|bunk)\b",
    r"\bdans les escaliers\b", r"\bplus d'?(?:un|1) metre\b", r"\bd'?une fenetre\b",
))

_HEAD_LUMP = re.compile(
    r"\b(?:chichon\w*|bulto\w*|hinchazon|hinchad\w*|bola|bollo)\b"
    r"|\b(?:lump|swelling|goose ?egg|bump on (?:his|her|their|the) head)\b"
    r"|\b(?:bosse|gonflement|hematome|enflure)\b"
)
_LUMP_SOFT = re.compile(r"\b(?:bland\w*|esponjos\w*|soft|squishy|boggy|spongy|molle?)\b")
_LUMP_BIG = re.compile(r"\b(?:grande|enorme|gran|big|huge|large|massive|grosse?)\b")

_EAR_BLEEDING = re.compile(
    r"\b(?:sangre|sangra\w*)\b[^.;]{0,15}\boidos?\b|\boidos?\b[^.;]{0,10}\bsangr\w*"
    r"|\b(?:blood|bleeding)\b (?:from|out of|coming out of|in) (?:his|her|their|the|its) ears?\b"
    r"|\bears? (?:is |are )?bleeding\b"
    r"|\b(?:sang|saign\w*)\b[^.;]{0,15}\b(?:de|par|dans) l'oreille\b"
)
_EAR_INFECTION = re.compile(r"\botitis\b|\binfeccion de oido\b|\bear infection\b|\botite\b")

#: The age below which SEUP sends any knock to the head to the emergency department.
HEAD_INJURY_ANY_KNOCK_MONTHS = 3
#: The age below which NHS sends a large lump or swelling after a knock to 999
#: or A&E (NICE CG176 behind it puts "large" at over 5 cm). A plain "chichon"
#: is not it: the conversation battery's golpe-en-la-cabeza scenario, at 11
#: months, expects the sources' answer to it.
HEAD_INJURY_BIG_LUMP_MONTHS = 12


# A knock the mother places somewhere else ("se dio un golpe en el dedo", "she
# banged her knee") is not a head injury unless the head is named as well.
_HEAD_WORD = re.compile(
    r"\b(?:cabeza|craneo|frente|nuca|head|forehead|skull|tete|crane|front)\b"
)
_OTHER_PART = re.compile(
    r"\b(?:en|de) (?:el |la |los |las |su |sus )?(?:dedos?|manos?|brazos?|piernas?|rodillas?|pies?"
    r"|codos?|labios?|boca|dientes?|tobillos?|espalda|culete|culo|trasero)\b"
    r"|\b(?:hit|hurt|bumped|banged|knocked|cut|on) (?:his|her|their|the|a) (?:fingers?|hands?"
    r"|arms?|legs?|knees?|foot|feet|elbows?|lips?|mouth|teeth|tooth|toes?|bottom|back)\b"
    r"|\b(?:au|aux|a la|sur (?:le|la|les|son|sa|ses)|cogne (?:le|la|les|son|sa|ses)) (?:doigts?"
    r"|mains?|bras|jambes?|genoux?|pieds?|coudes?|levres?|bouche|dents?|fesses|dos)\b"
)
# "no le sale sangre", "sin vomitar mas", "wasn't sick again", "pas de sang":
# a sign she rules out, read back to the last comma.
_NEGATION_BEFORE = re.compile(r"(?:\b(?:no|sin|ni|nunca|not|never|without|pas|sans)\b|n't)[^,.;]*$")


def _negated(n: str, start: int) -> bool:
    return _NEGATION_BEFORE.search(n[max(0, start - 20):start]) is not None


def _first_sign(n: str, patterns) -> re.Match[str] | None:
    for pattern in patterns:
        for m in pattern.finditer(n):
            if not _negated(n, m.start()):
                return m
    return None


def _head_injury_flag(n: str, age: int | None) -> RedFlag | None:
    """A knock to the head with a sign its sources send to the emergency department.

    Signs and sources are in the table above `_HEAD_BLOW`. The lethargy and
    seizure patterns count as signs after a knock, so "se cayo y no reacciona"
    gets the head-injury answer and its source rather than the generic one.
    """
    ear = _first_sign(n, (_EAR_BLEEDING,))
    if ear is not None and not _EAR_INFECTION.search(n):
        return RedFlag("head_injury", ear.group(0), age)
    if (blow := _HEAD_BLOW.search(n)) is None:
        return None
    if _OTHER_PART.search(n) and not _HEAD_WORD.search(n):
        return None
    if age is not None and age < HEAD_INJURY_ANY_KNOCK_MONTHS:
        return RedFlag("head_injury", blow.group(0), age)
    if (m := _first_sign(n, _HEAD_SIGNS)) is not None:
        return RedFlag("head_injury", m.group(0), age)
    for pattern in (*_COMPILED["lethargy"], *_COMPILED["seizure"]):
        if (m := pattern.search(n)) is not None:
            return RedFlag("head_injury", m.group(0), age)
    if (lump := _HEAD_LUMP.search(n)) is not None:
        under_one = age is None or age < HEAD_INJURY_BIG_LUMP_MONTHS
        if _LUMP_SOFT.search(n) or (under_one and _LUMP_BIG.search(n)):
            return RedFlag("head_injury", lump.group(0), age)
    return None


# --- how a mother spells it at night -----------------------------------------
#
# Read before the patterns, so each pattern keeps one spelling. Only fixes that
# cannot make a sentence mean something else: abbreviations ("q", "xq", "x",
# "d", "tb", "mui"), b for v in the words this module reads ("bomita",
# "conbulsion", "berde"), "desmallado", "inconciente", "reaciona", "abonbada",
# and "a" for "ha" before a participle ("se a puesto", "no a echo pis").
_MOTHER_SPELLING: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), r) for p, r in (
        (r"\b(?:q|k)\b", "que"), (r"\b(?:xq|pq|porq)\b", "porque"), (r"\bx\b", "por"),
        (r"\bd\b(?!')", "de"), (r"\btb\b", "tambien"), (r"\bmui\b", "muy"),
        (r"\bbomit", "vomit"), (r"\bconbuls", "convuls"), (r"\bberde", "verde"),
        (r"desmall", "desmay"), (r"inconcien", "inconscien"), (r"\breaciona", "reacciona"),
        (r"abonbad", "abombad"), (r"\ba echo\b", "ha hecho"), (r"\becho pis\b", "hecho pis"),
        (r"\b(se|le|lo|la|me|te|no|ya|y|i|que|nos|les) a "
         r"(?=\w+(?:ado|ido|ada|ida|ao|to|sto|cho)\b)", r"\1 ha "),
    )
)


def _mother_spelling(n: str) -> str:
    for pattern, replacement in _MOTHER_SPELLING:
        n = pattern.sub(replacement, n)
    return n


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
    n = _mother_spelling(normalize(question))
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

    if "respiratory_distress" in hits and _sleep_pause_only(n, age):
        hits.pop("respiratory_distress")

    vomit = hits.get("green_or_bloody_vomit")
    if (vomit is not None and _SWALLOWED_BLOOD.search(n)
            and not _GREEN_OR_BILE.search(vomit.matched)):
        hits.pop("green_or_bloody_vomit")

    if (head := _head_injury_flag(n, age)) is not None:
        hits["head_injury"] = head

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

# These two live with their topic, not in the urgent-care file: the SEUP sheet
# with the falls (evidence_seguridad.json), the NHS page with digestion
# (evidence_digestivo_piel.json). Each is the source that names the sign and
# sends it to the emergency department.
_SEUP_TCE = {
    "title": "Traumatismo craneal, información para padres (SEUP)",
    "organization": "Sociedad Española de Urgencias de Pediatría (SEUP)",
    "year": None,
    "url": "https://seup.org/wp-content/uploads/2025/08/24_Traumatismo-craneal_nueva.pdf",
}
_NHS_DV = {
    "title": "Diarrhoea and vomiting (NHS)",
    "organization": "NHS (National Health Service, Reino Unido)",
    "year": 2023,
    "url": "https://www.nhs.uk/conditions/diarrhoea-and-vomiting/",
}

RED_FLAG_SOURCES: dict[str, dict[str, object]] = {
    "head_injury": _SEUP_TCE,
    "green_or_bloody_vomit": _NHS_DV,
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
