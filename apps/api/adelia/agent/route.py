"""The `route` node: what does the mother want? (docs/specs/AGENT_GRAPH.md)

Two layers, in this order:

1. `route_by_rules`: deterministic, free, es/en/fr. Decides only when the
   message is unambiguous and returns None otherwise.
2. `route_by_model`: one call to a small model with a strict JSON-only
   prompt, validated with pydantic. Any failure to produce a valid decision
   falls back to `plan`, the path with the most safeguards, never to `other`.

`route` chains them. Red flags are NOT evaluated here: `guard` runs before
`route` on every surface and a flagged message never reaches this module.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from adelia.clinical.red_flags import age_months_in, normalize, temperature_in
from adelia.config import settings
from adelia.enrichment.profile_service import ProfileFacts
from adelia.llm import (
    anthropic_text,
    content_text,
    get_anthropic_client,
    get_mistral_client,
    uses_anthropic,
)
from adelia.services import usage

logger = logging.getLogger(__name__)

Intent = Literal["plan", "question", "record", "track", "clarify", "other"]
Via = Literal["rule", "model", "fallback"]
#: Where the turn sits in the conversation (agent/conversation.py). Only the
#: model says it, and only when it was called with the thread.
Turn = Literal["new", "follow_up", "correction"]
TURNS: tuple[str, ...] = ("new", "follow_up", "correction")
#: The longest search query taken from the model (conversation.MAX_QUERY_CHARS).
SEARCH_QUERY_CHARS = 1000

INTENTS: tuple[str, ...] = ("plan", "question", "record", "track", "clarify", "other")


class RouteDecision(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    missing: list[str] = Field(default_factory=list)
    via: Via
    #: With the thread only: the model's reading of the turn, and her question
    #: rewritten to stand alone. Optional and read apart from the rest, so a
    #: bad value costs these two fields and never the intent.
    turn: Turn | None = None
    search_query: str | None = None
    #: Why a fallback is one ("timeout", "error:<type> <status>", "invalid"); set by
    #: the code, never read from the model's JSON. The battery reports it (2026-11-11).
    reason: str | None = None


# --- rules ------------------------------------------------------------------
#
# Patterns are matched on `red_flags.normalize` output (lowercase, no
# accents), all languages together, as the red-flag detector does: the
# session locale picks the language of the answer, not of the mother.

# A number with an optional decimal part and an optional unit right after it.
# "37,8", "3 h", "120 ml", "2 bottles". The unit list is what a parent writes
# in a diary line, not a clinical vocabulary.
_MEASUREMENT = re.compile(
    r"(?<![\w,.])\d{1,3}(?:[.,]\d{1,2})?\s*"
    r"(?:°|º)?\s*(?:c\b|grados?\b|degres?\b|degrees?\b|h\b|horas?\b|hours?\b|heures?\b|"
    r"min\b|minutos?\b|minutes?\b|ml\b|cc\b|onzas?\b|oz\b|g\b|gramos?\b|grams?\b|kg\b|"
    r"tomas?\b|biberon(?:es)?\b|biberons?\b|bottles?\b|feeds?\b|cacas?\b|deposicion(?:es)?\b|"
    r"pa[nñ]al(?:es)?\b|couches?\b|nappies\b|nappy\b|diapers?\b|veces\b|fois\b|times\b|"
    r"siestas?\b|naps?\b|siestes?\b)?"
)
# A past-tense report, as a mother writes it: Spanish compound past ("ha
# tenido", "se ha tomado", "le he dado"), French passé composé ("a dormi",
# "a bu", "a eu"), English simple past ("had", "slept", "drank").
_PAST_REPORT = re.compile(
    r"\b(?:(?:se |le |me )?(?:ha|he|hemos|han) (?:\w+ ){0,2}?(?:tenido|dormido|comido|tomado|"
    r"bebido|hecho|vomitado|puesto|dado|mamado|subido|bajado|pesado|medido|durado|"
    r"estado|despertado|llorado|cenado|desayunado|merendado|cagado|mojado|manchado)\b"
    r"|\bhoy (?:ha|se ha|le he|he)\b"
    r"|\b(?:(?:il|elle|on|je|j'|lui) ?)?(?:a|ai|avons|ont) (?:\w+ ){0,2}?"
    r"(?:dormi|bu|mange|eu|fait|pris|vomi|pese|tete|pleure|donne|mis|regurgite)\b"
    r"|\b(?:had|slept|drank|ate|took|weighed|pooped|vomited|napped|fed|nursed|threw up|"
    r"woke up|spat up|measured|gave)\b)"
)

# "What do I do?", in the words a mother uses.
_PLAN_ASK = re.compile(
    r"\b(?:que hago|que puedo hacer|que debo hacer|que deberia hacer|que podemos hacer|"
    r"como (?:le |lo |la )?(?:ayudo|alivio|calmo|puedo ayudar|puedo aliviar|puedo calmar)\w*|"
    r"no se que hacer|no sabemos que hacer|que le (?:doy|puedo dar|damos|pongo|puedo poner)|"
    r"debo preocuparme|deberia preocuparme|hago algo|tengo que hacer algo|"
    r"que faire|comment (?:l'|la |le )?(?:aider|soulager|calmer)|"
    r"je ne sais (?:plus|pas) quoi faire|"
    r"what (?:should|can|do) (?:i|we) do|how (?:do|can) (?:i|we) help|"
    r"what (?:should|can) i give)\b"
)
# Worry markers: a symptom plus one of these is a plan even without "que hago".
_WORRY = re.compile(
    r"\b(?:me preocupa|estoy (?:muy |un poco |bastante )?preocupad\w*|me tiene preocupad\w*|"
    r"tengo miedo|me asusta|me da miedo|no para de|no deja de|"
    r"lleva (?:\w+ ){1,2}(?:dias?|horas?|noches?|semanas?)|desde hace|"
    r"je m'inquiete|inquiet\w*|j'ai peur|n'arrete pas|depuis (?:\w+ )?jours?|"
    r"i'?m worried|worried|scared|keeps|won'?t stop|for (?:\w+ )?days)\b"
)
_SYMPTOM = re.compile(
    r"\b(?:fiebre|febricula|decimas|mocos?|tos|tose|tosiendo|vomit\w*|diarrea|cacas?|"
    r"estre[nñ]i\w*|llor\w*|granitos|granos|sarpullido|erupcion|eccema|dermatitis|colico\w*|"
    r"gases|regurgit\w*|no come|no quiere comer|no duerme|se despierta|ronch\w*|manchas?|"
    r"oido|dientes|babea|hipo|congestion|resfri\w*|catarro|costra lactea|legañas|leganas|"
    r"rhume|toux|tousse|fievre|diarrhee|constip\w*|pleure|boutons|rougeurs|eczema|coliques|"
    r"ne mange|ne dort|nez bouche|"
    r"fever|cough\w*|cold|snot|runny nose|diarrhoea|diarrhea|constipat\w*|cry\w*|cries|rash|"
    r"spots|colic|spit\w* up|spitting up|reflux|won'?t eat|not eating|not sleeping|"
    r"wakes up|teeth\w*)\b"
)

# A fact or an explanation, not an action: "is it normal", "at what age".
_FACT_ASK = re.compile(
    r"\b(?:es normal que|es normal si|a que edad|a partir de que edad|desde cuando|"
    r"hasta cuando|cuando (?:se |le |les |puede|puedo|empiez\w*|hay|toca|dejan|deja)|"
    r"que es (?:la|el|un|una|eso de)\b|que significa|por que (?:los|las|el|la) bebes?|"
    r"cuant[oa]s? \w+ (?:debe|deberia|tiene que|suele|suelen|es normal|hay que|"
    r"necesita|toma|tienen que)|"
    r"is it normal|at what age|when (?:can|do|does|should)|what is (?:a|the)|"
    r"why do babies|how (?:much|many) \w+ should|is (?:that|this) normal|"
    r"est-ce normal|c'est normal|a quel age|a partir de quel age|"
    r"quand (?:est-ce|peut|peut-on|commence\w*)|qu'est-ce que|c'est quoi|combien de \w+ doit)\b"
)

# The child's own data: curves, vaccines due, reports, lab results, record.
_OWN_DATA = re.compile(
    r"\b(?:percentil\w*|curvas? de (?:peso|talla|crecimiento)|"
    r"vacunas? (?:que )?le (?:toca|tocan|falta|faltan|queda|quedan|corresponde\w*)|"
    r"le tocan? (?:las? |alguna )?vacunas?|proximas? vacunas?|siguiente vacuna|"
    r"que vacunas (?:tiene|lleva) puestas|"
    r"(?:ultimo|ultima) (?:informe|analitica|revision|visita|peso|talla|consulta)|"
    r"informe del? (?:pediatra|hospital|alta|neonato|urgencias)|"
    r"analitica\w*|analisis de sangre|expediente|historial|"
    r"resultados? (?:de|del) (?:la |el |los |las )?(?:analitica|analisis|sangre|prueba)|"
    r"que ponia en|cuanto (?:pesaba|media|peso|midio) (?:en|el|la|hace)|"
    r"percentiles?|growth curve|vaccines? (?:are |is )?due|which vaccines|"
    r"last (?:report|blood test|check-?up|visit|weight)|blood (?:test|work) results?|"
    r"(?:her|his) (?:records?|file|chart)|medical record|"
    r"courbe de (?:poids|croissance|taille)|"
    r"vaccins? (?:qui )?(?:lui )?(?:restent?|manquent?|a faire)|prochains? vaccins?|"
    r"dernier (?:bilan|compte rendu|rapport)|dernieres? analyses?|analyses? de sang|"
    r"dossier medical|son dossier)\b"
)

# What only the tools do (build step 5): briefings and profile fixes (write
# tools, behind a confirmation card), clinical trials and drug interactions
# (read tools). Not a plan and not a fact question: a contract answer would
# never run the tool, so these go to the tool loop whatever the classifier
# says, or fails to say.
_TOOL_ASK = re.compile(
    r"\b(?:briefing|"
    r"(?:prepara|preparame|genera|generame|haz|hazme|crea|creame|make|prepare|fais|faire)"
    r" (?:\w+ ){0,2}?(?:informe|resumen|summary|report|resume|rapport|compte rendu)|"
    r"fecha de nacimiento|naci(?:o|do|da) el|date de naissance|date of birth|born on|"
    r"(?:guarda|guardame|guardar|actualiza|apunta) (?:\w+ ){0,3}?perfil|en su perfil|"
    r"in (?:her|his) profile|dans son profil|"
    r"ensayos? clinicos?|clinical trials?|essais? cliniques?|"
    r"interacci\w+ (?:entre|con)|interactions? (?:between|with|entre|avec))\b"
)

# Out of scope: the mother or another adult as the patient, a pet, the
# weather, a joke. Guarded by _BABY_REF: a message that also names the baby
# is never `other` by rule.
_OUT_OF_SCOPE = re.compile(
    r"\b(?:me duele|me he (?:hecho|cortado|quemado)|me tomo\b|"
    r"tengo (?:mucha |mucho |un poco de |bastante )?(?:fiebre|tos|dolor|migrana|la regla|ansiedad|"
    r"insomnio|mocos|diarrea|nauseas)\b|"
    r"mi (?:marido|pareja|madre|padre|suegra|suegro|abuela|abuelo|jefe|hermano|hermana|"
    r"amiga|amigo|vecina|vecino) (?:tiene|esta|lleva|se ha|ha)\b|"
    r"mi (?:perro|perra|gato|gata|hamster|conejo|loro)\b|(?:el|al) (?:perro|gato)\b|"
    r"(?:la|a la) (?:perra|gata)\b|"
    r"que tiempo (?:va a )?hace\w*|va a llover|pronostico|chiste|cuentame (?:un|una|algo)|"
    r"receta de|quien gano|partido de|loteria|horoscopo|bitcoin|"
    r"my (?:husband|partner|wife|mother|father|dog|cat|boss)\b|"
    r"i have a (?:headache|fever|cough|cold)|tell me a joke|weather|"
    r"mon (?:mari|chien|chat|copain|pere)\b|ma (?:chienne|chatte|mere|femme)\b|"
    r"j'ai mal|une blague|la meteo)\b"
)
_BABY_REF = re.compile(
    r"\b(?:bebe|beba|nino|nina|hijo|hija|peque\w*|lactante|recien nacid\w*|"
    r"baby|son|daughter|toddler|infant|newborn|"
    r"mon fils|ma fille|le petit|la petite|nourrisson|"
    r"\d+ ?(?:meses|mes|months?|mois|semanas?|weeks?|semaines?))\b"
)

# Topics whose answer changes with the age: fever, how much to feed, sleep.
_NEEDS_AGE = re.compile(
    r"\b(?:fiebre|febricula|decimas|temperatura|destemplad\w*|fever|fievre|"
    r"cuant[oa]s? (?:ml|mililitros|onzas|tomas|gramos|biberones|cucharadas)|"
    r"cuanta (?:leche|cantidad)|cuanto (?:tiene que|debe|deberia) (?:comer|tomar|beber)|"
    r"cantidad de (?:leche|biberon)|ml por toma|"
    r"how (?:much|many) (?:ml|oz|ounces|feeds|bottles|milk)|"
    r"combien de (?:ml|biberons|lait)|"
    r"dormir|duerme|duerma|sue[nñ]o|siestas?|horas de sueno|se despierta|despertares|"
    r"sleep\w*|naps?|wakes? up|dort|dorme|sommeil|siestes?|se reveille)\b"
)


# A fever reported about the child, with somebody HAVING it, as opposed to a
# question about fever itself ("a partir de cuantos grados es fiebre", "what
# is a normal temperature"). Only a report gets asked for the thermometer
# reading (build step 3): 39 C or more at 3-6 months is an amber sign in
# NICE NG143, so the number changes the answer. Subject- or verb-anchored on
# purpose: a bare "con fiebre" or "with a fever" is as often a general
# question ("can a baby with a fever be bathed?").
_FEVER_REPORT = re.compile(
    r"\b(?:(?:tiene|tenia|ha tenido|tuvo|le ha (?:subido|dado|vuelto)|le sube|"
    r"le esta subiendo|vuelve a tener|sigue con|esta con) (?:\w+ ){0,2}?"
    r"(?:fiebre|febricula|decimas|temperatura|calentura)"
    r"|(?:esta|se nota|lo noto|la noto|le noto) (?:muy |un poco |algo )?"
    r"(?:destemplad\w*|caliente|ardiendo|calenturient\w*)"
    r"|(?:she|he|baby|son|daughter|it) (?:has|had|has had|is running|got) (?:a |an )?"
    r"(?:\w+ )?(?:fever|temperature)"
    r"|(?:she|he|baby|it) (?:feels|is|felt) (?:very |really |a bit )?(?:hot|feverish)"
    r"|(?:il|elle|bebe|fils|fille) (?:a|avait|a eu|fait) (?:de la |une |un peu de )?"
    r"(?:\w+ )?(?:fievre|temperature)"
    r"|(?:il|elle|bebe) (?:est|semble) (?:tres |un peu )?(?:chaud|brulant|fievreux)\w*"
    r")\b"
)

# She says there is NO fever: «no tiene fiebre» is not a report to ask the
# thermometer about (the battery, 2026-11-10, after vomiting).
_NO_FEVER = re.compile(
    r"\bno (?:tiene|tenia|ha tenido|tuvo|le ha (?:subido|dado)|le sube) (?:\w+ ){0,2}?"
    r"(?:fiebre|febricula|decimas|temperatura|calentura)\b"
)

# A plausible body temperature written bare ("fiebre de 39, que hago"). The
# guard's parser (red_flags.temperature_in) rejects a bare number followed by
# a comma on purpose, to keep ages and weeks out of the fever rules; here the
# only question is whether she already told us the number, so any 35-42 next
# to her fever report counts and she is not asked for it again.
_BARE_READING = re.compile(
    r"(?<![\d,.])(?:3[5-9]|4[0-2])(?:[.,]\d)?(?![\d])"
    r"(?!\s*(?:dias?|semanas?|meses|mes\b|horas?|h\b|min|days?|weeks?|months?|hours?|"
    r"jours?|semaines?|mois|heures?|ml|kg|g\b|cm))"
)


def _has_reading(message: str, n: str) -> bool:
    return temperature_in(message) is not None or bool(_BARE_READING.search(n))


# How a mother in a hurry writes, read as the words the rules know (the
# conversation battery, 2026-11-10: «ha vomitado 3 veces esta mañana q hago»
# became a diary line to note, because «q hago» was not «que hago»). Whole
# words only, on normalized text: common Spanish chat shorthand, and «la
# guarde» for the nursery. The clinical guard reads her text as she wrote it.
_SHORTHAND: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:xq|pq|porq|x q)\b"), "por que"),
    # Not «k»: «vitamina K» is a newborn topic.
    (re.compile(r"\b(?:q|ke)\b"), "que"),
    (re.compile(r"\b(?:tb|tmb|tbn)\b"), "tambien"),
    (re.compile(r"\bdsd\b"), "desde"),
    (re.compile(r"\bxa\b"), "para"),
    (re.compile(r"\bbb\b"), "bebe"),
    (re.compile(r"\b(en|a|de) la guarde\b"), r"\1 la guarderia"),
)


def read_shorthand(n: str) -> str:
    """Normalized text with her shorthand spelled out (`red_flags.normalize` first)."""
    for pattern, word in _SHORTHAND:
        n = pattern.sub(word, n)
    return n


# "Why...?" opening the message, or after "y" / "pero": «xq se despierta tanto».
# Inside a statement («no come porque le duelen») it is not a question.
_WHY_ASK = re.compile(r"(?:^|[¿?.!]\s*|\b(?:y|pero) )por que\b|^(?:why|pourquoi)\b")
# "...es normal?" at the end: the fact question written after the fact.
_NORMAL_AT_END = re.compile(r"\b(?:es normal|is (?:that|this|it) normal|c'est normal)\W*$")
# How much he should sleep or eat: a fact, the age comes from her profile.
_HOW_MUCH_SHOULD = re.compile(
    r"\bcuant[oa]s? (?:tiene que|debe|deberia|necesita|suele) "
    r"(?:dormir|comer|tomar|beber|mamar|pesar|medir)\b"
)
# "Something is wrong" with nothing she can describe yet (AGENT_GRAPH.md,
# `clarify`: «le pasa algo» sin síntoma). Searched as written it finds
# nothing and refuses; a pediatric nurse asks how he is and since when.
_VAGUE_WORRY = re.compile(
    r"\b(?:le pasa algo|algo (?:le pasa|raro|extrano)|no se (?:lo )?que le pasa|"
    r"something(?:'s| is) (?:wrong|off|not right)|not (?:himself|herself)|"
    r"je ne sais pas ce qu'(?:il|elle) a|(?:il|elle) a quelque chose|"
    r"quelque chose ne va pas)\b"
)
#: In the classifier's words (and tests/data/routing_es.json); agent/graph asks it.
_VAGUE_ASKS = ["symptom"]
#: A drug or a dose (conversation.py asks nothing about one, audit 3.1).
_DRUG = re.compile(
    r"\b(?:dosis|mg|paracetamol|ibuprofeno|apiretal|dalsy|jarabe|medicamento|medicina|"
    r"melatonina|antibiotico|supositorio|dose|medicine|medication|syrup|melatonin|"
    r"doliprane|sirop|medicament|gotas|drops|gouttes|"
    # A medicine asked for without its name: «algo para el dolor».
    r"(?:algo|something|quelque chose) (?:para|for|contre|pour) (?:el |la |the |sa |son )?"
    r"(?:dolor|fiebre|pain|fever|douleur|fievre))\b"
)
# A weight or a length is noted in the present: «hoy pesa 8,4 kg», «ya mide 72 cm».
_PRESENT_MEASURE = re.compile(
    r"\b(?:pesa|mide|weighs|measures|pese|mesure) \d{1,3}(?:[.,]\d{1,3})? ?"
    r"(?:kg|kilos?|g|gramos|grams?|cm|centimetros|lbs?|pounds?)\b"
)


def _age_is_known(message_n: str, facts: ProfileFacts | None) -> bool:
    if facts is not None and facts.age_months is not None:
        return True
    return age_months_in(message_n) is not None


def _fact_ask(n: str) -> bool:
    return bool(_FACT_ASK.search(n) or _WHY_ASK.search(n) or _NORMAL_AT_END.search(n)
                or _HOW_MUCH_SHOULD.search(n))


def _asks_something(n: str) -> bool:
    """A question, with or without its question mark («cuanto apiretal le doy»)."""
    return ("?" in n or "¿" in n or bool(_PLAN_ASK.search(n)) or _fact_ask(n)
            or bool(_QUESTION_OPENING.search(n.lstrip("¿¡( "))))


def route_by_rules(
    message: str,
    *,
    locale: str = "es",
    has_account: bool = False,
    facts: ProfileFacts | None = None,
) -> RouteDecision | None:
    """Deterministic routing, or None when the rules cannot decide.

    `locale` only matters for the model layer's prompt; matching here is
    language-agnostic, as in `clinical/red_flags`, so a Spanish session where
    the mother types in French still routes.

    Order matters and is the contract:
      other   only when nothing names the baby;
      track   what only the tools do: briefings, profile fixes, trials,
              interactions (needs an account, otherwise a question);
      record  a measurement reported in the past tense, nothing asked, no worry;
      track   the child's own data (needs an account, otherwise a question);
      clarify the age changes the answer and nobody knows it, or she reports
              a fever without the thermometer reading (age first: one
              question per turn);
      plan    an explicit "what do I do" or a symptom with a worry;
      question a fact or an explanation with no worry attached.
    """
    del locale
    n = read_shorthand(normalize(message))
    if not n:
        return None

    if _OUT_OF_SCOPE.search(n) and not _BABY_REF.search(n):
        return RouteDecision(intent="other", confidence=0.85, via="rule")

    if _TOOL_ASK.search(n):
        if has_account:
            return RouteDecision(intent="track", confidence=0.9, via="rule")
        return RouteDecision(intent="question", confidence=0.8, via="rule")

    worried = bool(_WORRY.search(n))
    if (
        ((_PAST_REPORT.search(n) and _MEASUREMENT.search(n)) or _PRESENT_MEASURE.search(n))
        and not _asks_something(n)
        and not worried
    ):
        if has_account:
            return RouteDecision(intent="record", confidence=0.9, via="rule")
        return RouteDecision(intent="plan", confidence=0.8, via="rule")

    if _OWN_DATA.search(n):
        if has_account:
            return RouteDecision(intent="track", confidence=0.9, via="rule")
        return RouteDecision(intent="question", confidence=0.8, via="rule")

    if _NEEDS_AGE.search(n) and not _age_is_known(n, facts):
        return RouteDecision(intent="clarify", confidence=0.9, missing=["age"], via="rule")

    fever_report = _FEVER_REPORT.search(n) and not _NO_FEVER.search(n)
    if fever_report and not _has_reading(message, n):
        return RouteDecision(intent="clarify", confidence=0.9, missing=["temperature"], via="rule")

    if _VAGUE_WORRY.search(n) and not _SYMPTOM.search(n):
        return RouteDecision(intent="clarify", confidence=0.9, missing=list(_VAGUE_ASKS),
                             via="rule")

    if _PLAN_ASK.search(n) or (worried and _SYMPTOM.search(n)):
        return RouteDecision(intent="plan", confidence=0.9, via="rule")

    if _fact_ask(n) and not worried:
        return RouteDecision(intent="question", confidence=0.85, via="rule")

    return None


# A message shaped as a question: its opening word, in the three languages.
_QUESTION_OPENING = re.compile(
    r"^(?:(?:y|and|et|pero|but|mais) )?(?:cuant[oa]s?|cuando|como|donde|cual\w*|que|"
    r"puedo|puede|se puede|es bueno|es malo|es normal|hay que|debo|tengo que|por que|"
    r"how|what|when|where|which|why|is it|is that|are|can|could|should|do|does|"
    r"combien|quand|comment|quel\w*|pourquoi|est-ce|peut|puis-je|dois|faut-il)\b"
)


def fallback_intent(message: str) -> str:
    """The shape for a turn nobody could place: the rules abstained and the
    classifier is down (the 429 of October, or its 2 s deadline).

    Decision 1 of AGENT_GRAPH.md: the path with the most safeguards, the plan.
    Only a plain question, with no symptom, no worry and no drug in it, takes
    the short sourced answer. Never the tool loop, which has no answer
    contract (the conversation battery, 2026-11-10).
    """
    n = read_shorthand(normalize(message)).lstrip("¿¡( ")
    looks = _asks_something(n) or bool(_QUESTION_OPENING.search(n))
    if looks and not (_SYMPTOM.search(n) or _WORRY.search(n) or _DRUG.search(n)):
        return "question"
    return "plan"


def names_the_baby(message: str) -> bool:
    """Whether the message names the baby: never `other`, whoever says so."""
    return bool(_BABY_REF.search(read_shorthand(normalize(message))))


# --- model ------------------------------------------------------------------

#: Below this the model is not sure enough to pick a contract: ask one thing.
CONFIDENCE_FLOOR = 0.6
#: The user-facing path waits at most this long for the classifier.
MODEL_TIMEOUT_S = 2.0

_FALLBACK = RouteDecision(intent="plan", confidence=0.0, via="fallback")


def _fallback(reason: str) -> RouteDecision:
    return _FALLBACK.model_copy(update={"reason": reason})


def _error_reason(exc: BaseException) -> str:
    """The exception's type and, for a provider's refusal, its HTTP status (a 429
    is capacity, not a bug). Never its text, which may quote the request."""
    status = getattr(exc, "status_code", None)
    return f"error:{type(exc).__name__}" + (f" {status}" if isinstance(status, int) else "")


_LANGUAGE = {"es": "Spanish", "en": "English", "fr": "French"}

_SYSTEM_PROMPT = """You classify ONE message a parent sends to a pediatric assistant.
Answer with a single JSON object and nothing else: no prose, no markdown.

Schema:
{{"intent": "<one of {intents}>", "confidence": <0.0 to 1.0>, "missing": [<strings>]}}

Intents:
- "plan": there is a concern about the baby and the parent wants to know what to do.
- "question": the parent wants a fact or a short explanation, with no action to take
  ("is it normal that...", "at what age...", "when...", "what is...").
- "record": the parent reports something that happened (a temperature, a feed, sleep,
  a nappy) to leave it noted. Only possible when the parent has an account.
- "track": the parent asks about THEIR OWN child's data: percentiles, vaccines due,
  reports, lab results, the record. Only possible when the parent has an account.
- "clarify": an essential fact is missing and the answer depends on it (no age and the
  topic is fever, feeding amounts or sleep; "something is wrong" with no symptom).
  Put the missing fact in "missing" ("age", "symptom", "temperature", "duration").
- "other": out of scope: an adult, a pet, the weather, small talk, jokes.

The message may be in {language} or any other language. Never explain. JSON only."""

_USER_PROMPT = {
    "es": "Mensaje: {message}\nLa madre tiene cuenta: {account}\nEdad conocida (meses): {age}",
    "en": "Message: {message}\nParent has an account: {account}\nKnown age (months): {age}",
    "fr": "Message : {message}\nLe parent a un compte : {account}\nAge connu (mois) : {age}",
}

#: Added to the system prompt only when the call carries the thread (2026-11-09).
#: A first turn's prompt is byte for byte what it was, and so is its cost.
_THREAD_RULES = """

The message continues a conversation, shown before it (most recent last). Add two keys:
{{"turn": "<follow_up | correction | new>", "search_query": "<text>"}}
- "follow_up": it goes on with the same topic ("and at night?", "but it happens every day").
- "correction": it says the last answer assumed something wrong ("he is not sick", "she has
  no fever", "that was a new topic", another age).
- "new": a different topic.
"search_query": the parent's current question as ONE standalone sentence in the parent's
language, built only from what THE PARENT wrote in this topic, never from the assistant's
answers, and without what the parent says does not apply. For "new", the message itself."""

#: The thread as the routing model reads it: a label per speaker, the tail
#: only (agent/conversation.route_history cuts it).
_THREAD_HEADER = {
    "es": ("Conversación previa (lo más reciente al final):", "Madre", "AdelIA"),
    "en": ("Earlier conversation (most recent last):", "Parent", "AdelIA"),
    "fr": ("Conversation précédente (le plus récent à la fin) :", "Parent", "AdelIA"),
}


def _thread_block(history: list[dict] | None, lang: str) -> str:
    turns = [m for m in history or [] if isinstance(m, dict) and isinstance(m.get("content"), str)
             and m.get("role") in ("user", "assistant")]
    if not turns:
        return ""
    header, parent, assistant = _THREAD_HEADER.get(lang, _THREAD_HEADER["es"])
    lines = [header]
    for m in turns:
        who = parent if m["role"] == "user" else assistant
        lines.append(f"{who}: {' '.join(m['content'].split())}")
    return "\n".join(lines) + "\n\n"


def _thread_fields(data: dict) -> dict:
    """`turn` and `search_query` out of the model's JSON, kept only if valid."""
    turn = data.pop("turn", None)
    query = data.pop("search_query", None)
    fields: dict = {}
    if isinstance(turn, str) and turn in TURNS:
        fields["turn"] = turn
    if isinstance(query, str) and query.strip():
        fields["search_query"] = query.strip()[:SEARCH_QUERY_CHARS]
    return fields


def _fence_free(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def _mistral_json(system: str, user: str) -> str:
    """One JSON-mode completion from the small routing model. Raises without a key."""
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")
    client = get_mistral_client()
    resp = await client.chat.complete_async(
        model=settings.mistral_routing_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage.count(
        usage.json_operation(), "mistral", settings.mistral_routing_model,
        **usage.openai_style_tokens(resp),
    )
    return content_text(resp.choices[0].message.content)


async def _openai_json(system: str, user: str) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage.count(
        usage.json_operation(), "openai", settings.openai_chat_model,
        **usage.openai_style_tokens(resp),
    )
    return resp.choices[0].message.content or ""


async def _anthropic_json(system: str, user: str) -> str:
    """JSON by instruction, not by schema: the reply is validated against
    RouteDecision anyway and an invalid one is the `plan` fallback. Effort "low"
    because the whole call has to fit the 2 s deadline, and not thinking
    "disabled", which some Claude models answer with a 400: a 400 here would
    turn every message into the fallback without anyone noticing."""
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.anthropic_routing_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low"},
    )
    usage.count(
        usage.json_operation(), "anthropic", settings.anthropic_routing_model,
        **usage.anthropic_tokens(resp),
    )
    return anthropic_text(resp)


async def _complete_json(system: str, user: str, *, provider: str | None = None) -> str:
    """Same selection as `chat_orchestrator._stream_llm_tokens`: an explicit
    provider (the demo's `demo_llm_provider`) wins, else `settings.llm_provider`."""
    if uses_anthropic(provider):
        return await _anthropic_json(system, user)
    if (provider or settings.llm_provider) == "openai":
        return await _openai_json(system, user)
    return await _mistral_json(system, user)


def _bounded_by_account(decision: RouteDecision, has_account: bool) -> RouteDecision:
    """Without an account there is nothing to record and no record to read."""
    if has_account:
        return decision
    if decision.intent == "record":
        return decision.model_copy(update={"intent": "plan"})
    if decision.intent == "track":
        return decision.model_copy(update={"intent": "question"})
    return decision


async def route_by_model(
    message: str,
    *,
    locale: str = "es",
    has_account: bool = False,
    facts: ProfileFacts | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
    ask_turn: bool = True,
) -> RouteDecision:
    """One classifier call. Never raises on the model's output: a reply that
    is not valid JSON for `RouteDecision` is the `plan` fallback. Provider
    errors (no key, network) DO propagate; `route` turns them into the same
    fallback under its deadline.

    `history` is the tail of the conversation (agent/conversation): with it,
    the same call also says what kind of turn this is and what to search.
    With `ask_turn` False (the rules already placed the turn) it reads the
    thread for the intent only: the system prompt is a first turn's, and no
    `turn` or `search_query` is asked for or taken. Those two fields were most
    of what the model wrote, and the graph threw them away (2026-11-11).
    """
    lang = (locale or "es").split("-")[0].lower()
    system = _SYSTEM_PROMPT.format(
        intents=", ".join(f'"{i}"' for i in INTENTS),
        language=_LANGUAGE.get(lang, "Spanish"),
    )
    thread = _thread_block(history, lang)
    asks_turn = bool(thread) and ask_turn
    if asks_turn:
        system += _THREAD_RULES.format()
    age = facts.age_months if facts is not None else None
    user = thread + _USER_PROMPT.get(lang, _USER_PROMPT["es"]).format(
        message=message.strip(),
        account="si" if has_account else "no",
        age=age if age is not None else "?",
    )
    raw = await _complete_json(system, user, provider=provider)
    try:
        data = json.loads(_fence_free(raw))
        extra = _thread_fields(data) if isinstance(data, dict) and asks_turn else {}
        if isinstance(data, dict):
            data.pop("turn", None)
            data.pop("search_query", None)
            data.pop("reason", None)
        decision = RouteDecision.model_validate({**data, "via": "model", **extra})
    except (ValueError, ValidationError, TypeError):
        # Never the text: with the thread it can carry her words (search_query).
        logger.info("route: model output did not validate (%d chars)", len(raw))
        return _fallback("invalid")
    if decision.confidence < CONFIDENCE_FLOOR:
        decision = decision.model_copy(update={"intent": "clarify"})
    return _bounded_by_account(decision, has_account)


async def route(
    message: str,
    *,
    locale: str = "es",
    has_account: bool = False,
    facts: ProfileFacts | None = None,
    provider: str | None = None,
    timeout_s: float = MODEL_TIMEOUT_S,
    history: list[dict] | None = None,
    ask_turn: bool = True,
) -> RouteDecision:
    """Rules first; the model only when they abstain, under a deadline.

    Never raises and never waits longer than `timeout_s`: the surfaces call
    this on the user-facing path, where a slow classifier must cost a log
    line, not a second of the mother's time. A fallback says why (`reason`).
    """
    decision = route_by_rules(message, locale=locale, has_account=has_account, facts=facts)
    if decision is not None:
        return decision
    try:
        return await asyncio.wait_for(
            route_by_model(
                message, locale=locale, has_account=has_account, facts=facts, provider=provider,
                history=history, ask_turn=ask_turn,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.info("route: model exceeded %.1fs, falling back to plan", timeout_s)
        return _fallback("timeout")
    except Exception as exc:  # noqa: BLE001 - routing must never break the answer
        reason = _error_reason(exc)
        logger.info("route: model unavailable (%s), falling back to plan", reason)
        return _fallback(reason)


# --- measure only (build step 1) --------------------------------------------
#
# The surfaces call `spawn_route_log` right after the red-flag check and
# carry on; the decision is logged, never used. When the graph lands the
# same call site becomes the edge out of `guard`.

_ROUTE_LOGS: set[asyncio.Task] = set()


async def log_route(
    surface: str,
    message: str,
    *,
    locale: str = "es",
    has_account: bool = False,
    facts: ProfileFacts | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
    ask_turn: bool = True,
) -> RouteDecision:
    """Route and write ONE log line. Never raises, never logs the message
    (nor the thread)."""
    try:
        decision = await route(
            message, locale=locale, has_account=has_account, facts=facts, provider=provider,
            history=history, ask_turn=ask_turn,
        )
    except Exception as exc:  # noqa: BLE001 - a measurement must not become an error
        decision = _fallback(_error_reason(exc))
    logger.info(
        "route intent=%s via=%s conf=%.2f surface=%s missing=%s account=%s turn=%s reason=%s",
        decision.intent, decision.via, decision.confidence, surface,
        ",".join(decision.missing) or "-", "yes" if has_account else "no",
        decision.turn or "-", decision.reason or "-",
    )
    return decision


def spawn_route_log(
    surface: str,
    message: str,
    *,
    locale: str = "es",
    has_account: bool = False,
    facts: ProfileFacts | None = None,
    provider: str | None = None,
) -> asyncio.Task:
    """Schedule `log_route` without waiting for it.

    The user-facing path pays nothing: rules settle on the task's first step,
    and the model layer has its own deadline. The set holds a strong
    reference until the task is done, as asyncio asks."""
    task = asyncio.create_task(
        log_route(
            surface, message, locale=locale, has_account=has_account, facts=facts,
            provider=provider,
        )
    )
    _ROUTE_LOGS.add(task)
    task.add_done_callback(_ROUTE_LOGS.discard)
    return task
