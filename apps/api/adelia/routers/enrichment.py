"""v0.2 enrichment router — exposes all 7 enrichment layers via REST.

Endpoints:
- GET    /enrichment/code-normalize        → ICD-10 + SNOMED normalize
- POST   /enrichment/lab-evaluate          → bulk lab value → reference range eval
- POST   /enrichment/drug-interactions     → pairwise interaction check
- GET    /enrichment/trials                → ClinicalTrials.gov search by condition
- POST   /enrichment/genomics/upload       → 23andMe raw upload → variant match
- GET    /enrichment/profiles              → list user profiles
- POST   /enrichment/profiles              → create profile
- GET    /enrichment/profiles/{id}         → get profile (opaque 404 cross-user)
- POST   /enrichment/profiles/{id}/default → set as default
- DELETE /enrichment/profiles/{id}         → soft-delete (protected: not the only one)
- GET    /enrichment/coverage              → stats: how many concepts/labs/drugs/variants loaded
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import get_db
from adelia.models import GenomicVariant
from adelia.enrichment import (
    drug_interactions as drug_svc,
    genomics as gen_svc,
    lab_ranges as lab_svc,
    normalization as norm_svc,
    profile_service,
    trial_matcher,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enrichment", tags=["enrichment"])


# ============================================================================
# L1 — Code normalization
# ============================================================================


class NormalizeOut(BaseModel):
    query: str
    canonical_name: str | None = None
    icd10: str | None = None
    snomed: str | None = None
    category: str | None = None
    match_score: int = 0


@router.get("/code-normalize", response_model=NormalizeOut)
async def code_normalize(
    query: Annotated[str, Query(min_length=1, max_length=256)],
    min_score: int = 80,
    _user_id: UUID = Depends(get_current_user_id),
):
    result = norm_svc.normalize(query, min_score=min_score)
    if result is None:
        return NormalizeOut(query=query)
    return NormalizeOut(
        query=query,
        canonical_name=result.canonical_name,
        icd10=result.icd10,
        snomed=result.snomed,
        category=result.category,
        match_score=result.match_score,
    )


# ============================================================================
# L2 — Lab reference ranges
# ============================================================================


class LabEvalRequest(BaseModel):
    name: str
    value: float | str
    sex: str | None = None  # "M" | "F"


class LabEvalBulkRequest(BaseModel):
    observations: list[LabEvalRequest] = Field(default_factory=list, max_length=200)
    sex: str | None = None  # default sex applied when item lacks one


class LabEvalResult(BaseModel):
    name: str
    canonical_name: str | None = None
    value: float | None = None
    unit: str | None = None
    flag: str | None = None  # "low" | "normal" | "high"
    zone_label: str | None = None
    interpretation: str | None = None
    range_low: float | None = None
    range_high: float | None = None


@router.post("/lab-evaluate", response_model=list[LabEvalResult])
async def lab_evaluate(
    payload: LabEvalBulkRequest,
    _user_id: UUID = Depends(get_current_user_id),
):
    out: list[LabEvalResult] = []
    for obs in payload.observations:
        sex = obs.sex or payload.sex
        # mypy-friendly cast — service does its own validation
        status_obj = lab_svc.evaluate(obs.name, obs.value, sex=sex)  # type: ignore[arg-type]
        if status_obj is None:
            out.append(LabEvalResult(name=obs.name))
            continue
        out.append(
            LabEvalResult(
                name=obs.name,
                canonical_name=status_obj.canonical_name,
                value=status_obj.value,
                unit=status_obj.unit,
                flag=status_obj.flag,
                zone_label=status_obj.zone_label,
                interpretation=status_obj.interpretation,
                range_low=status_obj.range.low,
                range_high=status_obj.range.high,
            )
        )
    return out


# ============================================================================
# L3 — Drug interactions
# ============================================================================


class DrugCheckRequest(BaseModel):
    medications: list[str] = Field(default_factory=list, max_length=50)


class DrugInteractionOut(BaseModel):
    drug_a: str
    drug_b: str
    severity: str
    mechanism: str
    recommendation: str


@router.post("/drug-interactions", response_model=list[DrugInteractionOut])
async def drug_interactions_endpoint(
    payload: DrugCheckRequest,
    _user_id: UUID = Depends(get_current_user_id),
):
    found = drug_svc.check_interactions(payload.medications)
    return [
        DrugInteractionOut(
            drug_a=i.drug_a,
            drug_b=i.drug_b,
            severity=i.severity,
            mechanism=i.mechanism,
            recommendation=i.recommendation,
        )
        for i in found
    ]


# ============================================================================
# L5 — Clinical trials
# ============================================================================


class TrialOut(BaseModel):
    nct_id: str
    title: str
    brief_summary: str
    status: str
    phase: str | None = None
    conditions: list[str]
    interventions: list[str]
    locations: list[dict]
    eligibility_age_min: str | None = None
    eligibility_age_max: str | None = None
    eligibility_sex: str | None = None
    sponsor: str | None = None
    url: str


@router.get("/trials", response_model=list[TrialOut])
async def trials_search(
    condition: Annotated[str, Query(min_length=2, max_length=128)],
    country: str | None = None,
    max_results: int = Query(10, ge=1, le=50),
    _user_id: UUID = Depends(get_current_user_id),
):
    trials = await trial_matcher.search_trials(
        condition=condition,
        country=country,
        max_results=max_results,
    )
    return [
        TrialOut(
            nct_id=t.nct_id,
            title=t.title,
            brief_summary=t.brief_summary,
            status=t.status,
            phase=t.phase,
            conditions=t.conditions,
            interventions=t.interventions,
            locations=t.locations,
            eligibility_age_min=t.eligibility_age_min,
            eligibility_age_max=t.eligibility_age_max,
            eligibility_sex=t.eligibility_sex,
            sponsor=t.sponsor,
            url=t.url,
        )
        for t in trials
    ]


# ============================================================================
# L6 — Genomics 23andMe upload
# ============================================================================


class VariantHitOut(BaseModel):
    rsid: str
    gene: str
    user_genotype: str
    risk_alleles: list[str]
    zygosity: str
    category: str
    phenotype: str
    actionability: str
    evidence_level: str
    url: str


@router.post("/genomics/upload", response_model=list[VariantHitOut])
async def genomics_upload(
    file: Annotated[UploadFile, File(description="23andMe raw_data.txt")],
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Allow 23andMe text/csv/tsv content types
    if file.content_type not in {
        "text/plain",
        "text/tab-separated-values",
        "text/csv",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=400, detail="Expected text/tsv file")

    body = await file.read()
    if len(body) > 50 * 1024 * 1024:  # 50MB cap; 23andMe files typically 15-25MB
        raise HTTPException(status_code=413, detail="File exceeds 50MB limit")

    import io

    stream = io.StringIO(body.decode("utf-8", errors="ignore"))
    genotypes = list(gen_svc.parse_23andme_raw(stream))
    hits = gen_svc.match_variants(genotypes)

    # Persist ONLY the matched variants (~20 rows), never the raw file —
    # data minimization. Re-upload replaces the previous analysis.
    await db.execute(
        sa.delete(GenomicVariant).where(GenomicVariant.user_id == user_id)
    )
    for h in hits:
        db.add(GenomicVariant(
            user_id=user_id,
            rsid=h.rsid,
            gene=h.gene,
            user_genotype=h.user_genotype,
            risk_alleles=list(h.risk_alleles),
            zygosity=h.zygosity,
            category=h.category,
            phenotype=h.phenotype,
            actionability=h.actionability,
            evidence_level=h.evidence_level,
            url=h.url,
        ))
    await db.commit()

    return [
        VariantHitOut(
            rsid=h.rsid,
            gene=h.gene,
            user_genotype=h.user_genotype,
            risk_alleles=list(h.risk_alleles),
            zygosity=h.zygosity,
            category=h.category,
            phenotype=h.phenotype,
            actionability=h.actionability,
            evidence_level=h.evidence_level,
            url=h.url,
        )
        for h in hits
    ]


class SavedGenomicsOut(BaseModel):
    analyzed_at: datetime | None = None
    variants: list[VariantHitOut]


@router.get("/genomics", response_model=SavedGenomicsOut)
async def genomics_saved(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Saved analysis — the page loads this instead of asking for a re-upload."""
    result = await db.execute(
        sa.select(GenomicVariant)
        .where(GenomicVariant.user_id == user_id)
        .order_by(GenomicVariant.category, GenomicVariant.gene)
    )
    rows = result.scalars().all()
    return SavedGenomicsOut(
        analyzed_at=rows[0].analyzed_at if rows else None,
        variants=[
            VariantHitOut(
                rsid=r.rsid,
                gene=r.gene,
                user_genotype=r.user_genotype,
                risk_alleles=list(r.risk_alleles or []),
                zygosity=r.zygosity,
                category=r.category,
                phenotype=r.phenotype,
                actionability=r.actionability,
                evidence_level=r.evidence_level,
                url=r.url,
            )
            for r in rows
        ],
    )


# ============================================================================
# L7 — Profiles
# ============================================================================


class ProfileCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    relationship: str = "self"  # validated against enum below
    date_of_birth: date | None = None
    sex: str | None = None  # M | F | other
    is_default: bool = False


class ProfileOut(BaseModel):
    id: UUID
    display_name: str
    relationship: str
    date_of_birth: date | None = None
    sex: str | None = None
    is_default: bool
    created_at: object  # datetime — JSON serializes via Pydantic


_VALID_RELATIONSHIPS = {"self", "child", "parent", "spouse", "sibling", "other"}


def _profile_to_out(p) -> ProfileOut:
    return ProfileOut(
        id=p.id,
        display_name=p.display_name,
        relationship=p.relationship,
        date_of_birth=p.date_of_birth,
        sex=p.sex,
        is_default=p.is_default,
        created_at=p.created_at,
    )


@router.get("/profiles", response_model=list[ProfileOut])
async def list_user_profiles(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Ensure default exists for legacy v0.1 users
    await profile_service.ensure_default_profile(db, user_id=user_id)
    await db.commit()
    profiles = await profile_service.list_profiles(db, user_id=user_id)
    return [_profile_to_out(p) for p in profiles]


@router.post(
    "/profiles", status_code=status.HTTP_201_CREATED, response_model=ProfileOut
)
async def create_user_profile(
    payload: ProfileCreateRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if payload.relationship not in _VALID_RELATIONSHIPS:
        raise HTTPException(
            status_code=422,
            detail=f"relationship must be one of {sorted(_VALID_RELATIONSHIPS)}",
        )
    created = await profile_service.create_profile(
        db,
        user_id=user_id,
        data=profile_service.ProfileCreate(
            display_name=payload.display_name,
            relationship=payload.relationship,  # type: ignore[arg-type]
            date_of_birth=payload.date_of_birth,
            sex=payload.sex,
            is_default=payload.is_default,
        ),
    )
    await db.commit()
    return _profile_to_out(created)


@router.get("/profiles/{profile_id}", response_model=ProfileOut)
async def get_user_profile(
    profile_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    p = await profile_service.get_profile(db, profile_id=profile_id, user_id=user_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_to_out(p)


@router.post("/profiles/{profile_id}/default", response_model=ProfileOut)
async def set_default(
    profile_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    p = await profile_service.set_default_profile(
        db, profile_id=profile_id, user_id=user_id
    )
    if p is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.commit()
    return _profile_to_out(p)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_profile(
    profile_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    ok = await profile_service.soft_delete_profile(
        db, profile_id=profile_id, user_id=user_id
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: profile not found or is the only profile",
        )
    await db.commit()
    return Response(status_code=204)


# ============================================================================
# Coverage / stats
# ============================================================================


class CoverageOut(BaseModel):
    normalization: dict
    lab_ranges_count: int
    drugs: dict
    variants: dict


@router.get("/coverage", response_model=CoverageOut)
async def coverage_stats_endpoint(_user_id: UUID = Depends(get_current_user_id)):
    return CoverageOut(
        normalization=norm_svc.coverage_stats(),
        lab_ranges_count=lab_svc.coverage_count(),
        drugs=drug_svc.coverage_stats(),
        variants=gen_svc.catalog_stats(),
    )
