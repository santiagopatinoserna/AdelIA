"""The clinical answer contract: one definition, every answering surface.

AdelIA has two surfaces that talk to a parent: the RAG chat
(`services/chat_orchestrator`) and the agent behind `/dashboard`
(`agent/orchestrator`). Until 2026-08-31 only the chat carried the clinical
rules; the agent's whole system prompt was three sentences with no citation
obligation, no disclaimer and no "say you don't know". The parent's first
question lands on the agent, so the promise the product makes was not the
promise the default screen kept.

This module is the single source of both:

* `answer_contract(locale)` renders the clauses both prompts must contain
  (language, citation obligation, no interpretation without a citation,
  refusal wording, closing disclaimer).
* `no_evidence_reply(locale)` is the answer the *code* returns, without ever
  reaching a generative model, when retrieval comes back with nothing. A
  prompt clause is a request; this one is a guarantee.

Anything that answers a parent composes one of `chat_system_prompt` /
`agent_system_prompt`. Adding a third surface means adding it here, not
re-typing the rules.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocaleContract:
    """Per-language slots of the contract.

    `language_rule` and `no_info_phrase` are instructions *about* the answer
    and stay in the prompt's own language (Spanish); only the quoted
    fragments they carry are localized. `refusal`, `disclaimer` and the
    red-flag wording are different: they are user-facing text, returned
    verbatim by the code or painted by the interface, so they are written in
    the parent's language and must read like a person, not like a policy.

    `disclaimer` used to be a prompt clause ("End with ..."), which meant it
    appeared only when the model chose to obey, never on a refusal, and never
    on the agent canvas. Audit 3.8 moves it to the interface, where it is
    always visible; the prompt no longer asks for it.
    """

    language_rule: str
    no_info_phrase: str
    disclaimer: str
    refusal: str


CONTRACTS: dict[str, LocaleContract] = {
    "es": LocaleContract(
        language_rule="Responde en español, en uno o dos párrafos cortos.",
        no_info_phrase='"No tengo información suficiente"',
        disclaimer=(
            "AdelIA no sustituye a tu pediatra. Verifica con tu médico antes de "
            "tomar decisiones clínicas."
        ),
        refusal=(
            "No tengo evidencia clínica sobre esto en mi biblioteca, así que prefiero "
            "no responder antes que inventar. Coméntalo con tu pediatra, que conoce a "
            "tu bebé y puede valorarlo."
        ),
    ),
    "en": LocaleContract(
        language_rule="Answer in English, in one or two short paragraphs.",
        no_info_phrase='"I don\'t have enough information"',
        disclaimer=(
            "AdelIA does not replace your pediatrician. Verify with your doctor "
            "before making clinical decisions."
        ),
        refusal=(
            "I have no clinical evidence about this in my library, so I would rather "
            "say nothing than make something up. Please raise it with your "
            "pediatrician, who knows your baby and can assess it."
        ),
    ),
    "fr": LocaleContract(
        language_rule="Réponds en français, en un ou deux paragraphes courts.",
        no_info_phrase='"Je n\'ai pas assez d\'informations"',
        disclaimer=(
            "AdelIA ne remplace pas votre pédiatre. Vérifiez avec votre médecin "
            "avant toute décision clinique."
        ),
        refusal=(
            "Je n’ai aucune preuve clinique à ce sujet dans ma bibliothèque, je préfère "
            "donc ne rien dire plutôt que d’inventer. Parlez-en à votre pédiatre, qui "
            "connaît votre bébé et peut l’évaluer."
        ),
    ),
}

DEFAULT_LOCALE = "es"


def contract_for(locale: str) -> LocaleContract:
    return CONTRACTS.get(locale, CONTRACTS[DEFAULT_LOCALE])


def no_evidence_reply(locale: str) -> str:
    """The refusal the code returns when retrieval found nothing at all.

    Used by `chat_orchestrator.answer_question_streaming` *instead of* a call
    to the generative model, so the guarantee does not depend on the model
    choosing to obey a prompt.
    """
    return contract_for(locale).refusal


def answer_contract(locale: str) -> str:
    """The clauses every AdelIA answering surface must carry, verbatim."""
    c = contract_for(locale)
    return f"""Reglas de respuesta (obligatorias, idénticas en el chat y en el agente):
- Toda interpretación, valoración o recomendación clínica DEBE apoyarse en al menos una
  cita de evidencia [ev_1], [ev_2], ... Si NO hay un estudio o guía en el contexto que
  respalde la respuesta clínica, di {c.no_info_phrase} y explica que no hay evidencia de
  investigación que la sustente. NO interpretes ni aconsejes sin respaldo de investigación.
- Puedes reportar los datos del bebé como hechos (valores, fechas, qué dijo cada médico)
  citándolos con marcadores numéricos [1], [2], ... del orden de los fragmentos del
  paciente, pero NO los interpretes clínicamente sin una cita [ev_N].
- Si no tienes ninguna base documental para lo que se te pregunta, dilo con estas
  palabras exactas y no añadas nada más: "{c.refusal}"
- {c.language_rule}
- NUNCA inventes datos médicos ni estudios. NUNCA des consejos médicos definitivos.
- NO escribas ningún descargo de responsabilidad ni "consulta con tu médico" al final:
  la interfaz ya lo muestra de forma fija bajo cada respuesta (auditoría 3.8). Repetirlo
  gasta la línea que el padre sí lee."""


def chat_system_prompt(locale: str) -> str:
    """System prompt of the RAG chat: dual-RAG preamble plus the contract."""
    return f"""Eres el asistente de salud de AdelIA, enfocado en el seguimiento de
la salud de bebés y niños. Respondes sobre los datos del bebé proporcionados,
pero TODA interpretación o afirmación clínica debe SUSTENTARSE EXCLUSIVAMENTE en
los estudios de investigación / guías clínicas provistos en la sección
"Clinical evidence". No respondes desde tu conocimiento general.

{answer_contract(locale)}

Además, en el chat:
- El historial de la conversación ES contexto válido: resuelve referencias ("ese valor",
  "¿y a los 6 meses?") usando los datos ya citados en turnos anteriores, manteniendo sus
  marcadores originales.
- Cita los estudios/guías con marcadores [ev_1], [ev_2], ... de la sección
  "Clinical evidence".
- Separa claramente el dato del bebé de la evidencia (e.g. "regurgita tras cada toma [1];
  según NASPGHAN-ESPGHAN es habitual y mejora hacia los 12 meses [ev_1]").
"""


_AGENT_PERSONA = {
    "es": (
        "Eres AdelIA, una asistente de salud cálida y clara para madres ocupadas. "
        "Responde corto y sin jerga. Usa las herramientas para consultar datos; nunca "
        "inventes. Para acciones que escriben o comparten, propón y espera confirmación."
    ),
    "en": (
        "You are AdelIA, a warm, clear health assistant for busy moms. Be brief, no "
        "jargon. Use tools to look up data; never make things up. For write/share "
        "actions, propose and wait for confirmation."
    ),
    "fr": (
        "Tu es AdelIA, une assistante santé chaleureuse et claire pour les mamans "
        "occupées. Sois brève, sans jargon. Utilise les outils pour consulter les "
        "données ; n’invente jamais. Pour les actions d'écriture/partage, propose et "
        "attends la confirmation."
    ),
}


def agent_system_prompt(locale: str) -> str:
    """System prompt of the /dashboard agent: persona plus the same contract.

    The agent reaches evidence through the `buscar_en_expediente` tool, which
    runs the RAG chat pipeline, so the citation clauses are enforceable here
    too. Without this composition the default screen answered clinical
    questions from the model's own knowledge.

    Until item 3.7 the agent overrode one clause: the marker syntax. The chat
    rendered [ev_N] as a source card while the agent canvas painted plain
    text and AgentEvent carried no citations, so a marker on /dashboard was
    an orphan pointing at nothing, and the tool stripped the markers and
    handed back a "Fuentes citables" line instead. The agent's SSE now
    carries both citation namespaces and the canvas renders the same
    evidence card as the chat, so the override is gone: one contract, one
    marker syntax, both surfaces.
    """
    persona = _AGENT_PERSONA.get(locale, _AGENT_PERSONA[DEFAULT_LOCALE])
    return f"""{persona}

{answer_contract(locale)}

Además, como agente:
- Antes de responder cualquier pregunta clínica sobre el bebé, usa
  `buscar_en_expediente`: es la única vía que trae datos del expediente y evidencia
  citable. No respondas clínicamente sin haberla usado.
- Si la herramienta no devuelve ni datos del bebé ni evidencia, di que no lo sabes y
  sugiere consultarlo con el pediatra. No completes el hueco con conocimiento general.
- Reutiliza los marcadores [N] y [ev_N] tal y como te los devuelve
  `buscar_en_expediente`: la interfaz los pinta como tarjeta de fuente. No los
  renumeres ni te inventes un [ev_5] que la herramienta no te haya dado.
- La edad, el sexo y la fecha de nacimiento salen del perfil: las herramientas ya los
  leen. No se los preguntes al padre ni los supongas.
"""


# ---------------------------------------------------------------------------
# Red flags (audit 3.3)
#
# What the parent reads when adelia.clinical.red_flags fires. It lives here,
# with the rest of the user-facing wording, for the same reason the refusal
# does: there are two answering surfaces and there must be one text.
#
# Rules this wording follows, and the reasons:
#
# * It names the emergency number of the parent's country. "Call your doctor"
#   at 3 a.m. is not an instruction anybody can act on.
# * It carries NO dose, NO drug name and NO reassurance. The whole point of
#   the detector is that the question ("do I give her paracetamol?") has an
#   answer the app must refuse to give.
# * It says what was seen, so the parent can tell the triage nurse. A message
#   that just says "go to hospital" gets argued with.
# * It says AdelIA cannot assess this remotely, which is true and is the
#   honest reason the app is stopping.
# ---------------------------------------------------------------------------

#: 112 is the single European emergency number (Council Decision 91/396/EEC),
#: and is the number in both countries AdelIA serves today. Adding a country
#: means adding it here, not editing eleven strings.
EMERGENCY_NUMBERS: dict[str, str] = {"ES": "112", "FR": "112"}
DEFAULT_EMERGENCY_NUMBER = "112"

#: Locale is not a country, but it is the only country signal the answering
#: surfaces have until Profile carries one. Both mapped locales resolve to
#: 112 anyway, so a wrong guess between them cannot produce a wrong number.
_LOCALE_COUNTRY: dict[str, str] = {"es": "ES", "fr": "FR"}


def emergency_number(country: str | None = None, locale: str = DEFAULT_LOCALE) -> str:
    """The number to dial, by country, falling back to the locale then to 112."""
    if country and country.upper() in EMERGENCY_NUMBERS:
        return EMERGENCY_NUMBERS[country.upper()]
    mapped = _LOCALE_COUNTRY.get(locale)
    if mapped:
        return EMERGENCY_NUMBERS[mapped]
    return DEFAULT_EMERGENCY_NUMBER


#: One line per flag, in the parent's language: what was recognised and why
#: it cannot wait. Keyed by adelia.clinical.red_flags.PRIORITY codes.
RED_FLAG_REASONS: dict[str, dict[str, str]] = {
    "fever_under_3_months": {
        "es": (
            "Has descrito fiebre en un bebé de menos de 3 meses. A esa edad, 38 °C o "
            "más se considera de alto riesgo y se valora el mismo día, aunque el bebé "
            "parezca tranquilo."
        ),
        "en": (
            "You have described a fever in a baby under 3 months old. At that age, "
            "38 °C or more counts as high risk and is assessed the same day, even if "
            "the baby seems settled."
        ),
        "fr": (
            "Vous décrivez une fièvre chez un bébé de moins de 3 mois. À cet âge, "
            "38 °C ou plus est considéré comme à haut risque et s’évalue le jour même, "
            "même si le bébé paraît calme."
        ),
    },
    "non_blanching_rash": {
        "es": (
            "Has descrito manchas que no desaparecen al presionar la piel. Un exantema "
            "que no blanquea puede ser el primer signo de una infección meningocócica y "
            "se valora de inmediato."
        ),
        "en": (
            "You have described spots that do not fade when you press the skin. A "
            "non-blanching rash can be the first sign of meningococcal infection and is "
            "assessed immediately."
        ),
        "fr": (
            "Vous décrivez des taches qui ne s’effacent pas à la pression. Une éruption "
            "qui ne blanchit pas peut être le premier signe d’une infection à "
            "méningocoque et s’évalue immédiatement."
        ),
    },
    "respiratory_distress": {
        "es": (
            "Has descrito dificultad para respirar (quejido, tiraje, aleteo nasal o "
            "respiración muy rápida). Es un signo de alarma respiratoria y se valora ya."
        ),
        "en": (
            "You have described difficulty breathing (grunting, chest indrawing, nasal "
            "flaring or very fast breathing). That is a respiratory red flag and is "
            "assessed now."
        ),
        "fr": (
            "Vous décrivez une difficulté à respirer (geignement, tirage, battement des "
            "ailes du nez ou respiration très rapide). C’est un signe d’alerte "
            "respiratoire et cela s’évalue tout de suite."
        ),
    },
    "cyanosis": {
        "es": (
            "Has descrito un color azulado o amoratado en los labios, la lengua o la "
            "piel. Es un signo de falta de oxígeno y no admite espera."
        ),
        "en": (
            "You have described a blue or dusky colour on the lips, tongue or skin. "
            "That is a sign of low oxygen and it cannot wait."
        ),
        "fr": (
            "Vous décrivez une coloration bleutée des lèvres, de la langue ou de la "
            "peau. C’est un signe de manque d’oxygène et cela n’attend pas."
        ),
    },
    "seizure": {
        "es": (
            "Has descrito una convulsión. Toda convulsión en un bebé o un niño pequeño "
            "se valora por un profesional, aunque haya cedido sola."
        ),
        "en": (
            "You have described a seizure. Every seizure in a baby or toddler is "
            "assessed by a professional, even if it stopped on its own."
        ),
        "fr": (
            "Vous décrivez une convulsion. Toute convulsion chez un bébé ou un jeune "
            "enfant s’évalue par un professionnel, même si elle a cédé seule."
        ),
    },
    "choking": {
        "es": (
            "Has descrito un atragantamiento. Si no puede toser, llorar ni respirar, "
            "es una urgencia inmediata."
        ),
        "en": (
            "You have described choking. If the child cannot cough, cry or breathe, "
            "this is an immediate emergency."
        ),
        "fr": (
            "Vous décrivez un étouffement. Si l’enfant ne peut ni tousser, ni pleurer, "
            "ni respirer, c’est une urgence immédiate."
        ),
    },
    "anaphylaxis": {
        "es": (
            "Has descrito una posible reacción alérgica grave (hinchazón de cara, labios "
            "o lengua, o dificultad para respirar tras un alérgeno). Si tenéis "
            "autoinyector de adrenalina prescrito, es el momento de usarlo."
        ),
        "en": (
            "You have described a possible severe allergic reaction (swelling of the "
            "face, lips or tongue, or trouble breathing after an allergen). If an "
            "adrenaline autoinjector has been prescribed, this is the moment to use it."
        ),
        "fr": (
            "Vous décrivez une possible réaction allergique grave (gonflement du visage, "
            "des lèvres ou de la langue, ou gêne respiratoire après un allergène). Si un "
            "auto-injecteur d’adrénaline a été prescrit, c’est le moment de l’utiliser."
        ),
    },
    "bulging_fontanelle": {
        "es": (
            "Has descrito la fontanela abombada. Es uno de los signos que hacen pensar "
            "en una meningitis y se valora de inmediato."
        ),
        "en": (
            "You have described a bulging fontanelle. It is one of the signs that "
            "raises the question of meningitis and is assessed immediately."
        ),
        "fr": (
            "Vous décrivez une fontanelle bombée. C’est un des signes qui font penser à "
            "une méningite et cela s’évalue immédiatement."
        ),
    },
    "lethargy": {
        "es": (
            "Has descrito que no se despierta, no reacciona o está muy decaído. Un bebé "
            "al que cuesta despertar se valora hoy, no mañana."
        ),
        "en": (
            "You have described a baby who will not wake, does not respond or is very "
            "listless. A baby who is hard to rouse is assessed today, not tomorrow."
        ),
        "fr": (
            "Vous décrivez un bébé qui ne se réveille pas, ne réagit pas ou est très "
            "abattu. Un bébé difficile à réveiller s’évalue aujourd’hui, pas demain."
        ),
    },
    "no_wet_nappy_12h": {
        "es": (
            "Has descrito 12 horas o más sin pañal mojado. Es un signo de deshidratación "
            "y hay que valorarlo hoy."
        ),
        "en": (
            "You have described 12 hours or more with no wet nappy. That is a sign of "
            "dehydration and needs assessing today."
        ),
        "fr": (
            "Vous décrivez 12 heures ou plus sans couche mouillée. C’est un signe de "
            "déshydratation et cela doit être évalué aujourd’hui."
        ),
    },
    "dehydration": {
        "es": (
            "Has descrito signos de deshidratación (ojos hundidos, llanto sin lágrimas, "
            "boca seca o fontanela hundida). En un lactante se valora hoy."
        ),
        "en": (
            "You have described signs of dehydration (sunken eyes, crying without tears, "
            "a dry mouth or a sunken fontanelle). In an infant that is assessed today."
        ),
        "fr": (
            "Vous décrivez des signes de déshydratation (yeux creux, pleurs sans larmes, "
            "bouche sèche ou fontanelle creuse). Chez un nourrisson, cela s’évalue "
            "aujourd’hui."
        ),
    },
}

#: The frame around the reason. `{reason}` and `{number}` are the only slots.
#: French keeps U+00A0 before its high punctuation, per the repo's typography
#: rule; no em dashes anywhere, per the same rule.
_RED_FLAG_TEMPLATE: dict[str, str] = {
    "es": (
        "Esto no puede esperar a una respuesta mía.\n\n"
        "{reason}\n\n"
        "Llama al {number} o acude ahora a urgencias pediátricas, y cuéntales "
        "exactamente lo que acabas de escribirme. No le des ningún medicamento por tu "
        "cuenta mientras tanto, y no esperes a ver si mejora.\n\n"
        "No voy a valorar esto a distancia: no puedo verle, ni tomarle las constantes, "
        "ni explorarle. Esa parte le toca a una persona, hoy."
    ),
    "en": (
        "This cannot wait for an answer from me.\n\n"
        "{reason}\n\n"
        "Call {number} or go to a paediatric emergency department now, and tell them "
        "exactly what you just wrote to me. Do not give any medicine on your own in the "
        "meantime, and do not wait to see whether it improves.\n\n"
        "I am not going to assess this remotely: I cannot see your baby, take their "
        "vital signs or examine them. That part belongs to a person, today."
    ),
    "fr": (
        "Cela ne peut pas attendre une réponse de ma part.\n\n"
        "{reason}\n\n"
        "Appelez le {number} ou rendez-vous maintenant aux urgences pédiatriques, et "
        "dites-leur exactement ce que vous venez de m’écrire. Ne donnez aucun médicament "
        "de votre propre initiative en attendant, et n’attendez pas de voir si cela "
        "s’améliore.\n\n"
        "Je ne vais pas évaluer cela à distance : je ne peux ni le voir, ni prendre ses "
        "constantes, ni l’examiner. Cette partie revient à une personne, aujourd’hui."
    ),
}


def red_flag_reply(code: str, locale: str, *, country: str | None = None) -> str:
    """The answer the code returns, verbatim, when a red flag fires.

    Never reaches a generative model: `chat_orchestrator` and the agent
    orchestrator both return this and stop. That is the whole guarantee, and
    it is why the wording, not just the decision, lives in code.

    An unknown `code` raises: a flag whose wording nobody wrote must fail
    loudly in the tests, not quietly return a generic sentence to a parent.
    """
    lang = locale if locale in _RED_FLAG_TEMPLATE else DEFAULT_LOCALE
    reasons = RED_FLAG_REASONS[code]
    return _RED_FLAG_TEMPLATE[lang].format(
        reason=reasons.get(lang, reasons[DEFAULT_LOCALE]),
        number=emergency_number(country, lang),
    )


def interface_disclaimer(locale: str) -> str:
    """The fixed disclaimer the UI paints under every answer (audit 3.8).

    The API keeps the canonical wording so the three web catalogues can be
    checked against one source instead of drifting apart.
    """
    return contract_for(locale).disclaimer
