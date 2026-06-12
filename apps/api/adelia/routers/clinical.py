"""Clinical questionnaires + reasoning endpoints."""

from fastapi import APIRouter

from adelia.clinical.questionnaire import load_reflux_questionnaire

router = APIRouter(prefix="/clinical", tags=["clinical"])


@router.get("/reflux-questionnaire")
async def reflux_questionnaire() -> dict:
    """The evidence-grounded reflux control questionnaire (every question
    carries its clinical rationale + source). Public: it's general clinical
    guidance, not patient data."""
    return load_reflux_questionnaire()
