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


#: The four sections of an action plan, per locale (Kenza, 2026-10-22), plus
#: the optional fifth, "mothers": what other parents report in public blogs
#: and forums, fed only by the experience tier and placed after the four. The
#: web renders a section as a plan card only when the model used one of these
#: exact headings; tests/test_answer_plan.py checks the web catalogues against
#: this table so the two cannot drift.
PLAN_HEADINGS: dict[str, dict[str, str]] = {
    "es": {"today": "Hoy", "watch": "Vigila", "doctor": "Cuándo ir al médico",
           "remember": "No olvides", "mothers": "Lo que cuentan otras madres"},
    "en": {"today": "Today", "watch": "Watch for", "doctor": "When to see a doctor",
           "remember": "Don’t forget", "mothers": "What other mothers say"},
    "fr": {"today": "Aujourd’hui", "watch": "À surveiller", "doctor": "Quand consulter",
           "remember": "À ne pas oublier", "mothers": "Ce que racontent d’autres mères"},
}

_H = PLAN_HEADINGS

#: The rule for the optional fifth section. It is the one place in the answer
#: where a non-clinical source may appear, so the rule names what it may never
#: carry rather than trusting the material's own header: a dose, a warning
#: sign, or anything a cited guideline contradicts, and it exists only when
#: the prompt actually brought [ex_N] material (the chat brings none today).
_MOTHERS_RULE = {
    "es": (
        f"Después de \"## {_H['es']['remember']}\" puedes añadir un único apartado opcional, "
        f"\"## {_H['es']['mothers']}\", con 1 a 3 viñetas, solo si el contexto trae fragmentos "
        "[ex_N] de experiencias de otros padres; cada viñeta cita su [ex_N]. Es experiencia, "
        "no evidencia: nunca una dosis ni un medicamento, nunca una señal de alarma ni una "
        "urgencia, nunca algo que contradiga una guía citada en la respuesta. Omítelo si no "
        "hay fragmentos [ex_N] o si lo único que cuentan choca con las fuentes. "
    ),
    "en": (
        f"After \"## {_H['en']['remember']}\" you may add one optional section, "
        f"\"## {_H['en']['mothers']}\", with 1 to 3 bullets, only when the context carries "
        "[ex_N] fragments of other parents' experience; each bullet cites its [ex_N]. It is "
        "experience, not evidence: never a dose or a medicine, never a warning sign or an "
        "urgency, never anything that contradicts a guideline cited in the answer. Leave it "
        "out if nothing [ex_N] was retrieved or if all it says clashes with the sources. "
    ),
    "fr": (
        f"Après \"## {_H['fr']['remember']}\" tu peux ajouter une seule rubrique facultative, "
        f"\"## {_H['fr']['mothers']}\", de 1 à 3 puces, uniquement si le contexte apporte des "
        "fragments [ex_N] d’expériences d’autres parents ; chaque puce cite son [ex_N]. C’est "
        "de l’expérience, pas une preuve : jamais de dose ni de médicament, jamais de signe "
        "d’alerte ni d’urgence, jamais rien qui contredise une recommandation citée dans la "
        "réponse. Omets-la si rien [ex_N] n’a été trouvé ou si tout ce qui s’y dit heurte les "
        "sources. "
    ),
}

_PLAN_RULE = {
    "es": (
        "Organiza la respuesta como un plan de acción: una frase inicial que responde, y "
        f"después solo estos apartados, en este orden: \"## {_H['es']['today']}\" (qué hacer "
        f"ahora), \"## {_H['es']['watch']}\" (qué observar), \"## {_H['es']['doctor']}\" (las "
        "señales de alarma de las fuentes y con qué urgencia actuar) y "
        f"\"## {_H['es']['remember']}\" (indicaciones previas del pediatra y lo que conviene "
        "anotar o preguntar). Omite un apartado si no hay nada respaldado: nunca un apartado "
        "vacío ni relleno. Cada viñeta es una acción concreta de una frase con su cita. "
        "En el apartado del médico, usa la urgencia que indica la fuente para cada señal "
        "(urgencias, hoy, consulta programada): ni la subas ni la bajes. "
        + _MOTHERS_RULE["es"]
    ),
    "en": (
        "Organise the answer as an action plan: one opening sentence that answers, then only "
        f"these sections, in this order: \"## {_H['en']['today']}\" (what to do now), "
        f"\"## {_H['en']['watch']}\" (what to observe), \"## {_H['en']['doctor']}\" (the warning "
        "signs from the sources and how urgently to act) and "
        f"\"## {_H['en']['remember']}\" (the pediatrician's earlier instructions and what to note "
        "or ask). Leave out a section when nothing supports it: never an empty section or "
        "filler. Each bullet is one concrete action in one sentence with its citation. "
        "In the doctor section, use the urgency the source states for each sign (emergency, "
        "today, booked visit): neither raise nor lower it. "
        + _MOTHERS_RULE["en"]
    ),
    "fr": (
        "Organise la réponse en plan d’action : une phrase d’ouverture qui répond, puis "
        f"uniquement ces rubriques, dans cet ordre : \"## {_H['fr']['today']}\" (quoi faire "
        f"maintenant), \"## {_H['fr']['watch']}\" (quoi observer), \"## {_H['fr']['doctor']}\" "
        "(les signes d’alerte des sources et avec quelle urgence agir) et "
        f"\"## {_H['fr']['remember']}\" (les consignes antérieures du pédiatre et ce qu’il faut "
        "noter ou demander). Omets une rubrique si rien ne l’étaye : jamais de rubrique vide "
        "ni de remplissage. Chaque puce est une action concrète d’une phrase avec sa citation. "
        "Dans la rubrique du médecin, garde pour chaque signe l’urgence indiquée par la "
        "source (urgences, aujourd’hui, consultation programmée), sans l’augmenter ni la "
        "réduire. "
        + _MOTHERS_RULE["fr"]
    ),
}

CONTRACTS: dict[str, LocaleContract] = {
    "es": LocaleContract(
        language_rule=(
            "Responde en español. Empieza con una respuesta directa y breve. Usa Markdown "
            "sencillo. Como máximo 3 viñetas cortas y accionables por apartado, solo si la evidencia las "
            "respalda. Todas las precauciones, condiciones y señales de alarma deben quedar "
            "visibles de inmediato junto al consejo pertinente, no en una explicación posterior. "
            "Nunca omitas seguridad por un límite de palabras o de viñetas: usa texto adicional "
            "si hace falta. Usa párrafos cortos y negrita "
            "solo para lo esencial. " + _PLAN_RULE["es"] + "No rellenes secciones ni repitas la "
            "pregunta. Mantén cada cita junto a "
            "la afirmación que respalda; el formato no permite añadir consejo sin evidencia. "
            "Escribe para una madre ocupada con un bebé llorando: ayuda directa primero. "
            "Incluye historial personal solo si está realmente en el contexto y cítalo. "
            "No prometas un diagnóstico ni inventes consejos tranquilizadores. "
            "No impongas secciones fijas ni vacías. La lectura opcional para después está en "
            "las fuentes, no en una explicación clínica larga obligatoria. La respuesta debe "
            "ser breve y segura por sí misma, sin necesitar un resumen clínico heurístico de "
            "la interfaz."
        ),
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
        language_rule=(
            "Answer in English. Start with a short, direct answer. Use simple Markdown: "
            "At most 3 short, actionable bullets per section, only if supported by evidence. "
            "All caveats, conditions and warning signs must be immediately visible alongside "
            "the relevant advice, not in a later explanation. Never omit safety for a word or "
            "bullet limit: use additional prose if needed. Use short paragraphs and bold "
            "only for essentials. " + _PLAN_RULE["en"] + "Do not pad sections or repeat the "
            "question. Keep each citation next to its "
            "claim; formatting does not permit adding advice without evidence. "
            "Write for a busy mother with a crying baby: direct help first. Include "
            "personal history only if actually present in context and cite it. "
            "Do not promise a diagnosis or invent soothing advice. "
            "Do not impose fixed or empty sections. The optional later reading belongs in the "
            "sources, not in a mandatory long clinical explanation. The answer must be brief "
            "and safe on its own, without needing a heuristic clinical summary from the interface."
        ),
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
        language_rule=(
            "Réponds en français. Commence par une réponse courte et directe. Utilise du "
            "Markdown simple. Au maximum 3 puces courtes et concrètes par rubrique, seulement si les preuves "
            "les étayent. Toutes les précautions, conditions et signes d’alerte doivent rester "
            "immédiatement visibles avec le conseil concerné, pas dans une explication ultérieure. "
            "Ne sacrifie jamais la sécurité à une limite de mots ou de puces : ajoute du texte "
            "si nécessaire. Utilise des paragraphes courts et le gras seulement pour l’essentiel. "
            + _PLAN_RULE["fr"] + "Ne remplis pas de rubriques et ne répète "
            "pas la question. Garde chaque citation près de son affirmation ; la mise en "
            "forme ne permet pas d’ajouter de conseil sans preuve. "
            "Écris pour une mère occupée avec un bébé qui pleure : aide directe d’abord. "
            "N’inclus les antécédents personnels que s’ils figurent réellement dans le contexte "
            "et cite-les. Ne promets pas de diagnostic et n’invente pas de conseils rassurants. "
            "N’impose pas de rubriques fixes ou vides. La lecture facultative pour plus tard se "
            "trouve dans les sources, pas dans une longue explication clinique obligatoire. "
            "La réponse doit être brève et sûre à elle seule, sans nécessiter un résumé clinique "
            "heuristique de l’interface."
        ),
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

#: The `question` shape (AGENT_GRAPH, build step 2): the mother asked for a
#: fact or an explanation, not for what to do, so the answer is one sentence
#: and at most three cited bullets, with no plan heading. It replaces only the
#: plan-shaped `language_rule`; every other clause of `answer_contract` stays.
#: The safety sentence is not decoration: night/brevity cut answers by 45 %
#: and lost a warning sign in 1 of 9 questions, so brevity here is bounded by
#: the sources' own warning signs and their urgency.
_QUESTION_RULE: dict[str, str] = {
    "es": (
        "Responde en español. La madre pregunta un dato o una explicación, no qué hacer: "
        "responde corto, sin plan de acción. Primero una frase que responde directamente, "
        "con su cita. Después, solo si aportan algo que la frase no dice, hasta 3 viñetas de "
        "una frase, cada una con su cita ([ev_N], o [N] si es un dato del bebé). Ningún "
        f"encabezado ni apartado: no escribas \"## {_H['es']['today']}\", "
        f"\"## {_H['es']['watch']}\", \"## {_H['es']['doctor']}\" ni "
        f"\"## {_H['es']['remember']}\". Si las fuentes ligan a la pregunta una señal de "
        "alarma o una condición que cambia la respuesta, dila en una viñeta con la urgencia "
        "que indica la fuente (urgencias, hoy, consulta programada): la seguridad nunca se "
        "recorta por brevedad. No repitas la pregunta, no añadas una explicación clínica "
        "larga y no inventes consejos tranquilizadores. Incluye historial personal solo si "
        "está realmente en el contexto y cítalo. Usa negrita solo para lo esencial."
    ),
    "en": (
        "Answer in English. The parent is asking for a fact or an explanation, not what to "
        "do: answer briefly, with no action plan. First one sentence that answers directly, "
        "with its citation. Then, only if they add something the sentence does not say, up "
        "to 3 bullets of one sentence, each with its citation ([ev_N], or [N] for the baby's "
        f"own data). No headings and no sections: do not write \"## {_H['en']['today']}\", "
        f"\"## {_H['en']['watch']}\", \"## {_H['en']['doctor']}\" or "
        f"\"## {_H['en']['remember']}\". If the sources tie a warning sign or a condition "
        "that changes the answer to the question, say it in a bullet with the urgency the "
        "source states (emergency, today, booked visit): safety is never cut for brevity. "
        "Do not repeat the question, do not add a long clinical explanation and do not "
        "invent soothing advice. Include personal history only if it is actually in the "
        "context, and cite it. Use bold only for essentials."
    ),
    "fr": (
        "Réponds en français. Le parent demande une information ou une explication, pas "
        "quoi faire : réponds brièvement, sans plan d’action. D’abord une phrase qui répond "
        "directement, avec sa citation. Ensuite, seulement si elles apportent ce que la "
        "phrase ne dit pas, jusqu’à 3 puces d’une phrase, chacune avec sa citation ([ev_N], "
        "ou [N] pour une donnée du bébé). Aucun titre ni rubrique : n’écris pas "
        f"\"## {_H['fr']['today']}\", \"## {_H['fr']['watch']}\", "
        f"\"## {_H['fr']['doctor']}\" ni \"## {_H['fr']['remember']}\". Si les sources "
        "rattachent à la question un signe d’alerte ou une condition qui change la réponse, "
        "dis-le dans une puce avec l’urgence indiquée par la source (urgences, aujourd’hui, "
        "consultation programmée) : la sécurité n’est jamais sacrifiée à la brièveté. Ne "
        "répète pas la question, n’ajoute pas de longue explication clinique et n’invente "
        "pas de conseils rassurants. N’inclus les antécédents personnels que s’ils figurent "
        "réellement dans le contexte, et cite-les. Garde le gras pour l’essentiel."
    ),
}

#: The answer shapes a surface may ask for. `plan` is the default and the
#: path with the most safeguards; the graph picks `question` only when the
#: route node said so (agent/graph.py).
SHAPES: tuple[str, ...] = ("plan", "question")


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


def _language_rule(locale: str, shape: str) -> str:
    if shape not in SHAPES:
        raise ValueError(f"unknown answer shape {shape!r}; expected one of {SHAPES}")
    if shape == "question":
        return _QUESTION_RULE.get(locale, _QUESTION_RULE[DEFAULT_LOCALE])
    return contract_for(locale).language_rule


def answer_contract(locale: str, *, shape: str = "plan") -> str:
    """The clauses every AdelIA answering surface must carry, verbatim.

    `shape` swaps only the format clause (plan or short answer); the citation
    obligation, the refusal and the no-invention clauses are the same text.
    """
    c = contract_for(locale)
    language_rule = _language_rule(locale, shape)
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
- {language_rule}
- NUNCA inventes datos médicos ni estudios. NUNCA des consejos médicos definitivos.
- NO escribas ningún descargo de responsabilidad ni "consulta con tu médico" al final:
  la interfaz ya lo muestra de forma fija bajo cada respuesta (auditoría 3.8). Repetirlo
  gasta la línea que el padre sí lee."""


def chat_system_prompt(locale: str, *, shape: str = "plan") -> str:
    """System prompt of the RAG chat: dual-RAG preamble plus the contract.

    The demo composes it too. `shape="question"` is the short-answer variant
    the graph uses when the mother asked for a fact (AGENT_GRAPH, step 2).
    """
    return f"""Eres el asistente de salud de AdelIA, enfocado en el seguimiento de
la salud de bebés y niños. Respondes sobre los datos del bebé proporcionados,
pero TODA interpretación o afirmación clínica debe SUSTENTARSE EXCLUSIVAMENTE en
los estudios de investigación / guías clínicas provistos en la sección
"Clinical evidence". No respondes desde tu conocimiento general.

{answer_contract(locale, shape=shape)}

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


# ---------------------------------------------------------------------------
# No evidence, but other mothers have something to say (AGENT_GRAPH, decision 3)
#
# When the clinical corpus has nothing and the experience tier has a match,
# the answer is one fixed sentence (code, not model) and one section, "Lo que
# cuentan otras madres", whose bullets the model writes under the rule below
# and nothing else. The rule is narrower than the plan's: there is no
# guideline in the prompt to plan on, so there is no plan, no doctor section
# and no [ev_N]; the code discards any output that strays (routers/demo).
# ---------------------------------------------------------------------------

#: User-facing, returned verbatim by the code, in the parent's language. No
#: em dashes, per the repo's typography rule.
_EXPERIENCE_ONLY_OPENING: dict[str, str] = {
    "es": "No he encontrado guías ni estudios sobre esto. Otras madres cuentan:",
    "en": "I found no guidelines or studies on this. Other mothers say:",
    "fr": "Je n’ai trouvé ni recommandation ni étude sur ce sujet. D’autres mères racontent :",
}

_EXPERIENCE_ONLY_RULE: dict[str, str] = {
    "es": (
        "El contexto no trae ninguna guía ni estudio: solo fragmentos [ex_N] de lo que "
        "cuentan otros padres en blogs y foros públicos. Escribe únicamente un apartado, "
        f"\"## {_H['es']['mothers']}\", con 1 a 3 viñetas; cada viñeta resume una "
        "experiencia concreta de una frase y cita su [ex_N]. Es experiencia, no evidencia: "
        "nunca una dosis, nunca un medicamento, nunca interpretes un síntoma, nunca una "
        "señal de alarma, nunca una urgencia, nunca un consejo que no esté en un fragmento "
        "[ex_N]. Ningún otro apartado, ninguna frase antes ni después, ninguna cita que no "
        "sea [ex_N]."
    ),
    "en": (
        "The context carries no guideline and no study: only [ex_N] fragments of what "
        "other parents report in public blogs and forums. Write exactly one section, "
        f"\"## {_H['en']['mothers']}\", with 1 to 3 bullets; each bullet sums up one "
        "concrete experience in one sentence and cites its [ex_N]. It is experience, not "
        "evidence: never a dose, never a medicine, never interpret a symptom, never a "
        "warning sign, never an urgency, never advice that is not in an [ex_N] fragment. "
        "No other section, no sentence before or after, no citation other than [ex_N]."
    ),
    "fr": (
        "Le contexte n’apporte ni recommandation ni étude : seulement des fragments [ex_N] "
        "de ce que racontent d’autres parents dans des blogs et forums publics. Écris une "
        f"seule rubrique, \"## {_H['fr']['mothers']}\", de 1 à 3 puces ; chaque puce résume "
        "une expérience concrète en une phrase et cite son [ex_N]. C’est de l’expérience, "
        "pas une preuve : jamais de dose, jamais de médicament, n’interprète jamais un "
        "symptôme, jamais de signe d’alerte, jamais d’urgence, jamais de conseil absent "
        "des fragments [ex_N]. Aucune autre rubrique, aucune phrase avant ni après, aucune "
        "citation autre que [ex_N]."
    ),
}

_EXPERIENCE_ONLY_LANGUAGE: dict[str, str] = {
    "es": "Responde en español.",
    "en": "Answer in English.",
    "fr": "Réponds en français.",
}


def experience_only_opening(locale: str) -> str:
    """The fixed first sentence of an experience-only answer, in the parent's language."""
    return _EXPERIENCE_ONLY_OPENING.get(locale, _EXPERIENCE_ONLY_OPENING[DEFAULT_LOCALE])


def experience_only_contract(locale: str) -> str:
    """System prompt for the bullets of an experience-only answer.

    Deliberately NOT composed from `answer_contract`: that one orders a plan
    with a doctor section and a refusal sentence, neither of which belongs
    here. The code has already decided there is no evidence; the model's only
    job is to sum up the [ex_N] fragments, and the code checks the shape.
    """
    lang = locale if locale in _EXPERIENCE_ONLY_RULE else DEFAULT_LOCALE
    return (
        "Eres el asistente de AdelIA. En esta respuesta no hay evidencia clínica y no "
        "debes aportarla desde tu conocimiento.\n\n"
        f"{_EXPERIENCE_ONLY_LANGUAGE[lang]} {_EXPERIENCE_ONLY_RULE[lang]}\n\n"
        "No escribas ningún descargo de responsabilidad ni \"consulta con tu médico\": "
        "la interfaz ya lo muestra bajo cada respuesta."
    )


# ---------------------------------------------------------------------------
# clarify: one question, two or three buttons (AGENT_GRAPH, build step 3)
#
# User-facing, returned verbatim by the code, in the parent's language: the
# question, the buttons and the way out. Two facts only, because each one
# changes what the sources say: the age (fever under 3 months is an
# emergency, NICE NG143 1.2.12; milk amounts and sleep depend on it) and the
# thermometer reading when she says "fiebre" without a number (39 C or more
# at 3-6 months is an amber sign in the same guideline).
#
# The age bands are chosen for the guard: the graph hands it the band's
# YOUNGEST age (CLARIFY_AGE_FLOOR), so an answer can only make it stricter,
# and "under 3 months" plus "fiebre" is the referral, not a plan. The
# temperature labels are written so that `red_flags.temperature_in` reads
# the band's top value, and the way out ("no la he medido") reads as no
# number at all. French keeps U+00A0 before its high punctuation and before
# the degree sign; no em dashes anywhere.
# ---------------------------------------------------------------------------

def _options(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


CLARIFY_QUESTIONS: dict[str, dict[str, dict]] = {
    "temperature": {
        "es": {
            "question": "¿Cuánto ha marcado el termómetro?",
            "options": _options(("37.5-37.9", "37,5 a 37,9 °C"), ("38-38.9", "38 a 38,9 °C"),
                                ("39+", "39 °C o más")),
            "skip": {"value": "unknown", "label": "No la he medido"},
        },
        "en": {
            "question": "What did the thermometer say?",
            "options": _options(("37.5-37.9", "37.5 to 37.9 °C"), ("38-38.9", "38 to 38.9 °C"),
                                ("39+", "39 °C or more")),
            "skip": {"value": "unknown", "label": "I haven’t measured it"},
        },
        "fr": {
            "question": "Combien affichait le thermomètre ?",
            "options": _options(("37.5-37.9", "37,5 à 37,9 °C"), ("38-38.9", "38 à 38,9 °C"),
                                ("39+", "39 °C ou plus")),
            "skip": {"value": "unknown", "label": "Je ne l’ai pas mesurée"},
        },
    },
    "age": {
        "es": {
            "question": "¿Cuántos meses tiene?",
            "options": _options(("0-2", "Menos de 3 meses"), ("3-11", "De 3 a 11 meses"),
                                ("12+", "12 meses o más")),
            "skip": {"value": "unknown", "label": "Responder sin la edad"},
        },
        "en": {
            "question": "How old is your baby?",
            "options": _options(("0-2", "Under 3 months"), ("3-11", "3 to 11 months"),
                                ("12+", "12 months or more")),
            "skip": {"value": "unknown", "label": "Answer without the age"},
        },
        "fr": {
            "question": "Quel âge a ton bébé ?",
            "options": _options(("0-2", "Moins de 3 mois"), ("3-11", "De 3 à 11 mois"),
                                ("12+", "12 mois ou plus")),
            "skip": {"value": "unknown", "label": "Répondre sans l’âge"},
        },
    },
}

#: The age the guard and the router see for each band: its youngest month.
CLARIFY_AGE_FLOOR: dict[str, int] = {"0-2": 0, "3-11": 3, "12+": 12}

_CLARIFY_PREFIX: dict[str, dict[str, str]] = {
    "es": {"temperature": "Temperatura: ", "age": "Edad: "},
    "en": {"temperature": "Temperature: ", "age": "Age: "},
    "fr": {"temperature": "Température : ", "age": "Âge : "},
}

_CLARIFY_UNKNOWN: dict[str, dict[str, str]] = {
    "es": {"temperature": "no la he medido", "age": "no indicada"},
    "en": {"temperature": "not measured", "age": "not given"},
    "fr": {"temperature": "pas mesurée", "age": "non indiqué"},
}


def clarify_question(field: str, locale: str) -> dict | None:
    """The question and its buttons for `field`, or None when we have none."""
    by_locale = CLARIFY_QUESTIONS.get(field)
    if by_locale is None:
        return None
    return by_locale.get(locale, by_locale[DEFAULT_LOCALE])


def clarification_sentence(field: str, value: str, locale: str) -> str | None:
    """Her answer to a clarify question, as a line appended to her message.

    None for a field or a value the question never offered: the client is a
    browser, and a value we did not write must not reach the guard or the
    prompt. "unknown" (the way out) is said in words, so no number appears.
    """
    q = clarify_question(field, locale)
    if q is None:
        return None
    lang = locale if locale in _CLARIFY_PREFIX else DEFAULT_LOCALE
    if value == q["skip"]["value"]:
        label = _CLARIFY_UNKNOWN[lang][field]
    else:
        label = next((o["label"] for o in q["options"] if o["value"] == value), None)
        if label is None:
            return None
    return f"{_CLARIFY_PREFIX[lang][field]}{label}"


#: The prompt clause for a second turn that still lacks the fact (principle
#: 2: answer with what there is). Prompt text, read by the model, in Spanish
#: like the rest of the contract's instructions.
_MISSING_FACT = {
    "temperature": "la temperatura que marca el termómetro",
    "age": "la edad del bebé",
}


def missing_fact_note(fields: list[str]) -> str:
    """What the model is told when a fact is still missing after the one question."""
    names = [_MISSING_FACT[f] for f in fields if f in _MISSING_FACT]
    if not names:
        return ""
    return (
        "Dato que falta y que no vamos a volver a preguntar: " + ", ".join(names) + ". "
        "Responde con lo que hay y di en una frase qué cambiaría en la respuesta si se "
        "supiera, con la cita de la fuente que lo dice."
    )
