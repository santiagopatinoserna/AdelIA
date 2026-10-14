"""Clinical questionnaires + reasoning endpoints."""

from fastapi import APIRouter, Response

from adelia.clinical.questionnaire import load_reflux_questionnaire
from adelia.services.corpus_stats import CACHE_TTL_S, CorpusStats, get_corpus_stats

router = APIRouter(prefix="/clinical", tags=["clinical"])


@router.get("/reflux-questionnaire")
async def reflux_questionnaire() -> dict:
    """The evidence-grounded reflux control questionnaire (every question
    carries its clinical rationale + source). Public: it's general clinical
    guidance, not patient data."""
    return load_reflux_questionnaire()


@router.get("/corpus-stats", response_model=CorpusStats)
async def corpus_stats(response: Response) -> CorpusStats:
    """How big the evidence corpus is, counted in the database (audit 1.1).

    Public and unauthenticated: the landing renders it for visitors with no
    account, and it carries no patient data, only aggregate counts of the
    guideline and study corpus. Cached in-process and, through Cache-Control,
    by whatever sits in front, so a crowd on the landing costs one aggregate
    query every few minutes."""
    response.headers["Cache-Control"] = f"public, max-age={int(CACHE_TTL_S)}"
    return await get_corpus_stats()
