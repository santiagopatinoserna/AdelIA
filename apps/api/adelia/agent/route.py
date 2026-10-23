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

import re
from typing import Literal

from pydantic import BaseModel, Field

from adelia.clinical.red_flags import age_months_in, normalize
from adelia.enrichment.profile_service import ProfileFacts

Intent = Literal["plan", "question", "record", "track", "clarify", "other"]
Via = Literal["rule", "model", "fallback"]

INTENTS: tuple[str, ...] = ("plan", "question", "record", "track", "clarify", "other")


class RouteDecision(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    missing: list[str] = Field(default_factory=list)
    via: Via


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
    r"estado|despertado|llorado|cenado|desayunado|merendado|cagado)\b"
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
    r"no se que hacer|no sabemos que hacer|que le (?:doy|puedo dar|damos)|"
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
    r"why do babies|how (?:much|many) \w+ should|"
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

# Out of scope: the mother or another adult as the patient, a pet, the
# weather, a joke. Guarded by _BABY_REF: a message that also names the baby
# is never `other` by rule.
_OUT_OF_SCOPE = re.compile(
    r"\b(?:me duele|me he (?:hecho|cortado|quemado)|me tomo\b|"
    r"tengo (?:fiebre|tos|dolor|migrana|la regla|ansiedad|insomnio|mocos)\b|"
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
    r"\b(?:fiebre|febricula|decimas|temperatura|fever|fievre|"
    r"cuant[oa]s? (?:ml|mililitros|onzas|tomas|gramos|biberones|cucharadas)|"
    r"cuanta (?:leche|cantidad)|cuanto (?:tiene que|debe|deberia) (?:comer|tomar|beber)|"
    r"cantidad de (?:leche|biberon)|ml por toma|"
    r"how (?:much|many) (?:ml|oz|ounces|feeds|bottles|milk)|"
    r"combien de (?:ml|biberons|lait)|"
    r"dormir|duerme|duerma|sue[nñ]o|siestas?|horas de sueno|"
    r"sleep\w*|naps?|dort|dorme|sommeil|siestes?)\b"
)


def _age_is_known(message_n: str, facts: ProfileFacts | None) -> bool:
    if facts is not None and facts.age_months is not None:
        return True
    return age_months_in(message_n) is not None


def _asks_something(n: str) -> bool:
    return "?" in n or "¿" in n or bool(_PLAN_ASK.search(n)) or bool(_FACT_ASK.search(n))


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
      record  a measurement reported in the past tense, with nothing asked;
      track   the child's own data (needs an account, otherwise a question);
      clarify the age changes the answer and nobody knows it;
      plan    an explicit "what do I do" or a symptom with a worry;
      question a fact or an explanation with no worry attached.
    """
    del locale
    n = normalize(message)
    if not n:
        return None

    if _OUT_OF_SCOPE.search(n) and not _BABY_REF.search(n):
        return RouteDecision(intent="other", confidence=0.85, via="rule")

    if _PAST_REPORT.search(n) and _MEASUREMENT.search(n) and not _asks_something(n):
        if has_account:
            return RouteDecision(intent="record", confidence=0.9, via="rule")
        return RouteDecision(intent="plan", confidence=0.8, via="rule")

    if _OWN_DATA.search(n):
        if has_account:
            return RouteDecision(intent="track", confidence=0.9, via="rule")
        return RouteDecision(intent="question", confidence=0.8, via="rule")

    if _NEEDS_AGE.search(n) and not _age_is_known(n, facts):
        return RouteDecision(intent="clarify", confidence=0.9, missing=["age"], via="rule")

    worried = bool(_WORRY.search(n))
    if _PLAN_ASK.search(n) or (worried and _SYMPTOM.search(n)):
        return RouteDecision(intent="plan", confidence=0.9, via="rule")

    if _FACT_ASK.search(n) and not worried:
        return RouteDecision(intent="question", confidence=0.85, via="rule")

    return None
