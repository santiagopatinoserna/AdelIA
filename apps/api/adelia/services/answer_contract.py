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

    `language_rule`, `no_info_phrase` and `disclaimer_rule` are instructions
    *about* the answer and stay in the prompt's own language (Spanish); only
    the quoted fragments they carry are localized. `refusal` is different: it
    is user-facing text, returned verbatim by the code, so it is written in
    the parent's language and must read like a person, not like a policy.
    """

    language_rule: str
    no_info_phrase: str
    disclaimer_rule: str
    refusal: str


CONTRACTS: dict[str, LocaleContract] = {
    "es": LocaleContract(
        language_rule="Responde en español, en uno o dos párrafos cortos.",
        no_info_phrase='"No tengo información suficiente"',
        disclaimer_rule=(
            'Termina con "Verifica con tu médico antes de tomar decisiones clínicas."'
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
        disclaimer_rule=(
            'End with "Verify with your doctor before making clinical decisions."'
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
        disclaimer_rule=(
            'Termine par "Vérifiez avec votre médecin avant toute décision clinique."'
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
- {c.disclaimer_rule}"""


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
        "données ; n'invente jamais. Pour les actions d'écriture/partage, propose et "
        "attends la confirmation."
    ),
}


def agent_system_prompt(locale: str) -> str:
    """System prompt of the /dashboard agent: persona plus the same contract.

    The agent reaches evidence through the `buscar_en_expediente` tool, which
    runs the RAG chat pipeline, so the citation clauses are enforceable here
    too. Without this composition the default screen answered clinical
    questions from the model's own knowledge.

    One clause is overridden at the end: the marker syntax. The chat renders
    [ev_N] as a source card (components/chat-message.tsx); the agent canvas
    paints plain text and AgentEvent carries no citations, so a marker there
    is an orphan citation pointing at nothing. The tool therefore strips the
    markers and hands back a "Fuentes citables" line, and this tail tells the
    model to name the guideline in prose. The override is removed when audit
    item 3.7 propagates citations through the agent's SSE stream.
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
- En esta superficie las citas se escriben con el NOMBRE de la fuente, no con
  marcadores: sustituye [ev_N] y [N] por la guía y el año que `buscar_en_expediente`
  devuelve en su línea "Fuentes citables". Nunca dejes un [1] ni un [ev_1] en la
  respuesta. Si esa línea viene vacía, no interpretes: di que no lo sabes.
"""
