"""The development signs search: when a milestone or a behaviour is the worry.

Measured with the real model on 2026-11-11 (the conversation battery, production,
docs/BATERIA_MODELO_2026-11-11.md): «no gatea y ya tiene 10 meses» was answered
from UNICEF alone, a guide with no warning signs, so the plan had no «Cuándo ir
al médico»; in the guardería conversation, after «No es enfermo», the search
found adaptation and nursery-exclusion guides and the only «Cuándo ir al médico»
the model could write was the sick child's. The corpus has the development
warning signs (AEPap «Desarrollo psicomotor y signos de alarma», SAP
«Desarrollo: ¿Qué esperamos durante el primer año de vida?», the WHO motor
development study); her words and the follow-up's hint never reached them.

So, behind settings.development_signs_retrieval (off by default), the account
search (chat_orchestrator.retrieve_for_account, which the /dashboard agent lends
the graph) embeds one more text in the same call when the topic is about
development: the topic as searched, then DEVELOPMENT_TERMS on a second line. It
is searched under the same two cut-offs (evidence_max_distance and the relative
margin, untouched) and up to two fragments the main search did not hold are
added after the main ones (add_signs_fragments), so the model is handed them
and compose keeps the card of each one it cites. What it can and cannot do:

* it adds nothing when the main search found nothing: a question without
  evidence is still refused by the code (B2 of the golden set, «¿Es normal que
  no gatee a los 9 meses?», has nothing under the cut: 0.2164 to UNICEF with
  the recorded vector, the same in prod on 2026-11-06);
* it runs for any shape of answer: the prefetch searches before the intent is
  known, and the short answer to «¿es normal que no gatee?» is when to consult;
* the guard has already run on her words: a red flag never gets here;
* the main fragments keep their order and their [ev_N] numbers.

Unlike agent/warning_signs.py, it does not look inside the sources already
retrieved first: the paragraph it wants is in another source (the guardería
topic retrieves adaptation guides, whose "cuándo" is about illness).

A topic is about development when the thread already reads it as a behaviour
topic (agent/conversation `behaviour`: not playing, not looking, no words), or
when her words in the topic say a motor milestone is not there yet. A sick
baby is not one: "no se mueve y tiene fiebre" is the fever's.

The words are Spanish whatever her language: they go after the corpus
rendering of her words (corpus_query.py), which is Spanish.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from adelia.agent.lay_terms import fold
from adelia.enrichment.evidence_retrieval import EvidenceMatch

#: The corpus's own words for it, each written in the pediatric corpus
#: (tests/test_development_signs.py reads the files): the topic lines of AEPap
#: («cómo interpretar un hito que se retrasa»), SAP («hitos y señales de alerta»)
#: and the WHO study («hitos motores»).
DEVELOPMENT_TERMS = (
    "desarrollo psicomotor, hitos motores, señales de alerta, signos de alarma, "
    "un hito que se retrasa, cuándo consultar"
)

#: Most of the fragments a turn may add.
MAX_ADDED = 2

#: A motor milestone she says is not there yet, read on folded text (no accents).
#: "No anda bien" is how she is doing; "le tire-lait ne marche pas" is a machine.
_MOTOR = re.compile(
    r"\bno\s+(?:\w+\s+){0,2}?(?:gatea\w*|gatee\w*|se\s+sienta\w*|se\s+sostiene|"
    r"se\s+pone\s+de\s+pie|se\s+levanta\s+solo|sostiene\s+la\s+cabeza|"
    r"se\s+da\s+la\s+vuelta|se\s+voltea|repta\w*|se\s+arrastra)\b"
    r"|\bno\s+(?:\w+\s+){0,1}?(?:anda|camina)\b(?!\s+(?:bien|mal|de|muy|fino|nada\s+bien))"
    r"|\bno\s+(?:ha\s+)?(?:empezado\s+a\s+)?(?:gatear|gateado|andar|andado|caminar|caminado)\b"
    r"|\bsin\s+gatear\b|\bretras\w*\s+(?:en\s+el\s+|del\s+)?(?:desarrollo|motor|psicomotor)\b"
    r"|\b(?:not|isn'?t|hasn'?t|doesn'?t|won'?t|can'?t)\s+(?:\w+\s+){0,1}?"
    r"(?:crawl\w*|walk\w*|sit\w*\s+up|sitting|stand\w*|roll\w*\s+over|"
    r"hold\w*\s+(?:his|her|their)\s+head)\b"
    r"|\bdevelopmental\s+delay\b|\bmilestones?\b"
    r"|\b(?:il|elle|bebe)\s+ne\s+(?:rampe|marche|se\s+tient|tient|s'assoit|se\s+met)\s+"
    r"(?:pas|plus)\b|\bretard\s+(?:de\s+|du\s+)?(?:developpement|moteur|psychomoteur)\b"
)


def _illness():
    # agent/conversation's own reading of a sick baby, so both agree.
    from adelia.agent import conversation

    return conversation._ILLNESS, conversation._DENY_HAS


def is_development_topic(text: str | None) -> bool:
    """Whether her words say a motor milestone is not there yet, and no illness."""
    folded = fold(text or "")
    if not folded.strip() or not _MOTOR.search(folded):
        return False
    illness, denied = _illness()
    return not illness.search(denied.sub(" ", folded))


def applies(state: Mapping) -> bool:
    """Whether this turn's topic is about development (see the module docstring)."""
    c = state.get("conversation")
    if c is not None and getattr(c, "behaviour", False):
        return True
    return is_development_topic(state.get("search_query") or state.get("message"))


def signs_query(text: str) -> str:
    """The topic as searched, then the development words on a second line."""
    return f"{text.strip()}\n{DEVELOPMENT_TERMS}"


def add_signs_fragments(
    main: Sequence[EvidenceMatch], extra: Sequence[EvidenceMatch], *, limit: int = MAX_ADDED
) -> list[EvidenceMatch]:
    """The main search, then up to `limit` fragments of the development search.

    The main list keeps its order and so its [ev_N] numbers; a fragment it
    already holds is not added again; the rest come in the order the search
    ranked them (by distance, one per source, under both cut-offs). An empty
    main list stays empty: this never turns a refusal into an answer.
    """
    if not main:
        return []
    seen = {m.chunk_id for m in main}
    new: list[EvidenceMatch] = []
    for match in extra:
        if match.chunk_id in seen:
            continue
        seen.add(match.chunk_id)
        new.append(match)
    return [*main, *new[: max(limit, 0)]]
