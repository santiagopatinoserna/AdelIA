"""Where a turn sits in the conversation: follow-up, correction or new topic.

Santiago tried the /dashboard agent in production on 2026-11-09: "no está
bien coordinado, es tonto; cuando sigues la conversación no sigue bien; si
tiene dudas no hace preguntas". His two conversations are the fixtures of
tests/test_conversation.py. The graph read one message at a time:

  * the router saw "Pero todos los días está así" and "No es enfermo" alone,
    with nothing to say they continued or took back the last answer;
  * the account search glued the last two messages in front of the new one,
    AdelIA's own answer included, so the "niño enfermo" frame of the first
    answer was searched again on every turn;
  * the answering model got the whole transcript, so a fever noted fifteen
    minutes earlier ("Anotado: 38,7 °C") was mixed into a question about the
    nursery;
  * with essentials missing it never asked, and without evidence it said the
    same sentence every turn.

`read` answers, from the transcript the browser sends and with rules only,
what this turn is and what each later step should see:

  kind            "new" (first message, or a topic of its own), "follow_up",
                  or "correction" (she takes back what the answer assumed:
                  "no es enfermo", "no tiene fiebre", "es tema nuevo", or the
                  age it was given for);
  search_query    her words in this topic, never AdelIA's, without what she
                  took back, plus the corpus's words for a behaviour topic; a
                  first turn is searched exactly as she wrote it (the golden
                  gate's questions are first turns);
  model_history   what the answering model sees as prior turns: this topic's
                  exchanges for a follow-up, nothing for a new topic, and
                  nothing for a correction, whose earlier answers rest on the
                  frame she rejected (her words go into the prompt instead);
  route_history   a short tail of the transcript for the routing model, which
                  is called only when the routing rules abstain (no new call);
  asked, refused  whether this topic already spent its one clarify round, and
                  whether it was already told there is no evidence;
  referral        the code of the red flag this topic was referred for, if any:
                  the guard reads her follow-ups with the topic (2026-11-11).

When the rules cannot place a turn it is a follow-up (`decided` False), and
the routing model, if the routing rules already need it, may say otherwise
(`with_kind`). Nothing here reads a database, a key or a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from adelia.agent.route import _BABY_REF, _DRUG, _SYMPTOM, read_shorthand
from adelia.clinical.red_flags import age_months_in
from adelia.clinical.red_flags import normalize as _normalize
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import (
    CLARIFY_QUESTIONS,
    PLAN_HEADINGS,
    RED_FLAG_REASONS,
    clarification_sentence,
    no_evidence_reply,
    out_of_scope_reply,
    red_flag_opening,
)

TurnKind = Literal["new", "follow_up", "correction"]

#: The routing model reads this much of the transcript: two exchanges, the
#: opening of each answer. Enough to tell a follow-up from a new topic; the
#: whole answer would cost tokens on every model-routed turn (measured in the
#: commit that added it).
ROUTE_HISTORY_MESSAGES = 4
ROUTE_HISTORY_CHARS = 300
#: The answering model reads at most this many messages of the topic, the
#: window routers/agent.py already allowed the whole transcript.
MODEL_HISTORY_MESSAGES = 6
#: Her messages in a topic's search: the first one (what the topic is about)
#: and the latest ones, each cut, so a long thread does not drown the question.
TOPIC_MESSAGES = 4
LINE_CHARS = 300
MAX_QUERY_CHARS = 1000
#: An observation is at most this long (agent/record.MAX_TEXT).
VISIT_NOTE_CHARS = 500

_LANGS = ("es", "en", "fr")


def normalize(text: str) -> str:
    """`red_flags.normalize`, with her shorthand spelled out («q», «tb», «la guarde»):
    the rules below are written for whole words (route.read_shorthand)."""
    return read_shorthand(_normalize(text))


# --- vocabulary (matched on red_flags.normalize output) -------------------------

#: "Otra cosa", "tema nuevo": she says the topic changes, or changed.
_NEW_TOPIC = re.compile(
    r"\b(?:otra (?:cosa|pregunta|duda|consulta)|(?:otro|nuevo) tema|"
    r"tema (?:nuevo|distinto|diferente|aparte)|cambiando de tema|cambio de tema|"
    r"nueva pregunta|por cierto|aparte de eso|"
    r"another (?:question|thing)|new (?:topic|question)|something else|"
    r"different (?:topic|question)|unrelated|by the way|"
    r"autre (?:chose|question|sujet)|nouveau sujet|nouvelle question|rien a voir|au fait)\b"
)
#: She says the answer is about something else, without naming it.
_GENERIC_DENIAL = re.compile(
    r"\b(?:no es eso|no me refiero|no te (?:he|estoy) preguntado|no he dicho|"
    r"no pregunto (?:eso|por)|"
    r"te equivocas|no es lo que|no (?:me )?has entendido|no tiene nada que ver|no va por ahi|"
    r"that'?s not what|not what i (?:asked|meant)|i didn'?t (?:say|ask)|you misunderstood|"
    r"not about that|ce n'est pas (?:ca|ce que)|je n'ai pas (?:dit|demande)|"
    r"tu n'as pas compris|pas du tout)\b"
)
#: She says what the baby is NOT: "no es enfermo", "he's not sick", "il n'est
#: pas malade". In a short message that is taking back the answer's frame.
_DENY_IS = re.compile(
    r"\bno (?:es|era|se trata de|va de) (?:(?:un|una|el|la|los|las|de|del|por|lo) )*(\w+)"
    r"|\b(?:he|she|it|baby)(?:'s| is| was) not (?:a |an )?(\w+)"
    r"|\b(?:isn'?t|wasn'?t) (?:a |an )?(\w+)"
    r"|\b(?:il|elle|bebe|ce) n'(?:est|etait) pas (?:un |une )?(\w+)"
)
#: She says something is absent: "no tiene fiebre", "no está enfermo", "pas de
#: fièvre". Taking back only what the answer talked about (or an illness):
#: "no tiene hambre" after a sleep answer is a new fact, and it is kept.
_DENY_HAS = re.compile(
    r"\bno (?:esta|estaba|tiene|tenia|ha tenido|hay|lo esta)"
    r"(?: (?:un|una|el|la|de|nada de|ningun|ninguna))? (\w+)"
    r"|\b(?:doesn'?t have|does not have|has no) (?:a |an |any )?(\w+)"
    r"|\bno (fever|temperature)\b"
    r"|\b(?:il|elle|bebe) n'(?:a|avait) pas (?:de |d')?(\w+)"
    r"|\bpas de (\w+)"
)
#: Words a denial can end on that name no frame ("no es eso", "no está bien").
_NOT_A_FRAME = {"eso", "esto", "asi", "nada", "que", "lo", "verdad", "that", "this", "it",
                "ca", "cela", "vrai", "normal", "bien", "mal", "mejor", "peor", "well",
                "primera", "primer", "unica", "unico", "vez", "first", "only", "premiere",
                "seule", "fois"}
_ILLNESS_FRAME = {"enfermo", "enferma", "malito", "malita", "malo", "mala", "sick", "ill",
                  "unwell", "malade"}
_GERUND = ("ando", "iendo", "yendo", "ing")
#: "y", "pero", "¿y...?": she goes on with the same thing.
_CONTINUATION = re.compile(
    r"^(?:y|e|o|pero|tambien|entonces|vale|ok|o sea|osea|aunque|ademas|ya|"
    r"and|but|also|so|or|what about|how about|et|mais|aussi|donc|alors|ou)\b"
)
#: "así", "eso", "igual": she points back at what was being talked about.
_ANAPHORA = re.compile(
    r"\b(?:asi|eso|esto|lo mismo|igual|like this|like that|the same|comme ca|pareil)\b"
)
#: «lo baño con agua fria?», «je lui donne du doliprane?»: a question that opens on
#: the pronoun of the baby being talked about has no subject of its own. Read as
#: a new topic it lost the fever it was about (the battery, 2026-11-10).
#: «le»/«les» are never articles; «lo»/«la» are pronouns before a verb in the
#: first person («lo baño», «la abrigo»), articles before a noun («la caca»).
_POINTS_AT_HIM = re.compile(
    r"^(?:se )?(?:le|les) \w+|^(?:se )?(?:lo|la) \w+o\b|^(?:je|on) (?:le|la|lui|l') ?\w+|"
    r"^(?:should|can|do|shall) (?:i|we) \w+ (?:him|her|them)\b"
)
_AGE_FIX_WORDS = 8
_SHORT_WORDS = 5
#: A correction is short; a statement with nothing in common with the topic
#: is a topic of its own only from this long (a question from _SHORT_WORDS):
#: "Hoy no juega nada, se queda quieto en el sofá" after a fever goes on with
#: the fever, it is not a behaviour topic.
_SELF_CONTAINED_WORDS = 7
_SELF_CONTAINED_STATEMENT = 12

#: A worry about how the baby relates to others or communicates: not
#: playing, alone in a corner, not looking, not answering to his name, no
#: babbling. A pediatric nurse asks before answering it (ask_first).
_BEHAVIOUR = re.compile(
    r"\b(?:no (?:quiere )?juega\w*|no quiere jugar|no se mueve|sin moverse|"
    r"se queda (?:sentad\w*|quiet\w*|parad\w*|sol[oa]|en un rincon|en una esquina)|"
    r"en una esquina|en un rincon|no se relaciona|no interactua|no se junta|juega sol[oa]|"
    r"no (?:me )?mira|evita la mirada|no responde a su nombre|no reacciona a su nombre|"
    r"no sonrie|no habla|no dice (?:ninguna |ni una )?palabras?|no balbucea|no se[nñ]ala|"
    r"aislad\w*|se aisla|no le interesan? (?:los )?(?:otros )?nin\w*|"
    r"doesn'?t play|won'?t play|not playing|sits (?:alone|still|in a corner)|in a corner|"
    r"plays alone|doesn'?t interact|no eye contact|doesn'?t look at|"
    r"doesn'?t (?:respond|answer) to (?:his|her|their) name|not talking|doesn'?t talk|"
    r"not babbling|doesn'?t babble|withdrawn|"
    r"doesn'?t say (?:any |a )?words?|(?:isn'?t|not) saying (?:any )?words|no words yet|"
    r"ne dit (?:pas )?(?:encore )?(?:de |d'|aucun )?mots?|"
    r"ne joue pas|reste (?:assis|seul|immobile|dans un coin)|dans un coin|joue seul|"
    r"ne (?:me )?regarde pas|ne (?:repond|reagit) pas a son prenom|ne parle pas|"
    r"ne babille pas|isole)\b"
)
#: Illness words: "no juega y tiene fiebre" is a sick baby, not a behaviour topic.
_ILLNESS = re.compile(
    r"\b(?:fiebre|febricula|decimas|decaid\w*|mocos?|tos|tose|vomit\w*|diarrea|enferm\w*|"
    r"malit\w*|dolor|duele|respira\w*|fever\w*|sick|ill|cough\w*|vomit\w*|diarrh\w*|"
    r"fievre|malade|toux|tousse|vomi\w*|diarrhee)\b"
)
_NURSERY = re.compile(
    r"\b(?:guarderia|escuela infantil|escoleta|daycare|day care|nursery|child ?care|"
    r"creche|garderie)\b"
)
#: A drug or a dose (route._DRUG): never asked about, the coded refusal stands
#: (audit 3.1).

#: The corpus's words for a behaviour topic (Spanish: the corpus's language).
#: Searched as she wrote it, the guardería question found "niño enfermo en la
#: guardería" cards; the corpus has adaptation, separation anxiety and social
#: development (evidence_guarderia_adaptacion, evidence_desarrollo_0_24m).
_HINT_NURSERY = (
    "Sobre la adaptación a la guardería, la ansiedad por separación y el desarrollo social "
    "del bebé."
)
_HINT_BEHAVIOUR = (
    "Sobre el desarrollo social y de la comunicación del bebé: si mira, sonríe, responde a "
    "su nombre y juega."
)

#: Each signal the social_signals question names, and the corpus passage that
#: makes it a reason to consult (tests/test_conversation.py reads the corpus).
SIGNAL_SOURCES: dict[str, tuple[str, str]] = {
    "mira": ("Desarrollo: ¿Qué esperamos durante el primer año de vida?",
             "evite la mirada"),
    "sonríe": ("Desarrollo: ¿Qué esperamos durante el primer año de vida?",
               "no tener sonrisa social"),
    "responde a su nombre": ("Desarrollo: ¿Qué esperamos durante el primer año de vida?",
                             "no responda a su nombre"),
    "balbucea": ("El desarrollo del lenguaje y sus alteraciones: cuándo debo preocuparme "
                 "(Familia y Salud, AEPap)", "no emitir sílabas ni balbuceos"),
    "palabras": ("Desarrollo psicomotor y signos de alarma (Curso de Actualización "
                 "Pediatría, AEPap)", "no emitir ninguna palabra entre 12 y 18 meses"),
    "dejado de hacer": ("Desarrollo: ¿Qué esperamos durante el primer año de vida?",
                        "la pérdida o el retroceso de habilidades ya adquiridas"),
}

_STOPWORDS = frozenset("""
bebe bebes nino nina ninos ninas hijo hija hijos peque pequeno pequena tiene tengo tenia
tienen esta estan estaba estoy este esto eso esos esas estos estas como cuando donde porque
pero para sobre desde hasta hace hacer puede puedo pueden debe deberia seria todo todos
todas toda otro otra otros otras mucho mucha muchos muchas poco poca algo nada bien muy casi
siempre nunca normal dias meses semanas horas veces cada solo sola mismo misma entonces
tambien ahora ayer despues antes mientras aunque ademas quiere quieren sabe saber creo parece
sigue seguimos vale gracias hola perdona perdon pasa pasar verdad favor alguna alguno algun
ningun ninguna ninguno aqui alli tema nuevo cosa ella pregunta
baby babies child children have been does doesn what when where which with that this there
their they about should could would always never every days weeks months hours still also
just very much many some thing things really then today yesterday thanks sorry topic
enfant fils fille avec dans pour mais quand comment elle sont fait faire peut tous tout toute
toutes tres beaucoup encore toujours jamais jours mois semaines heures merci pardon aussi
alors donc depuis comme quoi quel quelle sujet chose
""".split())

_NOTED_OPENINGS = ("Anotado: ", "Noted: ", "C’est noté : ")
#: What the agent says the second time there is nothing (no_evidence_again).
_AGAIN: dict[str, str] = {
    "es": "Sigo sin fuentes sobre esto. Coméntalo con tu pediatra, que conoce a tu bebé.",
    "en": "I still have no sources on this. Please raise it with your pediatrician, who "
          "knows your baby.",
    "fr": "Je n’ai toujours pas de source à ce sujet. Parlez-en à votre pédiatre, qui "
          "connaît votre bébé.",
}
_VISIT_TITLE: dict[str, str] = {
    "es": "¿Lo anoto en su historial para la consulta?",
    "en": "Shall I note it in the record for the visit?",
    "fr": "Je le note dans son dossier pour la consultation\u00a0?",
}
_CONSULT_INTRO: dict[str, str] = {
    "es": "Para la consulta, esto es lo que me has contado:",
    "en": "For the visit, this is what you told me:",
    "fr": "Pour la consultation, voici ce que tu m’as raconté\u00a0:",
}


def no_evidence_again(locale: str) -> str:
    """The second "no sources" in one topic: one short line, never the paragraph again."""
    return _AGAIN.get(locale, _AGAIN["es"])


#: How the note below starts; the conversation battery checks the model got it.
REFUSED_NOTE_MARK = "Ya le dijiste en este tema que no tienes fuentes"


def refused_note(c: "Conversation", locale: str) -> str:
    """For the answering model, in a topic already told there is no evidence.

    The conversation battery with the real model (2026-11-11): a mixed answer
    closed each uncovered part with the whole coded paragraph again («la
    carne, cuánta», «agua fría», «por qué en la guardería»), three turns in
    one run. Prompt text, in Spanish like the contract's instructions: the
    part still gets no advice, only the short line instead of the paragraph.
    """
    if not c.refused:
        return ""
    return (
        f"{REFUSED_NOTE_MARK} sobre una parte. Si ahora una parte de lo que pregunta sigue "
        "sin fuente, no repitas la frase de rechazo entera: en un párrafo aparte, nombra esa "
        f"parte en negrita y sigue con estas palabras exactas: «{no_evidence_again(locale)}» "
        "Sobre esa parte no añadas nada más: ni una cifra, ni una pauta."
    )


# --- reading the transcript -----------------------------------------------------


def _exchanges(history: list[dict] | None) -> list[tuple[str, str]]:
    """(her message, the answer after it), oldest first; text turns only.

    A button she pressed is in the transcript as its label ("Menos de un mes
    · Sí, todo eso"); it is read back as the sentence the API folded into her
    message that turn, which is what she said."""
    pairs: list[list[str]] = []
    for item in history or []:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, str):
            continue
        if item.get("role") == "user":
            if pairs and is_clarify_question(pairs[-1][1]):
                content = _pressed(content, pairs[-1][1])
            pairs.append([content, ""])
        elif item.get("role") == "assistant" and pairs:
            pairs[-1][1] = f"{pairs[-1][1]}\n{content}".strip() if pairs[-1][1] else content
    return [(q, a) for q, a in pairs]


def _clarify_texts() -> frozenset[str]:
    return frozenset(
        normalize(by_locale[lang]["question"])
        for by_locale in CLARIFY_QUESTIONS.values() for lang in _LANGS if lang in by_locale
    )


_CLARIFY_TEXTS = _clarify_texts()


def is_clarify_question(answer: str) -> bool:
    """Whether an assistant turn was one of our clarify questions (and nothing else)."""
    lines = [normalize(line) for line in answer.splitlines() if line.strip()]
    return bool(lines) and all(line in _CLARIFY_TEXTS for line in lines)


_QUESTION_OF: dict[str, tuple[str, str]] = {
    normalize(by_locale[lang]["question"]): (field_name, lang)
    for field_name, by_locale in CLARIFY_QUESTIONS.items() for lang in _LANGS if lang in by_locale
}
_PRESS_SEPARATOR = " · "


def _pressed(user: str, asked: str) -> str:
    """The labels of the buttons she pressed, as the sentences they stand for."""
    fields = [_QUESTION_OF.get(normalize(line)) for line in asked.splitlines() if line.strip()]
    labels = [part.strip() for part in user.split(_PRESS_SEPARATOR)]
    if not fields or None in fields or len(labels) != len(fields):
        return user
    said = []
    for (field_name, lang), label in zip(fields, labels):
        q = CLARIFY_QUESTIONS[field_name][lang]
        option = next((o for o in [*q["options"], q["skip"]] if o["label"] == label), None)
        sentence = clarification_sentence(field_name, option["value"], lang) if option else None
        if sentence is None:
            return user
        said.append(sentence)
    return " ".join(said)


def _is_refusal(answer: str) -> bool:
    return any(no_evidence_reply(lang) in answer or _AGAIN[lang] in answer for lang in _LANGS)


def _is_record(answer: str) -> bool:
    return answer.startswith(_NOTED_OPENINGS)


_OPENINGS = tuple(red_flag_opening(lang) for lang in _LANGS)


def referral_code(answer: str) -> str | None:
    """The red flag an answer referred her for, or None if it was not a referral.

    The referral is code (answer_contract.red_flag_reply): its opening and its
    reason are verbatim, in whichever language it was said.
    """
    if not answer.lstrip().startswith(_OPENINGS):
        return None
    for code, reasons in RED_FLAG_REASONS.items():
        if any(reason in answer for reason in reasons.values()):
            return code
    return None


def _is_redirect(answer: str) -> bool:
    return any(out_of_scope_reply(lang) in answer for lang in _LANGS)


def _words(n: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", n)


def _stems(n: str) -> set[str]:
    return {w[:5] for w in _words(n) if len(w) >= 4 and w not in _STOPWORDS}


def _denied(pattern: re.Pattern[str], n: str) -> list[str]:
    frames = []
    for m in pattern.finditer(n):
        frame = next(g for g in m.groups() if g)
        if frame not in _NOT_A_FRAME and not frame.endswith(_GERUND) and frame not in frames:
            frames.append(frame)
    return frames


def _retracted(n: str, said: str) -> tuple[str, ...]:
    """What she takes back from the last answer, or () when her "no" adds a fact.

    Taken back: X when the answer talked about it, or when X is being ill
    (his "No es enfermo" answered a plan that never wrote the word). "No
    tiene fiebre" after a fever-laden answer is a correction; "no tiene
    hambre" after a sleep answer, or "no es la primera vez", is news. `said`
    is the answer as `_read_answer` gives it.
    """
    short = len(_words(n)) <= _SELF_CONTAINED_WORDS
    out: list[str] = []
    for frame in _denied(_DENY_IS, n):
        if frame[:5] in said or frame in _ILLNESS_FRAME:
            out.append(frame)
    for frame in _denied(_DENY_HAS, n):
        if frame[:5] in said or (short and frame in _ILLNESS_FRAME):
            out.append(frame)
    return tuple(dict.fromkeys(out))


#: A plan's sections of signs to watch for: what the answer names there is a
#: condition («si tiene fiebre»), not something it assumed about the baby.
_CONDITIONAL_HEADINGS = frozenset(
    normalize(PLAN_HEADINGS[lang][key]) for lang in _LANGS for key in ("watch", "doctor")
)
#: A reading in an answer («Con 38,7 °C») is a fever it assumed, word or not.
#: From 37,5: «agua a 37 grados» for a bath is not a fever.
_READING = re.compile(
    r"\b(?:37[.,][5-9]\d*|(?:3[89]|4[0-2])(?:[.,]\d+)?)\s*(?:°|º|grados?\b|degrees?\b)"
)
_FEVER_WORDS = " fiebre fever fievre"
#: A no of any kind in her words, or her own «quise decir»: without either,
#: nothing was taken back. The rules already catch the corrections with a no;
#: the ones that reach the classifier are mostly these («perdona, quise decir...»).
_NEGATION = re.compile(
    r"\b(?:no|not|ni|nunca|jamas|never|pas|non|nope|"
    r"quise decir|queria decir|me equivoque|me he equivocado|en realidad|perdona|perdon|"
    r"i meant|i mean|actually|sorry|my mistake|"
    r"je voulais dire|je veux dire|en fait|je me suis trompee?|pardon)\b|n't\b"
)


def _read_answer(text: str) -> str:
    """An answer normalized, with a reading read as the fever it is."""
    said = normalize(text)
    return said + _FEVER_WORDS if _READING.search(said) else said


def _assumed(answer: str) -> str:
    """The part of an answer that says what it took the baby to have, normalized:
    without the plan's sections of signs to watch for, and with a reading read
    as the fever it is. The conversation battery with the real model
    (2026-11-11): «no tiene fiebre» after a vomiting plan that listed fever only
    under «Cuándo ir al médico» was taken as a correction, and the answering
    model, without its own plan, wrote the same 330 words again."""
    kept, skipping = [], False
    for line in answer.splitlines():
        if line.lstrip().startswith("#"):
            skipping = normalize(line.lstrip("# ").strip()) in _CONDITIONAL_HEADINGS
            if skipping:
                continue
        if not skipping:
            kept.append(line)
    return _read_answer("\n".join(kept))


_SPLIT = re.compile(r"(?<=[.;!?])\s+|(?<=,)\s+|\s+(?=(?:pero|but|mais)\b)", re.IGNORECASE)


def _retracts(piece: str, retracted: tuple[str, ...]) -> bool:
    n = normalize(piece)
    if _NEW_TOPIC.search(n) and not _stems(_NEW_TOPIC.sub(" ", n)):
        return True
    if _GENERIC_DENIAL.search(n):
        return True
    denied = _denied(_DENY_IS, n) + _denied(_DENY_HAS, n)
    return any(frame in retracted for frame in denied)


def _without_retractions(text: str, retracted: tuple[str, ...] = ()) -> str:
    """Her message without the clauses that only take something back or say
    the topic changed ("Es tema nuevo. No tiene fiebre" leaves nothing): a
    denied word in the search pulls back the very cards she rejected. A
    clause that adds a fact stays. A message with nothing to take back comes
    back untouched."""
    pieces, last = [], 0
    for m in _SPLIT.finditer(text):
        pieces.append(text[last:m.start()])
        last = m.end()
    pieces.append(text[last:])
    kept = [p for p in pieces if p.strip() and not _retracts(p, retracted)]
    if len(kept) == len([p for p in pieces if p.strip()]):
        return text
    return " ".join(p.strip() for p in kept).strip(" ,;")


def _substantive(n: str) -> bool:
    """Whether a message says something of its own once markers and denials are out."""
    rest = _NEW_TOPIC.sub(" ", n)
    rest = _GENERIC_DENIAL.sub(" ", _DENY_HAS.sub(" ", _DENY_IS.sub(" ", rest)))
    stems = _stems(rest)
    return len(stems) >= 2 or ("?" in rest and len(stems) >= 1)


def _classify(message: str, prev: list[tuple[str, str]]) -> tuple[str, str, tuple[str, ...]]:
    """(kind, via, retracted) for one message given the exchanges before it."""
    if not prev:
        return "new", "first", ()
    n = normalize(message)
    last_q, last_a = prev[-1]
    marker = bool(_NEW_TOPIC.search(n))
    if is_clarify_question(last_a):
        if marker and _substantive(n):
            return "new", "rule", ()
        return "follow_up", "clarify", ()
    retracted = _retracted(n, _read_answer(last_a))
    generic = bool(_GENERIC_DENIAL.search(n))
    if retracted and not generic and not marker and not _retracted(n, _assumed(last_a)):
        # She denies a sign the answer only listed to watch for: news, in the topic.
        return "follow_up", "rule", ()
    if marker and _substantive(n) and not retracted and not generic:
        return "new", "rule", ()
    if retracted or generic or marker:
        return "correction", "rule", retracted
    if referral_code(last_a):
        # After a referral she goes on with it («le doy apiretal mientras», «puedo
        # esperar a mañana?»): only her own "otra cosa" opens another topic.
        return "follow_up", "rule", ()
    if _is_redirect(last_a):
        # Nothing to go on with about the baby after "only your baby": a message
        # that names him starts his topic; more about herself stays in hers.
        return ("new" if _BABY_REF.search(n) else "follow_up"), "rule", ()
    if (
        age_months_in(message) is not None
        and len(_words(n)) <= _AGE_FIX_WORDS
        and last_a and not _is_record(last_a)
    ):
        return "correction", "rule", ()
    opening = n.lstrip("¿¡( ")
    if _CONTINUATION.match(opening):
        return "follow_up", "rule", ()
    if _ANAPHORA.search(n) and len(_words(n)) < _SELF_CONTAINED_STATEMENT:
        return "follow_up", "rule", ()
    own = _stems(n)
    if len(_words(n)) <= _SHORT_WORDS and not own:
        return "follow_up", "rule", ()
    topic_stems = set().union(*(_stems(normalize(q)) for q, _ in prev[-TOPIC_MESSAGES:]))
    if own & topic_stems and not _is_record(last_a):
        return "follow_up", "rule", ()
    words = len(_words(n))
    if words >= _SELF_CONTAINED_STATEMENT:
        return "new", "rule", ()
    if _POINTS_AT_HIM.match(opening):
        # Undecided: the routing model, when it is called, may still say "new".
        return "follow_up", "default", ()
    if "?" in message and words >= _SHORT_WORDS:
        return "new", "rule", ()
    return "follow_up", "default", ()


@dataclass(frozen=True)
class Conversation:
    kind: TurnKind
    via: str
    #: The turn's message: hers, with her earlier question in front when she
    #: answers a clarify question in words (the guard and the router read it).
    message: str
    #: Her earlier messages in this topic, oldest first (the first is the anchor).
    topic: tuple[str, ...]
    search_query: str
    route_text: str
    prompt_question: str
    model_history: list[dict]
    route_history: list[dict]
    retracted: tuple[str, ...] = ()
    asked: bool = False
    refused: bool = False
    answering: bool = False
    behaviour: bool = False
    nursery: bool = False
    #: The red flag this topic was referred for (referral_code), or None.
    referral: str | None = None
    decided: bool = True
    # What `with_kind` needs to read the turn again.
    _history: tuple = field(default=(), repr=False, compare=False)
    _clarified: bool = field(default=False, repr=False, compare=False)


def _cut(text: str, limit: int = LINE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def _route_history(history: list[dict] | None) -> list[dict]:
    text = [m for m in history or [] if isinstance(m, dict) and isinstance(m.get("content"), str)
            and m.get("role") in ("user", "assistant")]
    return [{"role": m["role"], "content": _cut(m["content"], ROUTE_HISTORY_CHARS)}
            for m in text[-ROUTE_HISTORY_MESSAGES:]]


def _past(exchanges: list[tuple[str, str]]) -> tuple[int, list[tuple[str, ...]]]:
    """Where the current topic starts, and what each earlier message took back."""
    start, retracted = 0, [()]
    for i in range(1, len(exchanges)):
        kind, _, frames = _classify(exchanges[i][0], exchanges[:i])
        retracted.append(frames)
        restarts = kind == "correction" and _NEW_TOPIC.search(normalize(exchanges[i][0]))
        if kind == "new" or restarts:
            start = i if kind == "new" else i - 1
    return start, retracted


def _query_lines(lines: list[tuple[str, tuple[str, ...]]], *, whole_last: bool = False
                 ) -> list[str]:
    """Her messages for the search, one line each: the anchor and the latest,
    without what each one took back. Earlier ones are cut; with `whole_last`,
    the last one (what she writes now) never is."""
    if len(lines) > TOPIC_MESSAGES:
        lines = [lines[0], *lines[-(TOPIC_MESSAGES - 1):]]
    kept = []
    for i, (line, frames) in enumerate(lines):
        text = " ".join(_without_retractions(line, frames).split())
        kept.append(text if whole_last and i == len(lines) - 1 else _cut(text))
    return [line for line in kept if line]


def _hint(behaviour: bool, nursery: bool) -> str | None:
    if not behaviour:
        return None
    return _HINT_NURSERY if nursery else _HINT_BEHAVIOUR


def _bounded(head: list[str], now: str, hint: str | None) -> str:
    """The search text: earlier lines, what she writes now, the corpus's words.

    What she writes now is never cut (the search before this change never cut
    her question either). Earlier lines give way first, the middle ones
    before the first, which says what the topic is about.
    """
    keep = [now, *([hint] if hint else [])]
    head = [line for line in head if line]
    room = MAX_QUERY_CHARS - len("\n".join(keep)) - 1
    while len(head) > 1 and len("\n".join(head)) > room:
        head.pop(1)
    if head and len(head[0]) > room:
        head = [head[0][:room].rstrip()] if room > 0 else []
    return "\n".join([*head, *keep])


def read(
    message: str,
    history: list[dict] | None,
    *,
    clarified: bool = False,
    _force: str | None = None,
    _query: str | None = None,
) -> Conversation:
    """This turn in the conversation, from the transcript, by rules.

    `clarified` is the graph's: she pressed a clarify button this turn and
    `absorb` already put her answer into `message`.
    """
    exchanges = _exchanges(history)
    if clarified and exchanges and is_clarify_question(exchanges[-1][1]):
        kind, via, retracted = "follow_up", "clarify", ()
    else:
        kind, via, retracted = _classify(message, exchanges)
    decided = via != "default"
    if _force is not None:
        kind, via, retracted, decided = _force, "model", (), True
    if clarified:
        via = "clarify"

    start, past = _past(exchanges)
    if kind == "correction" and _NEW_TOPIC.search(normalize(message)) and exchanges:
        start = len(exchanges) - 1
    in_topic = exchanges[start:] if kind != "new" else []
    topic = tuple(q for q, _ in in_topic)
    # Her words in the topic, each with what it took back.
    said = list(zip(topic, past[start:])) if kind != "new" else []
    answering = via == "clarify" and not clarified
    asked = clarified or answering or any(is_clarify_question(a) for _, a in in_topic)
    refused = any(_is_refusal(a) for _, a in in_topic)
    referral = next((code for _, a in reversed(in_topic) if (code := referral_code(a))), None)

    head = _query_lines(said)
    if kind == "new" and not clarified:
        # A first message, or a topic of its own: exactly what she wrote.
        turn_message = route_text = prompt = message
        model_history: list[dict] = []
        head, now = [], message
    elif clarified:
        # A button answer: `absorb` already wrote it under her question.
        turn_message = route_text = prompt = message
        model_history = []
        head, now = [], message
    elif answering:
        # Her answer in words, read under what she asked (the guard sees both,
        # as with a button); the earlier answers are not needed, it is all here.
        now = message
        turn_message = route_text = prompt = "\n".join([*head, message])
        model_history = []
    else:
        turn_message = message
        now = _query_lines([(message, retracted)], whole_last=True)
        now = now[0] if now else ""
        if not now and head:
            head, now = head[:-1], head[-1]
        route_text = "\n".join([*head, now]) or message
        if kind == "correction":
            # The answers rest on the frame she rejected: her words go into the
            # prompt instead, and correction_note says what she took back.
            prompt = route_text
            model_history = []
        else:
            prompt = message
            model_history = [
                {"role": role, "content": text}
                for q, a in in_topic for role, text in (("user", q), ("assistant", a)) if text
            ][-MODEL_HISTORY_MESSAGES:]

    spoken = normalize("\n".join(
        _without_retractions(w, frames) for w, frames in [*said, (turn_message, retracted)]
    ))
    # An illness she denies («No tiene fiebre») does not make it a sick baby.
    behaviour = bool(_BEHAVIOUR.search(spoken)) and not _ILLNESS.search(_DENY_HAS.sub(" ", spoken))
    nursery = bool(_NURSERY.search(spoken))
    hint = _hint(behaviour, nursery) if (kind != "new" or clarified) else None
    if _query is not None and _query.strip():
        # The model's rewrite leads; her own words stay, so a detail it
        # paraphrased away is still searched.
        query = " ".join(_query.split())
        head = [_cut(query, MAX_QUERY_CHARS)]
        now = message if normalize(message) not in normalize(query) else ""
        if not now:
            head, now = [], head[0]
    if kind == "new" and not clarified and _query is None:
        search = message
    elif clarified:
        search = message if hint is None else f"{message}\n{hint}"
    else:
        search = _bounded(head, now, hint)

    return Conversation(
        kind=kind, via=via, message=turn_message, topic=topic,
        search_query=search, route_text=route_text, prompt_question=prompt,
        model_history=model_history, route_history=_route_history(history),
        retracted=retracted, asked=asked, refused=refused, answering=answering,
        behaviour=behaviour, nursery=nursery, referral=referral, decided=decided,
        _history=tuple(history or ()), _clarified=clarified,
    )


def with_kind(c: Conversation, kind: str | None, *, search_query: str | None = None
              ) -> Conversation:
    """The routing model's verdict, taken only where the rules could not decide."""
    if c.decided or kind not in ("new", "follow_up", "correction"):
        return c
    if kind == "correction" and not _NEGATION.search(normalize(c.message)):
        # Nothing in her words takes anything back («le puedo dar gotas para los
        # gases» after a colic answer, the real classifier, 2026-11-11): as a
        # correction the model is told its earlier answers were wrong.
        kind = "follow_up"
    query = search_query if kind != "new" else None
    return read(c.message, list(c._history), clarified=c._clarified, _force=kind,
                _query=query[:MAX_QUERY_CHARS] if query else None)


# --- what to ask, and what to give when nothing was found -------------------------


def _age_known(c: Conversation, facts: ProfileFacts | None) -> bool:
    if facts is not None and facts.age_months is not None:
        return True
    return age_months_in("\n".join([*c.topic, c.message])) is not None


def ask_first(c: Conversation, facts: ProfileFacts | None) -> list[str]:
    """The clarify round a behaviour topic gets before any answer, or [].

    One round per topic: once asked (by button or in words), never again.
    """
    if c.asked or not c.behaviour:
        return []
    if not _age_known(c, facts):
        return ["age", "social_signals"]
    return ["nursery_time" if c.nursery else "since_when", "social_signals"]


def ask_when_nothing_found(c: Conversation, facts: ProfileFacts | None, *, intent: str
                           ) -> list[str]:
    """Before saying there is no evidence: one round, for a worry she observed.

    Never for a fact question or a drug (the coded refusal is the answer
    there), never in a topic that already had its round, and never once the
    topic was told there is no evidence: the round comes before the refusal
    («y si le doy zumo de pera» after a half-refused constipation answer, the
    battery with the real model, 2026-11-11).
    """
    if c.asked or c.refused:
        return []
    if c.behaviour:
        return ask_first(c, facts)
    spoken = normalize("\n".join([*c.topic, c.message]))
    if intent != "plan" or _DRUG.search(spoken) or not _SYMPTOM.search(spoken):
        return []
    return ["since_when", "general_state"]


def _her_lines(c: Conversation) -> list[str]:
    lines = [*c.topic, *c.message.split("\n")] if c.kind != "new" else c.message.split("\n")
    seen: list[str] = []
    for line in lines:
        line = line.strip()
        kept = _without_retractions(line) if _NEW_TOPIC.search(normalize(line)) else line
        if kept and kept not in seen:
            seen.append(_cut(kept))
    return seen


def consult_note(c: Conversation, locale: str) -> str:
    """What she told us in this topic, in her words, to take to the visit.

    Nothing of ours: no source, no interpretation, no answer of AdelIA's.
    """
    intro = _CONSULT_INTRO.get(locale, _CONSULT_INTRO["es"])
    return "\n".join([intro, *(f"- «{line}»" for line in _her_lines(c))])


def visit_card_title(locale: str) -> str:
    return _VISIT_TITLE.get(locale, _VISIT_TITLE["es"])


def visit_note(c: Conversation) -> str:
    """The same words as one observation (a note) she can save for the visit."""
    return _cut(" / ".join(_her_lines(c)), VISIT_NOTE_CHARS)


def correction_note(c: Conversation) -> str:
    """For the answering model, after a correction: what she took back.

    Prompt text, in Spanish like the rest of the contract's instructions. It
    adds no clinical rule: it says the earlier answers do not apply.
    """
    if c.kind != "correction":
        return ""
    note = (
        f"Corrección de la madre: «{c.message.strip()}». Las respuestas anteriores de esta "
        "conversación partían de algo que ella dice que no es así: no las repitas y responde "
        "a lo que ha contado arriba, solo con las fuentes de abajo."
    )
    if c.retracted:
        note += f" No aplica: {', '.join(c.retracted)}."
    return note


__all__ = [
    "Conversation", "MAX_QUERY_CHARS", "ROUTE_HISTORY_CHARS", "ROUTE_HISTORY_MESSAGES",
    "SIGNAL_SOURCES", "ask_first", "ask_when_nothing_found", "consult_note",
    "correction_note", "is_clarify_question", "no_evidence_again", "read", "referral_code",
    "REFUSED_NOTE_MARK", "refused_note",
    "visit_card_title", "visit_note", "with_kind",
]
