"""Does "Cuándo ir al médico" stop saying "no tengo evidencia" when the library knows?

    cd apps/api            # inside the production API container
    python scripts/probe_warning_signs.py
    python scripts/probe_warning_signs.py --json /tmp/warning_signs.json

For settings.warning_signs_retrieval (agent/warning_signs.py) and
settings.no_unasked_refusals (services/answer_contract.py). Measured in prod on
2026-11-06 (demo, Claude, 30 real questions,
~/dev/adelia-design/shots/prod-domains-eval-after.json): four good answers
carried a section the model made up that ended in the coded refusal, the croup
plan's warning signs among them. This script asks those four and eight more
with clear warning signs (fever, bronchiolitis, otitis, vomiting, diarrhoea, a
bump on the head, a rash, constipation), then the croup question with a dose in
it (FOLLOW_UPS), through the agent graph with the demo's
own wiring: the demo baby, its router, its translation, its retrieval and the
production model (`demo_llm_provider`), twice per question, with both settings
OFF and then both ON, set in memory for this process only. Per question and
mode it prints the words, the sources cited, the title and "Tema:" of every
fragment handed to the model (cited or not), the bullets of "Cuándo ir al
médico" and whether the coded refusal appears, and where (the bold label or
the section that carries it).

The fragments matter because of what was measured next, the same day: the croup
question with a dose in it held the SEUP "cuándo ir a urgencias" paragraph in
its main search and wrote "Ve a urgencias si hace ruido al coger aire"; without
the dose its warning search brought only "síntomas y evolución de la
laringitis". The warning search now also reads the other paragraphs of the
guidelines the plan cites (evidence_retrieval.retrieve_evidence, `cited_sources`);
the "given" lines tell whether the paragraph on when to go arrives.

Cheap on purpose: one call at a time, PAUSE_SECONDS between calls, 13 questions
x 2 modes, so 26 generations at most.

Read only. Every database session it opens is `SET TRANSACTION READ ONLY` before
the first query, so a write would fail rather than happen. No spending gate is
called (the demo's daily counter is not touched) and nothing is persisted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Iterator

from sqlalchemy import text as sql

from adelia.agent.corpus_query import corpus_query
from adelia.agent.graph import GraphDeps, run_graph
from adelia.agent.route import log_route
from adelia.config import settings
from adelia.demo.fixture import demo_patient_context, demo_profile, retrieval_query
from adelia.enrichment.evidence_loader import embed_with_retry
from adelia.enrichment.evidence_retrieval import (
    retrieve_evidence,
    retrieve_experience,
    topic_of,
)
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import CONTRACTS, PLAN_HEADINGS
from adelia.services.chat_orchestrator import generate_answer

#: The four prod answers with a made-up refusal, word for word, then eight
#: topics whose parent guides carry clear warning signs. None trips the guard
#: for the demo baby (tests/test_probe_warning_signs.py): a referral measures
#: nothing.
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("crup", "es", "Tiene tos de perro por la noche, ¿qué puedo hacer en casa?"),
    ("panal", "es", "Tiene el culito muy rojo del pañal"),
    ("gatear", "es", "¿A qué edad suelen empezar a gatear?"),
    ("cabeza_plana", "es", "Tiene la cabeza un poco plana por detrás"),
    ("fiebre", "es", "Tiene 38,3 de fiebre desde esta mañana, ¿qué hago?"),
    ("bronquiolitis", "es", "Tiene bronquiolitis y muchos mocos, ¿qué puedo hacer en casa?"),
    ("otitis", "es", "Se toca mucho la oreja y llora, ¿puede ser otitis?"),
    ("vomitos", "es", "Ha vomitado dos veces esta mañana, ¿qué hago?"),
    ("diarrea", "es", "Tiene diarrea desde ayer, ¿qué hago?"),
    ("golpe_cabeza", "es", "Se ha dado un golpe en la cabeza con la mesa, ¿qué vigilo?"),
    ("exantema", "es", "Le han salido manchitas rojas por el cuerpo, ¿qué hago?"),
    ("estrenimiento", "es", "Hace caca muy dura y le cuesta, ¿qué puedo hacer?"),
)

#: The croup question with a dose in it: measured in prod with a main search that
#: already held the SEUP paragraph on when to go, so it is the one to compare the
#: first question with. Paracetamol, not ibuprofen: the demo baby is 5 months old.
FOLLOW_UPS: tuple[tuple[str, str, str], ...] = (
    ("crup_dosis", "es",
     "Tiene tos de perro por la noche, ¿le puedo dar 2,5 ml de paracetamol?"),
)

ALL_QUESTIONS = (*QUESTIONS, *FOLLOW_UPS)

#: Seconds between calls, so the run stays under the providers' rate.
PAUSE_SECONDS = 2.0

_SETTINGS = ("warning_signs_retrieval", "no_unasked_refusals")
_HEADING = re.compile(r"^\s*#{2,}\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_BOLD_LABEL = re.compile(r"^\s*\*\*(.+?)\*\*")


@dataclass
class Row:
    kind: str
    intent: str | None
    answer: str
    #: (tag, title) of the cards that went out with the answer.
    sources: list[tuple[str, str]] = field(default_factory=list)
    #: (tag, title, "Tema:") of every fragment handed to the model, cited or not.
    given: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def words(self) -> int:
        return len(self.answer.split())


@contextmanager
def mode(on: bool) -> Iterator[None]:
    """Both settings at `on` for the block, in memory, restored whatever happens."""
    saved = {name: getattr(settings, name) for name in _SETTINGS}
    try:
        for name in _SETTINGS:
            setattr(settings, name, on)
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def read_only(search):
    """A retrieval call whose session refuses writes before its first query."""
    async def _wrapped(session, **kwargs):
        await session.execute(sql("SET TRANSACTION READ ONLY"))
        return await search(session, **kwargs)
    return _wrapped


def fragment_topics(evidence) -> list[tuple[str, str, str]]:
    """(ev_N, title, topic) of each fragment in the order the model read them."""
    return [
        (f"ev_{i}", m.source_title, topic_of(m.content) or "")
        for i, m in enumerate(evidence, start=1)
    ]


def doctor_bullets(answer: str, locale: str) -> list[str]:
    """The bullets under the "Cuándo ir al médico" heading, up to the next heading."""
    title = PLAN_HEADINGS.get(locale, PLAN_HEADINGS["es"])["doctor"].lower()
    inside, bullets = False, []
    for line in answer.splitlines():
        heading = _HEADING.match(line)
        if heading:
            inside = heading.group(1).strip().lower() == title
            continue
        bullet = _BULLET.match(line) if inside else None
        if bullet:
            bullets.append(bullet.group(1))
    return bullets


def refusal_places(answer: str) -> list[str]:
    """Where the coded refusal sits: the bold label of its paragraph, else its
    section heading, else "(whole answer)". Any locale's refusal counts."""
    refusals = [c.refusal for c in CONTRACTS.values()]
    places: list[str] = []
    heading = None
    paragraph_label = None
    for line in answer.splitlines():
        if not line.strip():
            paragraph_label = None
            continue
        found = _HEADING.match(line)
        if found:
            heading, paragraph_label = f"## {found.group(1).strip()}", None
            continue
        label = _BOLD_LABEL.match(line)
        if paragraph_label is None and label:
            paragraph_label = label.group(1).strip().rstrip(":").strip()
        if any(r in line for r in refusals):
            places.append(paragraph_label or heading or "(whole answer)")
    return places


async def answer_once(qid: str, locale: str, question: str) -> Row:
    """One demo answer, as /api/demo/ask builds it, without the spending gate."""
    provider = settings.demo_llm_provider or None

    async def _route(message: str, **kwargs):
        return await log_route("probe", message, provider=provider, **kwargs)

    async def _generate(system_prompt: str, user_message: str) -> str:
        return await generate_answer(system_prompt, user_message, provider=provider)

    deps = GraphDeps(
        route=_route,
        # The demo's embedder, with backoff on 429 and 5xx (a prod run died on one).
        embed=lambda texts: embed_with_retry(list(texts)),
        retrieve_evidence=read_only(retrieve_evidence),
        retrieve_experience=read_only(retrieve_experience),
        generate=_generate,
        patient_context=demo_patient_context(locale),
        retrieval_text=lambda message: retrieval_query(message, locale),
        corpus_text=lambda text, lang: corpus_query(text, lang, provider=provider),
    )
    out = await run_graph(
        {
            "surface": "probe", "locale": locale, "message": question, "account": False,
            "facts": ProfileFacts(None, None, None, None, demo_profile(locale)["age_months"]),
        },
        deps,
    )
    return Row(
        kind=out["kind"],
        intent=out.get("intent"),
        answer=out.get("answer", ""),
        sources=[(c.get("tag", ""), c.get("title", "")) for c in out.get("evidence_citations", [])],
        given=fragment_topics(out.get("evidence") or []),
    )


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def run_all(questions) -> list[tuple[tuple[str, str, str], Row, Row]]:
    """Each question OFF then ON, one call at a time, a pause between calls."""
    rows = []
    first = True
    for qid, locale, question in questions:
        pair = []
        for on in (False, True):
            if not first:
                await _pause(PAUSE_SECONDS)
            first = False
            with mode(on):
                pair.append(await answer_once(qid, locale, question))
        rows.append(((qid, locale, question), pair[0], pair[1]))
    return rows


def print_row(q: tuple[str, str, str], off: Row, on: Row) -> None:
    qid, locale, question = q
    print(f"\n[{qid}] ({locale}) {question}")
    for name, row in (("off", off), ("on ", on)):
        places = refusal_places(row.answer)
        print(f"  {name} kind {row.kind}  intent {row.intent}  words {row.words}  "
              f"refusal {'yes: ' + ' | '.join(places) if places else 'no'}")
        for tag, title in row.sources:
            print(f"       source  [{tag}] {title:.80}")
        for tag, title, topic in row.given:
            print(f"       given   [{tag}] {title}: {topic}")
        for bullet in doctor_bullets(row.answer, locale):
            print(f"       doctor  - {bullet:.110}")


async def main_async(args) -> int:
    rows = await run_all(ALL_QUESTIONS)
    for q, off, on in rows:
        print_row(q, off, on)
    print("\n== summary (cut-off %.2f, margin %.2f)" % (
        settings.evidence_max_distance, settings.evidence_relative_margin))
    for name, pick in (("off", 1), ("on ", 2)):
        picked = [r[pick] for r in rows]
        print(f"  {name} answers with the refusal inside: "
              f"{sum(1 for r in picked if r.kind == 'answer' and refusal_places(r.answer))}"
              f"/{len(picked)}  with doctor bullets: "
              f"{sum(1 for (q, *_), r in zip(rows, picked) if doctor_bullets(r.answer, q[1]))}"
              f"  words: {sum(r.words for r in picked)}")
    if args.json:
        payload = [
            {"id": q[0], "locale": q[1], "question": q[2],
             **{name: asdict(r) | {"words": r.words, "refusal": refusal_places(r.answer),
                                   "doctor": doctor_bullets(r.answer, q[1])}
                for name, r in (("off", off), ("on", on))}}
            for q, off, on in rows
        ]
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", help="also write every answer to this file")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
