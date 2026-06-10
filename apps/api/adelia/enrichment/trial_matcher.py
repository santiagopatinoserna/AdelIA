"""ClinicalTrials.gov trial matching.

Queries the public ClinicalTrials.gov v2 API (no auth required) to find
recruiting trials relevant to a patient's conditions + location preferences.

API docs: https://clinicaltrials.gov/data-api/api
Endpoint: https://clinicaltrials.gov/api/v2/studies

Production note: ClinicalTrials.gov rate-limits ~50 req/min unauth. Cache locally
with TTL 24h for popular conditions. v0.2.1 will add server-side cache.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)


_API_BASE = "https://clinicaltrials.gov/api/v2/studies"

Status = Literal["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "WITHDRAWN", "TERMINATED", "UNKNOWN"]


@dataclass(frozen=True)
class ClinicalTrial:
    nct_id: str
    title: str
    brief_summary: str
    status: Status
    phase: str | None
    conditions: list[str]
    interventions: list[str]
    locations: list[dict]  # [{country, city, facility, status}]
    eligibility_age_min: str | None
    eligibility_age_max: str | None
    eligibility_sex: str | None
    sponsor: str | None
    url: str


def _parse_study(study: dict) -> ClinicalTrial | None:
    """Parse a single study payload from ClinicalTrials.gov API v2."""
    try:
        protocol = study.get("protocolSection", {})
        ident = protocol.get("identificationModule", {})
        status_mod = protocol.get("statusModule", {})
        cond_mod = protocol.get("conditionsModule", {})
        eligib = protocol.get("eligibilityModule", {})
        contacts = protocol.get("contactsLocationsModule", {})
        design = protocol.get("designModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        arms = protocol.get("armsInterventionsModule", {})
        brief_mod = protocol.get("descriptionModule", {})

        nct_id = ident.get("nctId")
        if not nct_id:
            return None

        locations = [
            {
                "country": loc.get("country"),
                "city": loc.get("city"),
                "facility": loc.get("facility"),
                "status": loc.get("status"),
            }
            for loc in contacts.get("locations", [])
        ]

        interventions = [
            inter.get("name", "") for inter in arms.get("interventions", [])
        ]

        return ClinicalTrial(
            nct_id=nct_id,
            title=ident.get("briefTitle", ""),
            brief_summary=brief_mod.get("briefSummary", "")[:500],
            status=status_mod.get("overallStatus", "UNKNOWN"),
            phase=", ".join(design.get("phases", [])) or None,
            conditions=cond_mod.get("conditions", []),
            interventions=interventions,
            locations=locations,
            eligibility_age_min=eligib.get("minimumAge"),
            eligibility_age_max=eligib.get("maximumAge"),
            eligibility_sex=eligib.get("sex"),
            sponsor=sponsor_mod.get("leadSponsor", {}).get("name"),
            url=f"https://clinicaltrials.gov/study/{nct_id}",
        )
    except Exception as e:
        logger.warning("trial parse failed: %s", e)
        return None


async def search_trials(
    *,
    condition: str,
    country: str | None = None,
    status_filter: list[str] | None = None,
    max_results: int = 10,
    timeout: float = 10.0,
) -> list[ClinicalTrial]:
    """Search ClinicalTrials.gov for trials matching a condition.

    Args:
        condition: free-text condition name (e.g. 'type 2 diabetes')
        country: ISO country name or 2-letter code (e.g. 'Spain' or 'France')
        status_filter: list like ['RECRUITING'] to filter; default RECRUITING + ACTIVE_NOT_RECRUITING
        max_results: cap
        timeout: HTTP timeout in seconds

    Returns: list of ClinicalTrial. Empty list if no matches or API unreachable.
    """
    if status_filter is None:
        status_filter = ["RECRUITING", "ACTIVE_NOT_RECRUITING"]

    params: dict[str, str | int] = {
        "query.cond": condition,
        "filter.overallStatus": ",".join(status_filter),
        "pageSize": min(max_results, 100),
        "format": "json",
    }
    if country:
        params["query.locn"] = country

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_API_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("ClinicalTrials.gov unreachable: %s", e)
        return []

    studies = data.get("studies", [])
    trials: list[ClinicalTrial] = []
    for s in studies[:max_results]:
        t = _parse_study(s)
        if t is not None:
            trials.append(t)
    return trials


async def match_for_patient(
    *,
    conditions: list[str],
    country: str | None = None,
    max_per_condition: int = 3,
) -> dict[str, list[ClinicalTrial]]:
    """Bulk match: for each patient condition, find top trials.

    Returns dict mapping condition → list of trials (max_per_condition each).
    """
    results: dict[str, list[ClinicalTrial]] = {}
    for cond in conditions:
        trials = await search_trials(
            condition=cond,
            country=country,
            max_results=max_per_condition,
        )
        results[cond] = trials
    return results
