"""Run golden questions against the production corpus before they gate a deploy.

    cd /app        # inside the production API container, docs/GOLDEN_GATE_DESPLIEGUE.md
    python scripts/preview_golden_candidates.py                  # clinical/golden.CANDIDATES
    python scripts/preview_golden_candidates.py --ids A16,A19    # any question, by id
    python scripts/preview_golden_candidates.py --questions /tmp/candidates.json \\
        --record /tmp/candidate_vectors.json --json /tmp/preview.json
    python scripts/preview_golden_candidates.py --export /tmp/candidates.json  # no db, no key

Why. Since 2026-11-06 every deploy runs groups A and B of the golden set on
the server and stops when one misses (docs/GOLDEN_GATE_DESPLIEGUE.md). Its first
report showed most of the corpus unwatched, and the questions written for those
blind spots (clinical/golden.CANDIDATES) cannot go straight into the gate: one
that misses in production would stop the next release. This script runs them
first, the way the gate's retrieval sees them, and only the ones it passes are
promoted into GOLDEN_SET.

For each question it prints:

  * whether the guard stopped it, a red flag or a child of 3 or more
    (clinical/age_scope). For group A that is a failure, the referral would
    answer it and retrieval would never run; for group B it is a refusal;
  * the cards under the production cut-offs, at most four and one per source,
    with their distances. The cut-offs are the container's own settings
    (evidence_max_distance, evidence_relative_margin) and so is the lay
    lexicon (lay_query_expansion): nothing is set here;
  * the four nearest sources with no cut-off at all, to diagnose a miss;
  * group A: whether `expect_source` is in the cards, and the gate's citation
    checks (`golden.citation_defects`). Group B: whether anything fell under
    the cut, which the gate would leave to the model to refuse.

What runs is the agent graph's own guard and retrieve nodes, the ones every
answer goes through, with the router a fixed stub and the answer a constant
string: no answer is ever generated. The paid calls are the embeddings
(embed_with_retry, which backs off on a 429) and, for a French or English
question, one translation into the corpus's Spanish (agent/corpus_query.py,
with the provider production translates with), as the gate does. The script
waits PAUSE_SECONDS between questions.

Read only. Every database session it opens runs SET TRANSACTION READ ONLY
before its first query, so a write would fail rather than happen. No spending
gate is called.

--record FILE writes the vectors in the shape of
tests/fixtures/golden_query_embeddings.json: the question's own vector and, for
French or English, the Spanish text the corpus is searched with and its
vector. `python -m tests.record_golden_embeddings --merge FILE` adds them to
the fixture, so a promoted question runs offline exactly as it was measured.
A guarded question is embedded for the recording only.

--questions FILE reads questions exported with --export, so the script can run
in a container whose clinical/golden.py predates the candidates.

--no-model (2026-11-06, Santiago's rule that tests never spend the mothers'
Anthropic budget; the candidate evaluation of golden_gate.sh runs it): no
model call at all, only embeddings. A French or English question is searched
with the translation recorded in tests/fixtures/golden_query_embeddings.json
(made by the production model when its vectors were recorded) or, when there
is none, as she wrote it, and the verdict says "sin traducir": production
would have translated it, so such a verdict is pessimistic for that question.

Exit status: 0 when every group A question found its source with clean cards
and no group B question fell under the cut; 1 when one did not; 2 when the
run could not measure (no embedding key, provider down), as golden_gate.sh
tells "failed" from "did not run".
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import text as sql

from adelia.agent.corpus_query import corpus_query, needs_translation
from adelia.agent.graph import GraphDeps, GraphUnavailable, run_graph
from adelia.agent.route import RouteDecision
from adelia.clinical import golden
from adelia.clinical.golden import (
    GOLDEN_SET,
    TOP_K,
    GoldenQuestion,
    citation_defects,
    source_matches,
)
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.enrichment.evidence_loader import embed_with_retry
from adelia.enrichment.evidence_retrieval import (
    evidence_citations_for_response,
    merge_by_best_distance,
    retrieve_evidence,
)
from adelia.enrichment.profile_service import ProfileFacts

#: Seconds between questions: the lay-lexicon run of 2026-11-06 died on a
#: Mistral 429 halfway through without a pause.
PAUSE_SECONDS = 2.0
#: Sources shown with no cut-off, per question.
NEAREST_K = 4
#: "No cut-off": cosine distance never reaches 2.
_UNCUT = 2.0
#: --no-model: never translate with a model (see the module docstring).
NO_MODEL = False
#: (text, locale) pairs searched untranslated because NO_MODEL had no recording.
_UNTRANSLATED: set[tuple[str, str]] = set()
#: Where the recorded translations live: next to this script in the repo and in
#: the golden image, or under the working directory when the script was copied.
_FIXTURES = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "golden_query_embeddings.json",
    Path("tests") / "fixtures" / "golden_query_embeddings.json",
)


@dataclass
class Verdict:
    id: str
    group: str
    locale: str
    question: str
    #: "red_flag:<code>" or "age_scope" when the guard stopped it; None otherwise.
    guard: str | None = None
    #: The texts embedded for the corpus search (her text, or its Spanish
    #: rendering, then the lexicon's widening when production has it on).
    searched: list[str] = field(default_factory=list)
    #: The citations the gate would see, `evidence_citations_for_response` dicts.
    cards: list[dict] = field(default_factory=list)
    #: (title, distance) of the nearest sources with no cut-off.
    nearest: list[tuple[str, float]] = field(default_factory=list)
    hit: bool | None = None
    defects: list[str] = field(default_factory=list)
    passed: bool = False
    #: --no-model and no recorded translation: searched as she wrote it.
    untranslated: bool = False


# --- which questions ------------------------------------------------------------


def _candidates() -> tuple[GoldenQuestion, ...]:
    # getattr: in a container whose golden.py predates them, --questions is the way in.
    return tuple(getattr(golden, "CANDIDATES", ()))


def select(ids: str | None) -> list[GoldenQuestion]:
    """The candidates, or the questions named in `ids` (gate or candidates), in that order."""
    if not ids:
        chosen = list(_candidates())
        if not chosen:
            raise SystemExit("no candidates in this release's golden.py; pass --questions")
        return chosen
    known = {q.id: q for q in (*GOLDEN_SET, *_candidates())}
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    unknown = [i for i in wanted if i not in known]
    if unknown:
        raise SystemExit(f"unknown question ids: {', '.join(unknown)}")
    return [known[i] for i in wanted]


def export(qs: list[GoldenQuestion], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([asdict(q) for q in qs], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def load(path: str | Path) -> list[GoldenQuestion]:
    """Questions from an --export file. Fields this golden.py does not know are dropped."""
    known = {f.name for f in dataclasses.fields(GoldenQuestion)}
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenQuestion(**{k: v for k, v in row.items() if k in known}) for row in rows]


# --- the verdict ------------------------------------------------------------------


def judge(
    q: GoldenQuestion, *, guard: str | None, cards: list[dict]
) -> tuple[bool, bool | None, list[str]]:
    """(passed, hit, defects), by the gate's rules (tests/test_rag_golden.py)."""
    if q.group == "A":
        if guard:
            return False, False, [
                f"el guard la para ({guard}): una A nunca llega a la recuperación"
            ]
        titles = " | ".join((c.get("title") or "").lower() for c in cards[:TOP_K])
        hit = source_matches(q.expect_source or "", titles)
        defects = citation_defects(q, cards)
        return hit and not defects, hit, defects
    if guard:
        return True, None, []
    return not cards, None, []


async def _read_only(session) -> None:
    await session.execute(sql("SET TRANSACTION READ ONLY"))


async def _nearest(vectors: list[list[float]]) -> list[tuple[str, float]]:
    """The nearest sources with no cut-off, over every text searched (diagnostic only)."""
    found = []
    for vector in vectors:
        async with AsyncSessionLocal() as session:
            await _read_only(session)
            found.append(await retrieve_evidence(
                session, query_embedding=vector, specialties=["pediatrics"], top_k=NEAREST_K,
                max_distance=_UNCUT, relative_margin=None,
            ))
    merged = merge_by_best_distance(found, top_k=NEAREST_K, relative_margin=None)
    return [(m.source_title, round(m.distance, 4)) for m in merged]


async def _translate(text: str, locale: str, cache: dict) -> str:
    key = (text, locale)
    if key not in cache:
        if NO_MODEL and needs_translation(locale):
            _UNTRANSLATED.add(key)
            cache[key] = text
        else:
            cache[key] = await corpus_query(text, locale)
    return cache[key]


def recorded_translations(qs: list[GoldenQuestion]) -> dict[tuple[str, str], str]:
    """The fixture's Spanish text per French or English question, keyed as the cache.

    Only for a question whose recorded wording is the current one: a question
    rewritten since its recording is searched as written, not as it used to be."""
    for path in _FIXTURES:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            break
    else:
        return {}
    texts, recorded = data.get("corpus_queries") or {}, data.get("questions") or {}
    return {
        (q.question, q.locale): texts[q.id]
        for q in qs
        if needs_translation(q.locale) and q.id in texts and recorded.get(q.id) == q.question
    }


async def _vector(text: str, embedded: dict[str, list[float]]) -> list[float]:
    if text not in embedded:
        embedded[text] = (await embed_with_retry([text]))[0]
    return embedded[text]


async def _record(
    q: GoldenQuestion, recording: dict, embedded: dict[str, list[float]], cache: dict
) -> None:
    """The fixture's entries for `q`, from the vectors already paid for when possible."""
    recording["questions"][q.id] = q.question
    recording["embeddings"][q.id] = await _vector(q.question, embedded)
    if needs_translation(q.locale):
        text = await _translate(q.question, q.locale, cache)
        if text != q.question:  # a translation that fell back is not recorded, as in the recorder
            recording["corpus_queries"][q.id] = text
            recording["corpus_embeddings"][q.id] = await _vector(text, embedded)


def empty_recording() -> dict:
    return {
        "model": settings.mistral_embed_model, "questions": {}, "embeddings": {},
        "corpus_queries": {}, "corpus_embeddings": {},
    }


async def preview(q: GoldenQuestion, *, cache: dict, recording: dict | None) -> Verdict:
    """One question through the graph's guard and retrieve nodes, read only."""
    embedded: dict[str, list[float]] = {}
    searched: list[str] = []

    async def _route(message, **kwargs):
        return RouteDecision(intent="question", confidence=1.0, via="rule")

    async def _embed(texts):
        vectors = await embed_with_retry(list(texts))
        for t, v in zip(texts, vectors, strict=True):
            embedded[t] = v
        searched.extend(texts)
        return vectors

    async def _retrieve(session, **kwargs):
        await _read_only(session)
        return await retrieve_evidence(session, **kwargs)

    async def _generate(system_prompt, user_message):
        return "Respuesta de previsualización [ev_1]."

    async def _corpus_text(text, locale):
        return await _translate(text, locale, cache)

    deps = GraphDeps(
        route=_route, embed=_embed, retrieve_evidence=_retrieve, generate=_generate,
        corpus_text=_corpus_text,
    )
    out = await run_graph(
        {
            "surface": "golden_preview", "locale": q.locale, "message": q.question,
            "account": False, "facts": ProfileFacts(None, None, None, None, q.age_months),
        },
        deps,
    )
    verdict = Verdict(q.id, q.group, q.locale, q.question)
    key = (q.question, q.locale)
    verdict.untranslated = key in _UNTRANSLATED and cache.get(key) == q.question
    if out.get("kind") == "red_flag":
        flag = out.get("flag")
        verdict.guard = f"red_flag:{getattr(flag, 'code', '?')}"
    elif out.get("out_of_scope"):
        verdict.guard = "age_scope"
    else:
        verdict.searched = list(searched)
        verdict.cards = evidence_citations_for_response(list(out.get("evidence") or []))
        verdict.nearest = await _nearest([embedded[t] for t in searched])
    verdict.passed, verdict.hit, verdict.defects = judge(
        q, guard=verdict.guard, cards=verdict.cards
    )
    if recording is not None:
        await _record(q, recording, embedded, cache)
    return verdict


# --- the run ------------------------------------------------------------------------


def _fmt_verdict(q: GoldenQuestion, v: Verdict) -> str:
    lines = [f"\n[{q.id}] ({q.group}, {q.locale}, {q.age_months} meses) {q.question}"]
    if q.group == "A":
        lines.append(f"  espera: {q.expect_source}")
    if v.guard:
        lines.append(f"  guard: {v.guard}, sin búsqueda")
    if v.untranslated:
        lines.append("  sin traducir (sin modelo y sin traducción grabada; producción la traduciría)")
    for searched in v.searched:
        lines.append(f"  busca:   {searched.replace(chr(10), ' | '):.110}")
    for c in v.cards:
        lines.append(f"  tarjeta {c['distance']:.4f} {c['title']:.90}")
    if not v.guard and not v.cards:
        lines.append("  tarjeta (ninguna bajo el corte)")
    for title, distance in v.nearest:
        lines.append(f"  cercana {distance:.4f} {title:.90}")
    for d in v.defects:
        lines.append(f"  defecto: {d}")
    verdict = "PASA" if v.passed else "FALLA"
    if q.group == "A":
        why = "fuente en las tarjetas" if v.hit else "fuente fuera de las tarjetas"
    else:
        why = "negada por el guard" if v.guard else (
            "nada bajo el corte" if not v.cards else "hay tarjetas bajo el corte")
    lines.append(f"  => {verdict} ({why})")
    return "\n".join(lines)


def _coverage_line(qs: list[GoldenQuestion]) -> str | None:
    try:
        before = golden.corpus_blind_spots()
        after = golden.corpus_blind_spots(also=tuple(q for q in qs if q.group == "A"))
    except TypeError:  # an older golden.py without `also`
        return None
    if not before or not after:
        return None
    b = sum(t["untouched"] for t in before)
    a = sum(t["untouched"] for t in after)
    total = sum(t["sources"] for t in after)
    return f"fuentes pediátricas sin pregunta A: {b} de {total} hoy; {a} si entran todas estas"


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _dispose() -> None:
    from adelia.db import engine

    await engine.dispose()


async def main_async(args) -> int:
    qs = load(args.questions) if args.questions else select(args.ids)
    if args.export:
        export(qs, args.export)
        print(f"{len(qs)} preguntas exportadas a {args.export}")
        return 0
    global NO_MODEL
    NO_MODEL = bool(getattr(args, "no_model", False))
    print(
        f"golden preview: {len(qs)} preguntas; corte {settings.evidence_max_distance:.2f}, "
        f"margen {settings.evidence_relative_margin:.2f}, "
        f"léxico de madre {'encendido' if settings.lay_query_expansion else 'apagado'}"
        + ("; sin modelo (solo embeddings, traducciones grabadas)" if NO_MODEL else "")
    )
    coverage = _coverage_line(qs)
    if coverage:
        print(f"  {coverage}")
    cache: dict = recorded_translations(qs) if NO_MODEL else {}
    recording = empty_recording() if args.record else None
    verdicts: list[Verdict] = []
    try:
        for n, q in enumerate(qs):
            if n:
                await _pause(PAUSE_SECONDS)
            try:
                v = await preview(q, cache=cache, recording=recording)
            except GraphUnavailable as exc:
                # No key, or the provider down: nothing was measured.
                print(f"\n[{q.id}] NO MEDIDA: {exc}. Nada se ha medido como pasa o falla.")
                return 2
            verdicts.append(v)
            print(_fmt_verdict(q, v))
    finally:
        await _dispose()
    failed = [v.id for v in verdicts if not v.passed]
    print(f"\n== {len(verdicts) - len(failed)} de {len(verdicts)} pasan; "
          f"fallan: {', '.join(failed) or 'ninguna'}")
    if args.record:
        Path(args.record).write_text(json.dumps(recording, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
        print(f"vectores de {len(recording['questions'])} preguntas en {args.record}")
    if args.json:
        Path(args.json).write_text(
            json.dumps([asdict(v) for v in verdicts], ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ids", help="comma-separated ids from GOLDEN_SET or CANDIDATES")
    parser.add_argument("--questions", help="read the questions from an --export file")
    parser.add_argument("--export", help="write the selected questions to this file and stop")
    parser.add_argument("--record", help="write the vectors embedded, in the fixture's shape")
    parser.add_argument("--json", help="also write every verdict to this file")
    parser.add_argument(
        "--no-model", action="store_true",
        help="no model call at all: recorded translations, or the question as written",
    )
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
