"""Does the lay lexicon help a mother's words find their sources, and at what cost?

    cd apps/api            # inside the production API container
    python scripts/eval_lay_language.py
    python scripts/eval_lay_language.py --json /tmp/lay_language.json
    python scripts/eval_lay_language.py --no-translate   # fr/en embedded as written

For settings.lay_query_expansion (agent/lay_terms.py). There is no embeddings
key where the lexicon was written, so no distance was measured; this script
is the measurement, for whoever decides whether the setting goes on. It runs
every probe twice through the agent graph's own retrieve node (the demo's
wiring), with the setting OFF and then ON, set in memory for this process
only, and prints for each probe:

  * the best distance to the pediatric corpus with no cut-off (one row per
    searched text, so ON shows the better of her sentence and her sentence
    plus the terms), and the title it belongs to;
  * the titles that passed the production cut-offs (evidence_max_distance and
    evidence_relative_margin, unchanged), with their distances;
  * the terms the lexicon added.

Probes: the seven production misses of 2026-11-05, 23 colloquial questions
(every domain, es/fr/en, L23 the control with no lay word), the everyday
complaints added on 2026-11-06 (two left out of the lexicon on purpose), the
bump on the head of 2026-11-11 (H1-H5, each expecting SEUP's sheet), and
groups A and B of the golden set (clinical/golden.py). The summary counts, per mode, the
probes answered with evidence, the group A probes whose expected source is in
the cards, and the group B probes that fall UNDER the cut. Any B that moves
under the cut with the setting on is a reason to keep it off.

Read only. Every database session it opens is `SET TRANSACTION READ ONLY`
before the first query, so a write would fail rather than happen; no spending
gate is called (the demo's daily counter is not touched), the router is a
fixed stub and generation a constant string, so the only paid calls are the
embeddings and, for fr/en probes, one translation each (cached across modes,
as `corpus_query` is in production). Embeddings go through `embed_with_retry`
(backoff on 429 and 5xx) and the script waits PAUSE_SECONDS between probes:
the prod run of 2026-11-06 died halfway on a Mistral 429. Guarded probes (a red flag, or a child
of 3 or more) never search, in either mode, and are shown as such.

Exit status: 0 when no group B probe is under the cut with the setting on
that was not under it with the setting off; 1 otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field

from sqlalchemy import text as sql

from adelia.agent import lay_terms
from adelia.agent.corpus_query import corpus_query
from adelia.agent.graph import GraphDeps, run_graph
from adelia.agent.route import RouteDecision
from adelia.clinical.golden import questions, source_matches
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.demo.fixture import AGE_MONTHS, retrieval_query
from adelia.enrichment.evidence_retrieval import retrieve_evidence
from adelia.enrichment.profile_service import ProfileFacts
from adelia.enrichment.evidence_loader import embed_with_retry

#: Measured in production on 2026-11-05 (~/dev/adelia-design/shots/prod-domains-eval.json),
#: word for word. The corpus covers every one of them.
PROD_MISSES: tuple[tuple[str, str, str], ...] = (
    ("P1", "es", "Lleva 4 días sin hacer caca y toma pecho, ¿es normal?"),
    ("P2", "es", "Tiene el culito muy rojo del pañal"),
    ("P3", "es", "Le han salido granitos en las manos y en la boca"),
    ("P4", "es", "Tiene un ojo con legañas amarillas"),
    ("P5", "es", "¿Cuándo se le cae el cordón umbilical y cómo lo cuido?"),
    ("P6", "es", "¿A qué edad suelen empezar a gatear?"),
    ("P7", "es", "Tiene tos de perro por la noche, ¿qué puedo hacer en casa?"),
)

#: Colloquial questions written for this measurement. L23 is the control with
#: no lay word: both modes must return the same thing for it. L22 was one too
#: until the night-waking entry of 2026-11-06.
COLLOQUIAL: tuple[tuple[str, str, str], ...] = (
    ("L1", "es", "Tiene muchos mocos verdes y la nariz tapada, ¿qué hago?"),
    ("L2", "es", "Echa la leche después de cada toma, ¿es normal?"),
    ("L3", "es", "Hace las cacas muy duras y le cuesta mucho"),
    ("L4", "es", "Se levanta con los ojos pegados"),
    ("L5", "es", "Le llora un ojo todo el rato desde que nació"),
    ("L6", "es", "Se toca mucho la oreja y está muy llorón"),
    ("L7", "es", "Creo que mi bebé está un poco bizco"),
    ("L8", "es", "Tiene costras en la cabeza que no se le quitan"),
    ("L9", "es", "Tiene la piel muy seca y áspera"),
    ("L10", "es", "Le ha salido un sarpullido en la tripa y la espalda"),
    ("L11", "es", "Le huele mal el ombligo"),
    ("L12", "es", "Tiene el ombligo salido cuando llora"),
    ("L13", "es", "Le están saliendo los dientes y babea muchísimo"),
    ("L14", "es", "Tiene un bulto en la ingle que se nota más al llorar"),
    ("L15", "es", "Tose como un perro y está ronca"),
    ("L16", "es", "Tiene el culete irritado y con granitos"),
    ("L17", "fr", "Mon bébé a les fesses toutes rouges, que faire ?"),
    ("L18", "fr", "Elle a les yeux collés le matin"),
    ("L19", "fr", "Il a une toux de phoque la nuit"),
    ("L20", "en", "My baby has a runny nose and a stuffy nose, what can I do?"),
    ("L21", "en", "She has spots on her hands and in her mouth"),
    ("L22", "es", "No duerme nada por la noche, se despierta cada hora"),
    ("L23", "es", "Estoy agotada y lloro todos los días desde el parto"),
)

#: The complaints mothers of 0-24 months bring most, added to the lexicon on
#: 2026-11-06 (agent/lay_terms.py). E9 and E10 have no entry on purpose: gas is
#: B11's word, and evening crying is pinned as a false friend of a weeping eye.
EVERYDAY: tuple[tuple[str, str, str], ...] = (
    ("E1", "es", "Se despierta cinco veces cada noche, ¿es normal?"),
    ("E2", "es", "No come nada desde hace dos días"),
    ("E3", "es", "No quiere el biberón, ¿qué hago?"),
    ("E4", "es", "Ha vomitado dos veces esta mañana"),
    ("E5", "es", "Suda mucho cuando duerme"),
    ("E6", "es", "Ronca mucho por la noche"),
    ("E7", "es", "Respira con mucho ruido pero no tiene fiebre"),
    ("E8", "es", "Le están saliendo los dientes y está muy molesto"),
    ("E9", "es", "Tiene muchos gases y se retuerce"),
    ("E10", "es", "Llora mucho por las tardes"),
    ("E11", "fr", "Il se réveille toutes les heures la nuit"),
    ("E12", "en", "He won't eat anything since yesterday"),
)

#: A bump on the head (the battery with the real model, 2026-11-11): «se ha caido de
#: la cama y se ha dado en la cabeza» found one fragment on preventing falls and not
#: SEUP's sheet for parents, which only came when she wrote «chichón». The head
#: entries of the lexicon (golpe_cabeza, caida) expect that sheet in the cards.
SEUP_HEAD_SHEET = "Traumatismo craneal, información para padres"
HEAD_BUMP: tuple[tuple[str, str, str], ...] = (
    ("H1", "es", "se ha caido de la cama y se ha dado en la cabeza"),
    ("H2", "es", "Se ha caído de la cama y se ha dado un golpe"),
    ("H3", "es", "se ha dado en la cabeza con la mesa"),
    ("H4", "fr", "Il est tombé du lit et s'est cogné la tête"),
    ("H5", "en", "He fell off the bed and hit his head"),
)

#: Seconds between probes, so a run of ~110 probes stays under Mistral's rate.
PAUSE_SECONDS = 2.0


@dataclass
class Probe:
    id: str
    group: str  # "prod" | "lay" | "everyday" | "head" | "A" | "B"
    locale: str
    question: str
    age_months: int | None
    expect_source: str | None = None


@dataclass
class ModeResult:
    kind: str
    #: Stopped by the guard (red flag, or a child of 3 or more): nothing searched.
    guarded: bool = False
    terms: list[str] = field(default_factory=list)
    #: (text searched, best uncut distance, its title), one per embedded text.
    nearest: list[tuple[str, float | None, str | None]] = field(default_factory=list)
    #: (title, distance) of what passed the production cut-offs.
    cards: list[tuple[str, float]] = field(default_factory=list)

    @property
    def best(self) -> float | None:
        found = [d for _, d, _ in self.nearest if d is not None]
        return min(found) if found else None

    @property
    def under_cut(self) -> bool:
        return bool(self.cards)


def probes() -> list[Probe]:
    out = [Probe(i, "prod", loc, q, AGE_MONTHS) for i, loc, q in PROD_MISSES]
    out += [Probe(i, "lay", loc, q, AGE_MONTHS) for i, loc, q in COLLOQUIAL]
    out += [Probe(i, "everyday", loc, q, AGE_MONTHS) for i, loc, q in EVERYDAY]
    out += [Probe(i, "head", loc, q, AGE_MONTHS, SEUP_HEAD_SHEET) for i, loc, q in HEAD_BUMP]
    for group in ("A", "B"):
        out += [
            Probe(q.id, group, q.locale, q.question, q.age_months, q.expect_source)
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


async def run_probe(probe: Probe, *, on: bool, translate: bool, cache: dict) -> ModeResult:
    settings.lay_query_expansion = on
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
            cache[key] = await corpus_query(text, locale, provider=settings.demo_llm_provider or None)
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
        },
        deps,
    )
    result = ModeResult(kind=out["kind"])
    if out["kind"] == "red_flag" or out.get("out_of_scope"):
        result.guarded = True
        return result
    if embedded:
        result.terms = list(lay_terms.clinical_terms(embedded[0][0])) if on else []
    for searched, vector in embedded:
        distance, title = await _nearest(vector)
        result.nearest.append((searched, distance, title))
    result.cards = [(m.source_title, round(m.distance, 4)) for m in out.get("evidence") or []]
    return result


def expected_hit(probe: Probe, result: ModeResult) -> bool | None:
    if not probe.expect_source:
        return None
    return source_matches(probe.expect_source, " ".join(t.lower() for t, _ in result.cards))


def summarise(rows: list[tuple[Probe, ModeResult, ModeResult]]) -> dict:
    """Counts per mode; `new_b_under_cut` is what decides the exit status."""
    summary: dict = {"off": {}, "on": {}}
    for mode, pick in (("off", 1), ("on", 2)):
        by_group: dict[str, dict[str, int]] = {}
        for row in rows:
            probe, result = row[0], row[pick]
            g = by_group.setdefault(probe.group, {"probes": 0, "under_cut": 0, "expected": 0})
            g["probes"] += 1
            g["under_cut"] += int(result.under_cut)
            g["expected"] += int(bool(expected_hit(probe, result)))
        summary[mode] = by_group
    summary["new_b_under_cut"] = [
        p.id for p, off, on in rows if p.group == "B" and on.under_cut and not off.under_cut
    ]
    return summary


def _fmt(d: float | None) -> str:
    return "  -   " if d is None else f"{d:.4f}"


def print_row(probe: Probe, off: ModeResult, on: ModeResult) -> None:
    print(f"\n[{probe.id}] ({probe.group}, {probe.locale}) {probe.question}")
    for name, res in (("off", off), ("on ", on)):
        if res.guarded:
            print(f"  {name} guard: {res.kind}, no search")
            continue
        hit = expected_hit(probe, res)
        mark = "" if hit is None else (" expected:yes" if hit else " expected:NO")
        print(f"  {name} best {_fmt(res.best)}  kind {res.kind}{mark}")
        for searched, distance, title in res.nearest:
            shown = searched.replace("\n", " | ")
            print(f"       nearest {_fmt(distance)} {title!s:.60}  <- {shown:.80}")
        for title, distance in res.cards:
            print(f"       card    {distance:.4f} {title:.70}")
        if res.terms:
            print(f"       terms   {', '.join(res.terms)}")


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def main_async(args) -> int:
    cache: dict = {}
    rows: list[tuple[Probe, ModeResult, ModeResult]] = []
    original = settings.lay_query_expansion
    try:
        for n, probe in enumerate(probes()):
            if n:
                await _pause(PAUSE_SECONDS)
            off = await run_probe(probe, on=False, translate=not args.no_translate, cache=cache)
            on = await run_probe(probe, on=True, translate=not args.no_translate, cache=cache)
            rows.append((probe, off, on))
            print_row(probe, off, on)
    finally:
        settings.lay_query_expansion = original
    summary = summarise(rows)
    print("\n== summary (cut-off %.2f, margin %.2f)" % (
        settings.evidence_max_distance, settings.evidence_relative_margin))
    for mode in ("off", "on"):
        for group, g in summary[mode].items():
            print(f"  {mode:3} {group:4} under the cut {g['under_cut']:2}/{g['probes']:<2}"
                  f"  expected source {g['expected']}")
    print(f"  group B newly under the cut with the setting on: {summary['new_b_under_cut'] or 'none'}")
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
