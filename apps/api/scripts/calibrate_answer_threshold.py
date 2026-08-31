"""Measure where the evidence cut-off belongs, instead of guessing it.

`settings.evidence_max_distance` decides whether AdelIA answers a clinical
question at all. Until 2026-08-31 it was a literal, 0.45, chosen by intuition,
and it sat above the corpus's own diameter (largest cosine distance between
any two corpus fragments: 0.3386), so it never rejected anything. This script
is how that number gets set from data and how it gets re-checked whenever the
corpus grows.

Two modes, both printing the same tables:

  --mode questions   (needs MISTRAL_API_KEY)
      Embeds the 40 control questions below, 20 inside the corpus and 20
      outside it, and measures the distance of the best-matching fragment for
      each. This is the real measurement: the queries are what a parent
      actually types.

  --mode corpus      (no API key, no network)
      Uses the corpus fragments themselves as queries. In-corpus population:
      every pediatric fragment against the pediatric fragments of *other*
      sources. Out-of-corpus population: every adult, off-topic fragment
      (atrial fibrillation, hypertension, cholesterol, breast and colorectal
      cancer screening, endometriosis, adult diabetes, SBAR, all of them
      already in `evidence_seed.json`) against the pediatric fragments. A
      weaker proxy than real questions, since a fragment is denser than a
      question, but it needs nothing but the database and it is what produced
      the numbers currently in config.py.

BOTH modes search THE INDEX PRODUCTION SEARCHES, and nothing wider. That is
`specialties ?| array['pediatrics']`, the filter chat_orchestrator and
briefing_orchestrator pass to retrieve_evidence. It has to be said out loud
because the first version of this script measured the OUT population against
the pediatric fragments while the code searched all 258 chunks, the 14 adult
probes included: the table said 0/14 leaked at 0.20 while the running code
leaked 12/14 (minimum distance 0.1324), because a probe's nearest neighbour
was another adult source sitting in the same table. A measurement that does
not interrogate the same population as the code is not a measurement of the
code. If the pediatrics filter is ever removed, the queries below must widen
with it.

Usage on the dev box (the corpus is loaded there):

    ssh santiago@192.168.1.150 'cd /opt/adelia-dev/apps/api && \
      POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_USER=adelia \
      POSTGRES_PASSWORD=adelia_dev POSTGRES_DB=adelia AUTH_SECRET=ci-only-secret \
      uv run python scripts/calibrate_answer_threshold.py --mode corpus'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from sqlalchemy import text

from adelia.db import AsyncSessionLocal


# --------------------------------------------------------------------------
# The 40 control questions. Five covered topics, five uncovered ones.
# --------------------------------------------------------------------------

IN_CORPUS_QUESTIONS: list[str] = [
    # reflujo
    "¿Es normal que mi bebé regurgite después de cada toma?",
    "¿Cuándo deja de tener reflujo un bebé?",
    "¿Qué señales de alarma indican que no es un reflujo simple?",
    "¿Sirve espesar la leche para el reflujo del lactante?",
    "¿Hay que dar medicación para el reflujo a un bebé de 3 meses?",
    # alimentación complementaria 6-24 meses
    "¿A qué edad empiezo con la alimentación complementaria?",
    "¿Puedo darle huevo entero a mi bebé de 8 meses?",
    "Mi hijo de 18 meses no quiere comer verdura, ¿qué hago?",
    "¿Cuánta cantidad debe comer un niño de un año en cada comida?",
    "¿Es mejor baby led weaning o purés?",
    # guardería y adaptación
    "¿Cuánto dura el periodo de adaptación a la guardería?",
    "¿Por qué mi hijo se pone malo todo el rato desde que va a la guardería?",
    "¿Es malo para el apego llevar al bebé a la guardería al año?",
    "¿Cómo hago la incorporación progresiva a la escuela infantil?",
    "Mi bebé llora al dejarlo en la guardería, ¿es normal a los 12 meses?",
    # lactancia
    "¿Hasta cuándo se recomienda la lactancia materna?",
    "¿La lactancia prolongada tiene beneficios después del año?",
    "¿Puedo seguir dando pecho mientras empieza con sólidos?",
    # hierro
    "¿Mi bebé necesita suplemento de hierro si toma solo pecho?",
    "¿Cuánta leche de vaca puede tomar un niño de 15 meses sin quedarse bajo de hierro?",
]

OUT_OF_CORPUS_QUESTIONS: list[str] = [
    # fibrilación auricular / cardiología del adulto
    "¿Qué anticoagulante se usa en fibrilación auricular no valvular?",
    "¿Cómo se calcula el CHA2DS2-VASc?",
    "¿Cuándo se hace cardioversión en una fibrilación auricular?",
    "Tengo palpitaciones y el ECG dice fibrilación auricular, ¿qué significa?",
    # hipotecas / finanzas
    "¿Me conviene una hipoteca fija o variable en 2026?",
    "¿Cuánto me pueden prestar para una hipoteca con 40.000 € de sueldo?",
    "¿Qué es el euríbor y cómo afecta a mi cuota?",
    "¿Puedo amortizar hipoteca anticipadamente sin penalización?",
    # recetas de cocina
    "¿Cómo hago una paella valenciana para ocho personas?",
    "¿Cuánto tiempo se hornea un bizcocho de yogur?",
    "Dame una receta de lentejas con chorizo.",
    "¿Cómo se hace una masa madre para pan?",
    # dermatitis del adulto
    "¿Qué crema uso para la dermatitis seborreica en la cara de un adulto?",
    "¿La psoriasis en placas se cura con corticoides tópicos?",
    "Tengo eccema en las manos por el trabajo, ¿qué hago?",
    "¿El dupilumab está indicado en dermatitis atópica grave del adulto?",
    # oncología
    "¿Cada cuánto hay que hacerse una mamografía a los 50 años?",
    "¿Qué es el cribado de cáncer colorrectal con sangre oculta en heces?",
    "¿Cuáles son los efectos secundarios de la quimioterapia adyuvante en cáncer de mama?",
    "¿Qué significa un PSA elevado en un hombre de 60 años?",
]


# --------------------------------------------------------------------------
# Corpus tagging (mode "corpus"): which sources are the baby corpus and which
# are the adult, off-topic ones that ride along in evidence_seed.json.
# --------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "adelia" / "enrichment" / "data"
BABY_FILES = (
    "evidence_pediatric_reflux.json",
    "evidence_alimentacion_bebes.json",
    "evidence_guarderia_adaptacion.json",
)
SEED_FILE = "evidence_seed.json"
# Seed entries that ARE about babies, so they belong to neither population.
SEED_PEDIATRIC_PREFIXES = ("GINA asthma", "Pediatric immunization schedule")


def _titles(filename: str) -> list[str]:
    data = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    return [s["title"] for s in sources]


def _populations() -> tuple[list[str], list[str]]:
    baby = [t for f in BABY_FILES for t in _titles(f)]
    off_topic = [
        t
        for t in _titles(SEED_FILE)
        if not t.startswith(SEED_PEDIATRIC_PREFIXES)
    ]
    return baby, off_topic


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

CUTS = [0.14, 0.16, 0.18, 0.19, 0.20, 0.22, 0.24, 0.28, 0.32, 0.36, 0.40, 0.45]


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def _describe(label: str, values: list[float]) -> None:
    if not values:
        print(f"{label:38s}  (empty)")
        return
    print(
        f"{label:38s} n={len(values):4d}  min={min(values):.4f}  "
        f"p50={statistics.median(values):.4f}  p95={_pct(values, 0.95):.4f}  "
        f"max={max(values):.4f}"
    )


def _report(inside: list[float], outside: list[float]) -> None:
    print()
    _describe("IN  (best fragment, in corpus)", inside)
    _describe("OUT (best fragment, off corpus)", outside)
    print()
    if inside and outside:
        lo, hi = max(inside), min(outside)
        if lo < hi:
            print(
                f"Valley: [{lo:.4f}, {hi:.4f}]  width {hi - lo:.4f}  "
                f"midpoint {(lo + hi) / 2:.4f}"
            )
        else:
            print(
                f"NO VALLEY: the two populations overlap "
                f"(worst in-corpus {lo:.4f} >= closest off-corpus {hi:.4f}). "
                "A distance cut-off alone cannot separate them; add a reranker "
                "or a cheap yes/no judge."
            )
    print()
    print(f"{'cut':>7}  {'in kept':>10}  {'off leaked':>11}")
    for cut in CUTS:
        kept = sum(1 for d in inside if d <= cut)
        leaked = sum(1 for d in outside if d <= cut)
        print(f"{cut:7.3f}  {kept:5d}/{len(inside):<4d}  {leaked:5d}/{len(outside):<5d}")


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------


# The pediatric index, exactly as retrieve_evidence scopes it on the
# answering path (adelia/enrichment/evidence_retrieval.py).
PEDIATRIC_ONLY = "es.specialties ?| array['pediatrics']"


async def _best_distance_for_embedding(session, embedding: list[float]) -> float | None:
    row = (
        await session.execute(
            text(
                "SELECT min(ec.embedding <=> :emb) AS d "
                "FROM evidence_chunks ec "
                "JOIN evidence_sources es ON es.id = ec.source_id "
                f"WHERE ec.embedding IS NOT NULL AND {PEDIATRIC_ONLY}"
            ),
            {"emb": str(embedding)},
        )
    ).first()
    return None if row is None or row.d is None else float(row.d)


async def run_questions() -> None:
    from adelia.workers.embed import embed_texts

    questions = IN_CORPUS_QUESTIONS + OUT_OF_CORPUS_QUESTIONS
    embeddings = await embed_texts(questions)
    if len(embeddings) != len(questions):
        raise SystemExit(
            f"embed_texts returned {len(embeddings)} vectors for {len(questions)} questions"
        )
    inside: list[float] = []
    outside: list[float] = []
    async with AsyncSessionLocal() as session:
        for question, embedding in zip(questions, embeddings, strict=True):
            distance = await _best_distance_for_embedding(session, embedding)
            if distance is None:
                raise SystemExit("no evidence chunks with embeddings in this database")
            bucket = inside if question in IN_CORPUS_QUESTIONS else outside
            bucket.append(distance)
            tag = "IN " if bucket is inside else "OUT"
            print(f"{tag} {distance:.4f}  {question}")
    _report(inside, outside)


async def _count(sql: str) -> int:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text(sql))).first()
    return 0 if row is None else int(row.n)


async def run_corpus() -> None:
    baby_titles, off_topic_titles = _populations()
    async with AsyncSessionLocal() as session:
        inside_rows = (
            await session.execute(
                text(
                    """
                    SELECT min(a.embedding <=> b.embedding) AS d
                    FROM evidence_chunks a
                    JOIN evidence_sources sa ON sa.id = a.source_id
                    JOIN evidence_chunks b ON b.source_id <> a.source_id
                    JOIN evidence_sources sb ON sb.id = b.source_id
                    WHERE sa.title = ANY(:baby)
                      AND sb.specialties ?| array['pediatrics']
                      AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
                    GROUP BY a.id
                    """
                ),
                {"baby": baby_titles},
            )
        ).all()
        outside_rows = (
            await session.execute(
                text(
                    """
                    SELECT min(a.embedding <=> b.embedding) AS d
                    FROM evidence_chunks a
                    JOIN evidence_sources sa ON sa.id = a.source_id
                    JOIN evidence_chunks b ON true
                    JOIN evidence_sources sb ON sb.id = b.source_id
                    WHERE sa.title = ANY(:off)
                      AND sb.specialties ?| array['pediatrics']
                      AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
                    GROUP BY a.id
                    """
                ),
                {"off": off_topic_titles, "baby": baby_titles},
            )
        ).all()
    pediatric_sources = (
        await _count("SELECT count(*) AS n FROM evidence_sources WHERE " + PEDIATRIC_ONLY.replace("es.", ""))
    )
    print(
        f"sources: {len(baby_titles)} baby, {len(off_topic_titles)} adult off-topic; "
        f"searched index: {pediatric_sources} pediatric-tagged sources"
    )
    _report([float(r.d) for r in inside_rows], [float(r.d) for r in outside_rows])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("questions", "corpus"), default="corpus")
    args = parser.parse_args()
    asyncio.run(run_questions() if args.mode == "questions" else run_corpus())


if __name__ == "__main__":
    main()
