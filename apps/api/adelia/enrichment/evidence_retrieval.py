"""Dual-RAG evidence retrieval — clinical guidelines + papers + protocols.

Sister to the patient RAG (Modo A chat retrieval). Combined results in
chat_orchestrator / briefing_orchestrator provide:
- Patient context (from `chunks` table — what's true about THIS user)
- Evidence context (from `evidence_chunks` table — what's true clinically)

LLM synthesizes both with separate citation namespaces:
- 🟡 patient citation (linkable to /dashboard/documents/{id})
- 📘 evidence citation (linkable to source URL)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.config import settings
from adelia.services.fusion import rrf
from adelia.services.lexical import HYBRID_CANDIDATE_POOL, LexicalPlan, plan_lexical
from adelia.services.reranker import NullReranker, Reranker, rerank_items

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceMatch:
    chunk_id: UUID
    source_id: UUID
    source_title: str
    organization: str | None
    publication_year: int | None
    url: str | None
    content: str
    chunk_index: int
    distance: float  # cosine distance, lower = more relevant
    # 'evidence' or 'experience' (evidence_sources.tier, migration 0022). The
    # answer surfaces label and place a citation by it, so it travels with
    # the match rather than being inferred from where the match came from.
    tier: str = "evidence"


#: The two tiers evidence_sources holds. Retrieval reads one at a time.
EVIDENCE_TIER = "evidence"
EXPERIENCE_TIER = "experience"


#: Most rows the vector query is ever asked for when it has to look past
#: repeated sources. The corpus has up to 8 fragments per source (127 sources,
#: 301 fragments), so finding 4 distinct sources can mean reading
#: (4 - 1) * 8 + 1 = 25 rows in the worst case; 64 covers that with room, and
#: keeps a corpus that grows a 20-fragment source from turning one question
#: into a table scan.
EVIDENCE_CANDIDATE_CAP = 64


def within_relative_margin(
    matches: Sequence[EvidenceMatch], margin: float | None
) -> list[EvidenceMatch]:
    """Keep the matches no farther than `margin` behind the best one.

    The absolute cut-off (settings.evidence_max_distance) asks "is this close
    to the corpus?". This asks "is this close to what THIS question found?".
    On 2026-10-14 the public demo answered a question about sudden infant
    death with three sleep fragments and a reflux guideline as the fourth
    "evidence". It was inside 0.19, so the absolute cut-off let it through, and
    no fixed number can tell whether the fragment is about the question. The
    measurement kept only the title, so it is not known whether that card was
    the sleeping-position paragraph of NICE NG1 (relevant) or one of its
    feeding paragraphs (not); the margin is aimed at the second case and cannot
    tell them apart except through distance. Anchored to the query's own best
    distance, a question with one good source keeps one fragment.

    The best distance is the minimum over `matches`, not the first element, so
    the result does not depend on the order the caller holds them in; the order
    is preserved. `margin=None` disables the criterion. A match exactly
    `margin` behind the best is kept (the comparison is `<=`).
    """
    if margin is None or not matches:
        return list(matches)
    ceiling = min(m.distance for m in matches) + margin
    return [m for m in matches if m.distance <= ceiling]


def dedupe_by_source(matches: Sequence[EvidenceMatch], top_k: int) -> list[EvidenceMatch]:
    """The first match of each source, in the given order, up to `top_k`.

    "FUENTES CITADAS" shows one card per returned match. Measured on the public
    demo on 2026-10-14, one question about safe sleep showed the same AAP 2022
    title in three of its four cards, reflux showed NICE 2019 twice and the
    nursery question showed the AEPap guide twice. A mother reads four cards as
    four independent sources agreeing, and it was two, so the cards are the
    product's only credibility signal and were overstating it.

    `matches` must already be in the order that decides who wins (ascending
    distance, or the fused/reranked order of the hybrid path): the first
    fragment of a source is the one kept, and it is the one the model reads and
    the one the parent sees, because both are rendered from this same list
    (format_evidence_for_prompt and evidence_citations_for_response). Never
    swap in another fragment of the source afterwards: the quoted text is the
    guarantee.

    The key is `source_id`, never the title. Different sources share a title
    (the corpus has repeated ones), and collapsing those would drop a real,
    independent source. When fewer than `top_k` distinct sources exist this
    returns fewer than `top_k`, on purpose: four cards from two sources say
    more than the evidence does, two honest cards do not.
    """
    if top_k <= 0:
        return []
    seen: set[UUID] = set()
    kept: list[EvidenceMatch] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        kept.append(match)
        if len(kept) == top_k:
            break
    return kept


async def retrieve_evidence(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    specialties: Iterable[str] | None = None,
    top_k: int = 5,
    max_distance: float | None = None,
    relative_margin: float | None = None,
    query_text: str | None = None,
    locale: str | None = None,
    reranker: Reranker | None = None,
    tier: str = EVIDENCE_TIER,
) -> list[EvidenceMatch]:
    """Retrieve up to top-K evidence chunks, one per source, ranked by cosine distance.

    Args:
        query_embedding: 1024-dim vector from mistral-embed
        specialties: optional filter — only evidence tagged with at least one
            of these specialties is returned (e.g. ['pediatrics']). The
            answering path passes ['pediatrics'] so a question about a baby
            can never be answered with the adult sources the same table
            holds (atrial fibrillation, cancer screening, SBAR).
        top_k: max results. At most `top_k`, and FEWER when fewer distinct
            sources are good enough: see "One citation per source" below.
        max_distance: cosine distance cut-off. Defaults to
            settings.evidence_max_distance, calibrated against the real corpus
            (see apps/api/docs/CALIBRACION_UMBRAL_EVIDENCIA.md). The previous
            default, 0.45, was above the corpus's own diameter (0.3386), so it
            rejected nothing and every question came back "evidence-backed".
        relative_margin: how far behind the query's own best fragment a
            fragment may be and still be returned, see within_relative_margin.
            A second admission control on top of `max_distance`, never looser
            than it. None, the default, applies no relative criterion. The
            answering call sites (chat, demo, briefings) pass
            settings.evidence_relative_margin, the way they already pass
            `max_distance`; how that value was chosen is written next to it in
            config.py. The policy lives with the callers on purpose: a stored
            vector used as the query matches itself at distance 0.0, which
            would anchor the margin at 0 and drop every other source, and the
            calibration tests do exactly that. A parent's question never lands
            on a fragment, so it never happens in production.
        query_text: the question as text, for the lexical half of hybrid
            retrieval. Ignored (and may be omitted, as briefings and the demo
            do) unless settings.retrieval_hybrid_enabled is on.
        locale: the question's language (es/en/fr), picks the text-search
            configuration. Any other value means no lexical query.
        reranker: a services.reranker.Reranker applied to the fused pool.
            Defaults to NullReranker, the identity. Only used on the hybrid
            path, see below.
        tier: which of the two tiers the table holds to read, 'evidence' by
            default. The filter is on `evidence_sources.tier`, not on the
            specialty tag, so an experience row tagged 'pediatrics' by
            mistake still never reaches a clinical answer, and a guideline
            never shows up as "what other mothers say". Both the vector and
            the lexical statements carry it. See retrieve_experience.

    One citation per source, and no filler (measured on the public demo on
    2026-10-14). The corpus holds several fragments per source, so the top
    four rows of a question were often three or two fragments of one guideline
    and four cards showed two sources. Two defects, two fixes, both applied to
    what the vector query admitted and neither able to admit anything new:

      * `dedupe_by_source` keeps the best fragment of each `source_id` and goes
        on down the ranking until `top_k` distinct sources are found, or the
        ranking runs out. The first statement asks for `top_k` rows, exactly as
        before; only when those rows repeat a source (and more could still pass)
        is a second, wider one run (see EVIDENCE_CANDIDATE_CAP). The fragment
        returned is the one the model reads and the one the parent sees: the
        quoted text is the guarantee, so it is never swapped for another
        fragment of the same source.
      * `within_relative_margin` drops fragments too far behind the best one,
        so a question with one good source does not fill the other slots with
        the fifth-best thing in the corpus.

    Hybrid retrieval (settings.retrieval_hybrid_enabled, OFF by default). With
    the flag off, or without `query_text`, or with a locale the corpus is not
    written in, this function runs the vector query below with LIMIT top_k and
    nothing else: the same first SQL and parameters as before the flag
    existed (the dedup and the margin above are the only things applied to its
    rows, and they are not part of the flag). With it on:

      1. the vector query runs unchanged (same calibrated `max_distance`, same
         specialty filter) but returns a pool of HYBRID_CANDIDATE_POOL rows
         instead of top_k;
      2. a `tsvector` query ranks the same corpus by `ts_rank_cd`, under the
         SAME specialty filter (that filter is what keeps adult sources out of
         a question about a baby; a lexical query that skipped it would put
         them back);
      3. the two rankings are fused by Reciprocal Rank Fusion;
      4. the reranker reorders the fused pool, and the first top_k distinct
         sources are kept.

    The lexical ranking can reorder, it cannot admit. Only fragments that
    already passed `max_distance` can be returned; a chunk the full-text query
    found but the vector query did not is dropped. That is deliberate. The
    refusal in chat_orchestrator ("nothing grounded, so no generative call")
    is the audit's answer to a confident, sourceless answer about a baby, and
    it hangs on this function returning [] for an off-corpus question. A
    keyword search admits on shared vocabulary ("dosis", "bebé", "meses" are in
    nearly every pediatric chunk), which is precisely the failure the
    calibration removed, and a lexical admission criterion cannot be calibrated
    without live embeddings. So the full-text signal cross-checks and
    reorders the vector survivors, and rescuing a fragment that falls just
    outside the cut-off stays an open item for after the eval harness exists.

    Returns: sorted list, most relevant first, never two fragments of one
    source, possibly shorter than `top_k` and possibly empty.
    """
    if max_distance is None:
        max_distance = settings.evidence_max_distance
    plan = plan_lexical(query_text, locale)
    pool = max(top_k, HYBRID_CANDIDATE_POOL) if plan is not None else top_k
    # pgvector cosine distance via `<=>` operator
    # We do a join to evidence_sources to filter by specialty + return metadata
    stmt_text = """
        SELECT
            ec.id AS chunk_id,
            ec.source_id,
            es.title AS source_title,
            es.organization,
            es.publication_year,
            es.url,
            ec.content,
            ec.chunk_index,
            ec.embedding <=> :emb AS distance,
            es.tier
        FROM evidence_chunks ec
        JOIN evidence_sources es ON es.id = ec.source_id
        WHERE ec.embedding <=> :emb < :max_distance
          AND es.tier = :tier
    """
    params: dict = {"emb": str(query_embedding), "max_distance": max_distance, "tier": tier}

    # JSONB array contains-any check via the ?| operator, whose right-hand
    # side is a text[]. `array[:spec_list]` built an array OF the parameter,
    # so asyncpg was handed a list where it expected a str and raised
    # DataError: invalid input for query argument $3: ['pediatrics'] (expected
    # str, got list). Every call that passed `specialties` therefore blew up —
    # silently, because both call sites swallow the exception and return []
    # (briefing_orchestrator._retrieve_specialty_evidence never returned a
    # single fragment). Bind the list itself, typed as text[].
    spec_list = list(specialties) if specialties else None
    if spec_list:
        stmt_text += " AND es.specialties ?| :spec_list"
        params["spec_list"] = spec_list

    stmt_text += " ORDER BY distance ASC LIMIT :k"

    stmt = text(stmt_text)
    if spec_list:
        stmt = stmt.bindparams(bindparam("spec_list", type_=ARRAY(String)))

    limit = pool
    while True:
        params["k"] = limit
        result = await session.execute(stmt, params)
        rows = result.mappings().all()
        matches = [
            EvidenceMatch(
                chunk_id=r["chunk_id"],
                source_id=r["source_id"],
                source_title=r["source_title"],
                organization=r["organization"],
                publication_year=r["publication_year"],
                url=r["url"],
                content=r["content"],
                chunk_index=r["chunk_index"],
                distance=float(r["distance"]),
                tier=r.get("tier", tier),
            )
            for r in rows
        ]
        admitted = within_relative_margin(matches, relative_margin)
        # Look past repeated sources only when that can still pay off: the
        # rows so far do not hold `top_k` distinct sources, the margin has not
        # already cut the tail (rows are in ascending distance, so everything
        # after a cut is farther still), the cut-off has not run out of rows
        # (fewer rows than asked for), and the cap has not been reached.
        if (
            len({m.source_id for m in admitted}) >= top_k
            or len(admitted) < len(matches)
            or len(rows) < limit
            or limit >= EVIDENCE_CANDIDATE_CAP
        ):
            break
        limit = EVIDENCE_CANDIDATE_CAP
    matches = admitted
    if plan is None or not matches:
        # Nothing survived the cut-offs means nothing can be returned, so there
        # is no point asking the lexical index either.
        return dedupe_by_source(matches, top_k)

    lexical_ids = await lexical_evidence_ranking(
        session, plan=plan, specialties=spec_list, pool=pool, tier=tier
    )
    fused = dict(rrf([[str(m.chunk_id) for m in matches], lexical_ids]))
    # Only vector survivors are fused back in: see "reorder, cannot admit".
    # sorted() is stable, so equal fused scores keep their vector order.
    ordered = sorted(matches, key=lambda m: -fused[str(m.chunk_id)])
    ordered = await rerank_items(
        reranker or NullReranker(),
        query_text,
        ordered,
        id_of=lambda m: str(m.chunk_id),
        text_of=lambda m: m.content,
        score_of=lambda m: fused[str(m.chunk_id)],
    )
    return dedupe_by_source(ordered, top_k)


async def lexical_evidence_ranking(
    session: AsyncSession,
    *,
    plan: LexicalPlan,
    specialties: list[str] | None,
    pool: int,
    tier: str = EVIDENCE_TIER,
) -> list[str]:
    """Evidence chunk ids ranked by full-text relevance, best first (as str).

    The same corpus the vector query searches, narrowed the same way:
      * `specialties` is the identical `?|` filter, so the pediatric-only
        promise holds for this ranking too;
      * `tier` is the identical `es.tier` filter, so the two tiers stay apart
        here as well;
      * `ec.language = :language` restricts the match to rows indexed in the
        question's language, since `tsv` was built per row from that column
        (migration 0021) and only the same configuration produces the same
        stems. English rows are the vector search's to find.

    Best-effort: this is a cross-check, so a failure (the migration not applied
    yet, a malformed tsquery) is logged and returns [], and the caller falls
    back to the vector order. It runs in a SAVEPOINT so the failed statement
    does not poison the caller's transaction.
    """
    stmt_text = """
        SELECT ec.id AS chunk_id
        FROM evidence_chunks ec
        JOIN evidence_sources es ON es.id = ec.source_id
        CROSS JOIN (
            SELECT to_tsquery(CAST(:ts_config AS regconfig), :tsquery) AS q
        ) lex
        WHERE ec.language = :language AND ec.tsv @@ lex.q AND es.tier = :tier
    """
    params: dict = {
        "ts_config": plan.ts_config,
        "tsquery": plan.tsquery,
        "language": plan.language,
        "k": pool,
        "tier": tier,
    }
    if specialties:
        stmt_text += " AND es.specialties ?| :spec_list"
        params["spec_list"] = list(specialties)
    # Normalisation 1 divides the rank by 1 + log(length), a mild brake on long
    # chunks that match more terms simply by containing more words.
    stmt_text += " ORDER BY ts_rank_cd(ec.tsv, lex.q, 1) DESC, ec.id ASC LIMIT :k"

    stmt = text(stmt_text)
    if specialties:
        stmt = stmt.bindparams(bindparam("spec_list", type_=ARRAY(String)))
    try:
        async with session.begin_nested():
            result = await session.execute(stmt, params)
            return [str(row.chunk_id) for row in result]
    except Exception as exc:  # noqa: BLE001 - never let the cross-check break retrieval
        # Class name only: str(exc) carries the bound parameters, which are the
        # parent's question terms, and health questions do not belong in logs.
        logger.warning(
            "lexical evidence ranking failed, using vector order: %s", type(exc).__name__
        )
        return []


def format_evidence_for_prompt(matches: list[EvidenceMatch]) -> str:
    """Render evidence matches as a context block for LLM system prompt.

    Each match prefixed with a `[ev_N]` citation tag the LLM can reference.
    """
    if not matches:
        return ""

    lines = ["## Clinical evidence (cite as [ev_N]):"]
    for i, m in enumerate(matches, start=1):
        attribution = m.source_title
        if m.organization:
            attribution = f"{m.organization} — {attribution}"
        if m.publication_year:
            attribution = f"{attribution} ({m.publication_year})"
        lines.append(f"[ev_{i}] {attribution}")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines)


def evidence_citations_for_response(
    matches: list[EvidenceMatch], *, tag_prefix: str = "ev", tier: str | None = None
) -> list[dict]:
    """Render evidence matches as a JSON-serializable list for the API response.

    Frontend uses this to render 📘 citation badges with click-through URLs.
    `tier` travels on every citation (schemas.EvidenceCitation defaults it to
    'evidence', so older clients and the red-flag citation keep working); the
    experience list is rendered with `tag_prefix="ex"` so its markers can
    never collide with, or be mistaken for, an [ev_N] in the same answer.
    """
    return [
        {
            "tag": f"{tag_prefix}_{i}",
            "tier": tier or m.tier,
            "source_id": str(m.source_id),
            "chunk_id": str(m.chunk_id),
            "title": m.source_title,
            "organization": m.organization,
            "year": m.publication_year,
            "url": m.url,
            "snippet": m.content[:280],
            "distance": round(m.distance, 4),
        }
        for i, m in enumerate(matches, start=1)
    ]


async def retrieve_experience(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    top_k: int = 3,
    max_distance: float | None = None,
    relative_margin: float | None = None,
) -> list[EvidenceMatch]:
    """What other parents report, for the optional last section of a plan.

    The same engine as retrieve_evidence, read under `tier='experience'` and
    nothing else: no specialty filter (the tier is the lock), the same
    absolute cut-off and the same relative margin as the clinical call, so
    the softer tier is admitted no more generously than the studies are. It
    is a separate function, not a flag at the call site, so the demo can be
    tested with one tier stubbed and the other not, and so a reader of the
    answering path sees two calls where there are two kinds of source.

    It is never consulted before the evidence call decides the `kind` of the
    answer: a question with experience hits and no evidence is still
    `no_evidence` (tests/test_demo_experience.py).
    """
    return await retrieve_evidence(
        session,
        query_embedding=query_embedding,
        top_k=top_k,
        max_distance=max_distance,
        relative_margin=relative_margin,
        tier=EXPERIENCE_TIER,
    )


def format_experience_for_prompt(matches: list[EvidenceMatch]) -> str:
    """The experience block of the prompt: labelled, apart, with its own tags.

    The model reads it after the clinical evidence and is told, in the same
    block it reads the text in, what it is and what it may not be used for.
    The rule itself (one optional section, never doses, never warning signs,
    never against a cited guideline) lives in answer_contract with the rest
    of the contract; this header is the reminder next to the material.
    """
    if not matches:
        return ""
    lines = [
        "## What other parents report (cite as [ex_N]; experience, not medical evidence; "
        "only for the optional last section; never for doses, warning signs or anything a "
        "cited guideline contradicts):"
    ]
    for i, m in enumerate(matches, start=1):
        attribution = m.source_title
        if m.organization:
            attribution = f"{m.organization}: {attribution}"
        if m.publication_year:
            attribution = f"{attribution} ({m.publication_year})"
        lines.append(f"[ex_{i}] {attribution}")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines)
