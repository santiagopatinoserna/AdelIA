"""Does putting the baby back find a mother's sources, and at what cost?

    cd apps/api            # inside the production API container
    python scripts/eval_implicit_subject.py
    python scripts/eval_implicit_subject.py --json /tmp/implicit_subject.json
    python scripts/eval_implicit_subject.py --no-translate   # fr/en embedded as written

For settings.implicit_subject_expansion (agent/implicit_subject.py). There is
no embeddings key where the rules were written, so no distance was measured;
this script is the measurement, for whoever decides whether the setting goes
on. It runs every probe twice through the agent graph's own retrieve node (the
demo's wiring, with each probe's age as the profile's), with the setting OFF and
then ON, set in memory for this process only, and prints, as
scripts/eval_lay_language.py does, the best uncut distance of each searched
text, the titles that passed the production cut-offs (unchanged) and the
summary per group. The other retrieval settings (lay_query_expansion,
warning_signs_retrieval) stay as the environment sets them, and are printed.

Probes: 20 sentences without a subject on the commonest worries (fever,
diarrhoea, vomiting, a runny nose, not eating, not sleeping...) in es/fr/en,
the fever button flow ("Tiene fiebre, ¿qué hago?" then "38 a 38,9 °C", with and
without "Mi bebé"), and groups A and B of the golden set (clinical/golden.py).
Of group B only B2 and B3 name nobody, so only they get the second search
(tests/test_implicit_subject.py pins the list); the others are controls.

Read only, like its sibling: every database session is `SET TRANSACTION READ
ONLY` before its first query, no spending gate is called, the router is a fixed
stub and generation a constant string, so the only paid calls are the
embeddings (through `embed_with_retry`, which backs off on 429 and 5xx) and,
for fr/en probes, one translation each, cached across modes. It waits
PAUSE_SECONDS between probes. Guarded probes (a red flag, or a child of 3 or
more) never search, in either mode.

Exit status: 0 when no group B probe is under the cut with the setting on that
was not under it with the setting off; 1 otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text as sql

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_lay_language as lay  # noqa: E402

from adelia.agent.corpus_query import corpus_query  # noqa: E402
from adelia.agent.graph import GraphDeps, run_graph  # noqa: E402
from adelia.agent.implicit_subject import subject_query  # noqa: E402
from adelia.agent.route import RouteDecision  # noqa: E402
from adelia.clinical.golden import questions  # noqa: E402
from adelia.config import settings  # noqa: E402
from adelia.db import AsyncSessionLocal  # noqa: E402
from adelia.demo.fixture import AGE_MONTHS, retrieval_query  # noqa: E402
from adelia.enrichment.evidence_loader import embed_with_retry  # noqa: E402
from adelia.enrichment.evidence_retrieval import retrieve_evidence  # noqa: E402
from adelia.enrichment.profile_service import ProfileFacts  # noqa: E402

ModeResult = lay.ModeResult
PAUSE_SECONDS = lay.PAUSE_SECONDS

#: The worries mothers bring most, written as they write them: nobody named.
#: S1 and S2 are the production misses of 2026-11-06, word for word.
SUBJECTLESS: tuple[tuple[str, str, str], ...] = (
    ("S1", "es", "Tiene 38,3 de fiebre desde esta mañana, ¿qué hago?"),
    ("S2", "es", "Tiene diarrea desde ayer, ¿qué hago?"),
    ("S3", "es", "Ha vomitado dos veces después de comer, ¿qué hago?"),
    ("S4", "es", "Tiene mocos desde hace una semana, ¿qué hago?"),
    ("S5", "es", "No come casi nada desde ayer, ¿es normal?"),
    ("S6", "es", "No duerme bien por las noches, ¿qué puedo hacer?"),
    ("S7", "es", "Tiene tos desde hace tres días, ¿qué hago?"),
    ("S8", "es", "Está estreñido, ¿qué puedo hacer?"),
    ("S9", "es", "Llora mucho por las noches y no sé por qué"),
    ("S10", "es", "Le están saliendo los dientes, ¿cómo le alivio el dolor?"),
    ("S11", "es", "Tiene fiebre, ¿cuándo tengo que llevarlo al médico?"),
    ("S12", "es", "Regurgita mucho después de las tomas, ¿es normal?"),
    ("S13", "fr", "Il a 38,3 de fièvre depuis ce matin, que faire ?"),
    ("S14", "fr", "Elle a la diarrhée depuis hier, que faire ?"),
    ("S15", "fr", "Il vomit après chaque biberon, c’est normal ?"),
    ("S16", "fr", "Elle ne dort pas la nuit, que faire ?"),
    ("S17", "en", "She has had a fever of 38.3 since this morning, what should I do?"),
    ("S18", "en", "He has had diarrhoea since yesterday, what should I do?"),
    ("S19", "en", "He has a runny nose and a cough, what can I do?"),
    ("S20", "en", "She won't eat anything since yesterday, is that normal?"),
)

#: The fever button flow: her message, then the thermometer band she pressed.
FEVER_BUTTON = {"field": "temperature", "value": "38-38.9"}
CLARIFIED: tuple[tuple[str, str, str], ...] = (
    ("K1", "es", "Tiene fiebre, ¿qué hago?"),
    ("K2", "es", "Mi bebé tiene fiebre, ¿qué hago?"),
)


@dataclass
class SubjectProbe(lay.Probe):
    #: Her answer to the clarify question, absorbed into the message by the graph.
    clarification: dict | None = None


def probes() -> list[SubjectProbe]:
    out = [SubjectProbe(i, "subject", loc, q, AGE_MONTHS) for i, loc, q in SUBJECTLESS]
    out += [
        SubjectProbe(i, "clarified", loc, q, AGE_MONTHS, clarification=dict(FEVER_BUTTON))
        for i, loc, q in CLARIFIED
    ]
    for group in ("A", "B"):
        out += [
            SubjectProbe(q.id, group, q.locale, q.question, q.age_months, q.expect_source)
            for q in questions(group)
        ]
    return out


async def _read_only(session) -> None:
    await session.execute(sql("SET TRANSACTION READ ONLY"))


async def _nearest(vector: list[float]) -> tuple[float | None, str | None]:
    """The closest pediatric fragment with no cut-off at all (diagnostic only)."""
    async with AsyncSessionLocal() as session:
        await _read_only(session)
        rows = await retrieve_evidence(
            session, query_embedding=vector, specialties=["pediatrics"], top_k=1,
            max_distance=2.0, relative_margin=None,
        )
    return (rows[0].distance, rows[0].source_title) if rows else (None, None)


async def run_probe(probe: SubjectProbe, *, on: bool, translate: bool, cache: dict) -> ModeResult:
    settings.implicit_subject_expansion = on
    embedded: list[tuple[str, list[float]]] = []

    async def _route(message, **kwargs):
        return RouteDecision(intent="question", confidence=1.0, via="rule")

    async def _embed(texts):
        vectors = await embed_with_retry(list(texts))
        embedded.extend(zip(texts, vectors))
        return vectors

    async def _retrieve(session, **kwargs):
        await _read_only(session)
        return await retrieve_evidence(session, **kwargs)

    async def _generate(system_prompt, user_message):
        return "Respuesta de evaluación [ev_1]."

    async def _corpus_text(text, locale):
        if not translate:
            return text
        key = (text, locale)
        if key not in cache:
            provider = settings.demo_llm_provider or None
            cache[key] = await corpus_query(text, locale, provider=provider)
        return cache[key]

    deps = GraphDeps(
        route=_route, embed=_embed, retrieve_evidence=_retrieve, generate=_generate,
        retrieval_text=lambda message: retrieval_query(message, probe.locale),
        corpus_text=_corpus_text,
    )
    out = await run_graph(
        {
            "surface": "eval", "locale": probe.locale, "message": probe.question,
            "account": False, "facts": ProfileFacts(None, None, None, None, probe.age_months),
            "clarification": probe.clarification,
        },
        deps,
    )
    result = ModeResult(kind=out["kind"])
    if out["kind"] == "red_flag" or out.get("out_of_scope"):
        result.guarded = True
        return result
    for searched, vector in embedded:
        distance, title = await _nearest(vector)
        result.nearest.append((searched, distance, title))
    result.cards = [(m.source_title, round(m.distance, 4)) for m in out.get("evidence") or []]
    return result


def b_with_variant() -> list[str]:
    """The group B questions that get the second search, from her words alone."""
    return [
        q.id for q in questions("B")
        if subject_query(q.question, locale=q.locale, age_months=q.age_months) is not None
    ]


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def main_async(args) -> int:
    cache: dict = {}
    rows: list[tuple[SubjectProbe, ModeResult, ModeResult]] = []
    original = settings.implicit_subject_expansion
    print(f"lay_query_expansion={settings.lay_query_expansion} "
          f"warning_signs_retrieval={settings.warning_signs_retrieval} (as configured)")
    print(f"group B with the second search: {b_with_variant() or 'none'}")
    try:
        for n, probe in enumerate(probes()):
            if n:
                await _pause(PAUSE_SECONDS)
            off = await run_probe(probe, on=False, translate=not args.no_translate, cache=cache)
            on = await run_probe(probe, on=True, translate=not args.no_translate, cache=cache)
            rows.append((probe, off, on))
            lay.print_row(probe, off, on)
    finally:
        settings.implicit_subject_expansion = original
    summary = lay.summarise(rows)
    print("\n== summary (cut-off %.2f, margin %.2f)" % (
        settings.evidence_max_distance, settings.evidence_relative_margin))
    for mode in ("off", "on"):
        for group, g in summary[mode].items():
            print(f"  {mode:3} {group:9} under the cut {g['under_cut']:2}/{g['probes']:<2}"
                  f"  expected source {g['expected']}")
    newly = summary["new_b_under_cut"] or "none"
    print(f"  group B newly under the cut with the setting on: {newly}")
    if args.json:
        payload = {
            "summary": summary,
            "rows": [
                {"probe": asdict(p), "off": asdict(off) | {"best": off.best},
                 "on": asdict(on) | {"best": on.best}}
                for p, off, on in rows
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    return 1 if summary["new_b_under_cut"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", help="also write every row to this file")
    parser.add_argument("--no-translate", action="store_true",
                        help="embed fr/en probes as written (no translation call)")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
