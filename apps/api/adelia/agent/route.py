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

from adelia.clinical.red_flags import age_months_in, normalize
from adelia.config import settings
from adelia.enrichment.profile_service import ProfileFacts
from adelia.llm import content_text, get_mistral_client

logger = logging.getLogger(__name__)

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
      record  a measurement reported in the past tense, nothing asked, no worry;
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

    worried = bool(_WORRY.search(n))
    if (
        _PAST_REPORT.search(n)
        and _MEASUREMENT.search(n)
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

    if _PLAN_ASK.search(n) or (worried and _SYMPTOM.search(n)):
        return RouteDecision(intent="plan", confidence=0.9, via="rule")

    if _FACT_ASK.search(n) and not worried:
        return RouteDecision(intent="question", confidence=0.85, via="rule")

    return None


# --- model ------------------------------------------------------------------

#: Below this the model is not sure enough to pick a contract: ask one thing.
CONFIDENCE_FLOOR = 0.6
#: The user-facing path waits at most this long for the classifier.
MODEL_TIMEOUT_S = 2.0

_FALLBACK = RouteDecision(intent="plan", confidence=0.0, via="fallback")

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
    return resp.choices[0].message.content or ""


async def _complete_json(system: str, user: str, *, provider: str | None = None) -> str:
    """Same selection as `chat_orchestrator._stream_llm_tokens`: an explicit
    provider (the demo's `demo_llm_provider`) wins, else `settings.llm_provider`."""
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
) -> RouteDecision:
    """One classifier call. Never raises on the model's output: a reply that
    is not valid JSON for `RouteDecision` is the `plan` fallback. Provider
    errors (no key, network) DO propagate; `route` turns them into the same
    fallback under its deadline."""
    lang = (locale or "es").split("-")[0].lower()
    system = _SYSTEM_PROMPT.format(
        intents=", ".join(f'"{i}"' for i in INTENTS),
        language=_LANGUAGE.get(lang, "Spanish"),
    )
    age = facts.age_months if facts is not None else None
    user = _USER_PROMPT.get(lang, _USER_PROMPT["es"]).format(
        message=message.strip(),
        account="si" if has_account else "no",
        age=age if age is not None else "?",
    )
    raw = await _complete_json(system, user, provider=provider)
    try:
        data = json.loads(_fence_free(raw))
        decision = RouteDecision.model_validate({**data, "via": "model"})
    except (ValueError, ValidationError, TypeError):
        logger.info("route: model output did not validate (%r)", raw[:120])
        return _FALLBACK
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
) -> RouteDecision:
    """Rules first; the model only when they abstain, under a deadline.

    Never raises and never waits longer than `timeout_s`: the surfaces call
    this on the user-facing path, where a slow classifier must cost a log
    line, not a second of the mother's time.
    """
    decision = route_by_rules(message, locale=locale, has_account=has_account, facts=facts)
    if decision is not None:
        return decision
    try:
        return await asyncio.wait_for(
            route_by_model(
                message, locale=locale, has_account=has_account, facts=facts, provider=provider
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.info("route: model exceeded %.1fs, falling back to plan", timeout_s)
    except Exception as exc:  # noqa: BLE001 - routing must never break the answer
        logger.info("route: model unavailable (%s), falling back to plan", type(exc).__name__)
    return _FALLBACK


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
) -> RouteDecision:
    """Route and write ONE log line. Never raises, never logs the message."""
    try:
        decision = await route(
            message, locale=locale, has_account=has_account, facts=facts, provider=provider
        )
    except Exception:  # noqa: BLE001 - a measurement must not become an error
        decision = _FALLBACK
    logger.info(
        "route intent=%s via=%s conf=%.2f surface=%s missing=%s account=%s",
        decision.intent, decision.via, decision.confidence, surface,
        ",".join(decision.missing) or "-", "yes" if has_account else "no",
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
