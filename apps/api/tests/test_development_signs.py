"""The development signs search: when a milestone or a behaviour is the worry.

The battery with the real model (2026-11-11, docs/BATERIA_MODELO_2026-11-11.md):
«no gatea y ya tiene 10 meses» was answered from UNICEF alone, with no
«Cuándo ir al médico»; the guardería conversation, after «No es enfermo», had
the sick child's «Cuándo ir al médico» (a nursery-exclusion guide) and none of
the development warning signs the corpus holds (AEPap «Desarrollo psicomotor y
signos de alarma», SAP «Desarrollo: ¿Qué esperamos durante el primer año?», the
WHO motor study). What these tests pin (agent/development_signs.py):

  * which topics are about development: a milestone she says is not there yet,
    or the thread's behaviour topic; a sick baby is not one;
  * the words added to the search, each written in the corpus;
  * how its fragments join the main ones: after them, at most two, never into
    an empty list.
"""
from __future__ import annotations

import json
import unicodedata
from uuid import uuid4

import pytest

from adelia.agent import development_signs as ds
from adelia.clinical.golden import CORPUS_DATA_DIR
from adelia.enrichment.evidence_retrieval import EvidenceMatch


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


@pytest.mark.parametrize("message", [
    "no gatea y ya tiene 10 meses",
    "¿Es normal que no gatee a los 9 meses?",
    "Todavía no gatea",
    "Tiene 8 meses y no se sienta solo",
    "Con 15 meses aún no anda",
    "no camina y tiene 16 meses",
    "No ha empezado a andar",
    "Tiene 4 meses y no sostiene la cabeza",
    "No se da la vuelta",
    "Creo que tiene un retraso en el desarrollo",
    "My 10-month-old is not crawling yet",
    "She isn't walking at 15 months",
    "Il ne rampe pas encore",
    "Il ne marche pas encore à 16 mois",
])
def test_a_milestone_that_is_not_there_yet_is_a_development_topic(message):
    assert ds.is_development_topic(message), message


@pytest.mark.parametrize("message", [
    "No come nada y tiene fiebre",
    "no se mueve y tiene fiebre",                 # a sick baby, not a milestone
    "No anda bien de la tripa",                   # "anda" of how she is doing
    "¿A qué edad suelen empezar a gatear?",        # a question of age, no worry
    "Le cuesta dormir",
    "Il ne mange pas",
    "Le tire-lait ne marche pas",
    "",
])
def test_a_sick_baby_or_another_worry_is_not(message):
    assert not ds.is_development_topic(message), message


class _Conv:
    def __init__(self, behaviour: bool):
        self.behaviour = behaviour


def test_the_thread_s_behaviour_topic_counts_and_so_do_her_words():
    """A behaviour topic (agent/conversation) is development's too, whatever
    the last turn says («No es enfermo»); otherwise her words in the topic."""
    assert ds.applies({"conversation": _Conv(True), "message": "No es enfermo"})
    assert ds.applies({"conversation": _Conv(False), "message": "y ahora qué",
                       "search_query": "no gatea y ya tiene 10 meses\ny ahora qué"})
    assert not ds.applies({"conversation": _Conv(False), "message": "Tiene diarrea"})
    assert ds.applies({"message": "Tiene 8 meses y no se sienta solo"})


def test_the_search_is_the_topic_then_the_development_words():
    query = ds.signs_query("  no gatea y ya tiene 10 meses ")
    assert query == f"no gatea y ya tiene 10 meses\n{ds.DEVELOPMENT_TERMS}"


def _corpus_text() -> str:
    parts: list[str] = []
    for path in sorted(CORPUS_DATA_DIR.glob("evidence_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for source in payload["sources"]:
            if "pediatrics" in (source.get("specialties") or []):
                parts.append(source["title"])
                parts.extend(source["chunks"])
    return _plain(" ".join(parts))


def test_every_development_word_is_written_in_the_corpus():
    corpus = _corpus_text()
    words = [w.strip() for w in ds.DEVELOPMENT_TERMS.replace(":", ",").split(",")]
    assert [w for w in words if w and _plain(w) not in corpus] == []


def _match(distance: float, source=None, title="Fuente") -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid4(), source_id=source or uuid4(), source_title=title,
        organization="AEPap", publication_year=2024, url=None, content="Tema: algo.",
        chunk_index=0, distance=distance,
    )


def test_its_fragments_come_after_the_main_ones_at_most_two():
    main = [_match(0.15, title="UNICEF")]
    extra = [_match(0.16, title="AEPap signos de alarma"), _match(0.17, title="OMS"),
             _match(0.18, title="AEPap normal")]
    out = ds.add_signs_fragments(main, extra)
    assert [m.source_title for m in out] == ["UNICEF", "AEPap signos de alarma", "OMS"]


def test_a_fragment_already_held_is_not_added_twice():
    held = _match(0.15, title="UNICEF")
    out = ds.add_signs_fragments([held], [held, _match(0.17, title="OMS")])
    assert [m.source_title for m in out] == ["UNICEF", "OMS"]


def test_nothing_found_stays_nothing_found():
    """The golden B2 («¿Es normal que no gatee a los 9 meses?») has nothing under
    the cut: the development search never turns a refusal into an answer."""
    assert ds.add_signs_fragments([], [_match(0.12)]) == []
