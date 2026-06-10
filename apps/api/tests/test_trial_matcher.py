"""Tests for ClinicalTrials.gov trial matcher.

Pure: _parse_study with sample API responses.
Live: gated test against the real API (skipped if no network).
"""
from __future__ import annotations

import pytest

from adelia.enrichment.trial_matcher import _parse_study, search_trials


SAMPLE_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT05000000",
            "briefTitle": "Test trial for T2D",
        },
        "statusModule": {"overallStatus": "RECRUITING"},
        "descriptionModule": {"briefSummary": "A sample trial. " * 5},
        "designModule": {"phases": ["PHASE3"]},
        "conditionsModule": {"conditions": ["Type 2 Diabetes Mellitus"]},
        "armsInterventionsModule": {
            "interventions": [
                {"name": "Drug A 50mg"},
                {"name": "Placebo"},
            ]
        },
        "eligibilityModule": {
            "minimumAge": "18 Years",
            "maximumAge": "75 Years",
            "sex": "ALL",
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Test Pharma"}
        },
        "contactsLocationsModule": {
            "locations": [
                {
                    "facility": "Hospital Universitario La Paz",
                    "city": "Madrid",
                    "country": "Spain",
                    "status": "RECRUITING",
                }
            ]
        },
    }
}


def test_parse_study_extracts_core_fields():
    trial = _parse_study(SAMPLE_STUDY)
    assert trial is not None
    assert trial.nct_id == "NCT05000000"
    assert trial.title == "Test trial for T2D"
    assert trial.status == "RECRUITING"
    assert trial.phase == "PHASE3"
    assert "Type 2 Diabetes Mellitus" in trial.conditions
    assert "Drug A 50mg" in trial.interventions
    assert trial.eligibility_age_min == "18 Years"
    assert trial.sponsor == "Test Pharma"
    assert len(trial.locations) == 1
    assert trial.locations[0]["city"] == "Madrid"
    assert trial.url == "https://clinicaltrials.gov/study/NCT05000000"


def test_parse_study_missing_nct_id_returns_none():
    bad_study = {"protocolSection": {"identificationModule": {}}}
    assert _parse_study(bad_study) is None


def test_parse_study_handles_empty_locations():
    minimal = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT99", "briefTitle": "Minimal"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "descriptionModule": {"briefSummary": ""},
            "designModule": {"phases": []},
            "conditionsModule": {"conditions": []},
            "armsInterventionsModule": {"interventions": []},
            "eligibilityModule": {},
            "sponsorCollaboratorsModule": {},
            "contactsLocationsModule": {"locations": []},
        }
    }
    trial = _parse_study(minimal)
    assert trial is not None
    assert trial.locations == []
    assert trial.interventions == []
    assert trial.phase is None
    assert trial.eligibility_age_min is None


def test_parse_study_truncates_long_summary():
    long_summary = {**SAMPLE_STUDY}
    long_summary["protocolSection"] = {**SAMPLE_STUDY["protocolSection"]}
    long_summary["protocolSection"]["descriptionModule"] = {
        "briefSummary": "x" * 2000,
    }
    trial = _parse_study(long_summary)
    assert trial is not None
    assert len(trial.brief_summary) <= 500


@pytest.mark.asyncio
async def test_search_trials_returns_empty_on_network_error(monkeypatch):
    """Network errors should be swallowed → empty list, not raise."""
    from adelia.enrichment import trial_matcher

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *args, **kwargs):
            import httpx

            raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr(trial_matcher.httpx, "AsyncClient", FakeClient)

    trials = await search_trials(condition="diabetes", country="Spain")
    assert trials == []


@pytest.mark.asyncio
async def test_search_trials_parses_api_response(monkeypatch):
    """End-to-end with a mocked HTTP response."""
    from adelia.enrichment import trial_matcher

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return FakeResponse({"studies": [SAMPLE_STUDY]})

    monkeypatch.setattr(trial_matcher.httpx, "AsyncClient", FakeClient)

    trials = await search_trials(condition="type 2 diabetes", country="Spain")
    assert len(trials) == 1
    assert trials[0].nct_id == "NCT05000000"
