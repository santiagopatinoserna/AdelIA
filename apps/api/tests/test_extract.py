from pathlib import Path

import pytest

from adelia.config import settings
from adelia.schemas import ExtractedEntity
from adelia.workers.extract import extract_entities


FIXTURE = Path(__file__).parent / "fixtures" / "sample-clinical-note.txt"


@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key")
async def test_extract_entities_from_clinical_note():
    text = FIXTURE.read_text()
    entities = await extract_entities(text)

    assert isinstance(entities, list)
    assert len(entities) >= 5  # At least: 2 conditions + 2 meds + 1 allergy + lab/vitals
    for e in entities:
        assert isinstance(e, ExtractedEntity)
        # Anti-hallucination invariant: raw_quote must appear in source
        assert e.raw_quote in text, f"hallucinated quote: {e.raw_quote!r}"

    # Spot-check coverage: must extract Metformin
    medication_names = [e.name.lower() for e in entities if e.entity_type == "medication"]
    assert any("metformin" in n for n in medication_names), "metformin missing"

    # Spot-check: penicillin allergy
    allergy_names = [e.name.lower() for e in entities if e.entity_type == "allergy"]
    assert any("penicillin" in n for n in allergy_names), "penicillin allergy missing"


async def test_extract_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY not set"):
        await extract_entities("any text")
