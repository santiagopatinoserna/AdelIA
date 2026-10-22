"""Boot loads the experience fixture from its own directory, after the corpus.

The clinical loop in main.py reads `enrichment/data/evidence_*.json`. The
experience files live in `enrichment/experience/` and go through their own
loader (the tier is set there), so they can never be swept into the clinical
load by matching a glob, and a failure in them never blocks boot or the
evidence that loaded before them.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from adelia.config import settings
from adelia.main import load_startup_corpora


async def test_boot_loads_evidence_files_then_the_experience_directory(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "x")
    seed = AsyncMock(return_value=(0, 0))
    evidence = AsyncMock(return_value=(0, 0))
    experience = AsyncMock(return_value=(0, 0))
    with patch("adelia.enrichment.evidence_loader.load_seed_if_empty", seed), patch(
        "adelia.enrichment.evidence_loader.load_evidence_file", evidence
    ), patch("adelia.enrichment.experience_loader.load_experience_dir", experience):
        await load_startup_corpora()
    seed.assert_awaited_once()
    loaded = {Path(c.args[0]).name for c in evidence.await_args_list}
    data_dir = Path(load_startup_corpora.__code__.co_filename).parent / "enrichment" / "data"
    expected = {p.name for p in data_dir.glob("evidence_*.json")} - {"evidence_seed.json"}
    assert loaded == expected
    assert not any("experiences" in n for n in loaded), "experience never enters the clinical loop"
    experience.assert_awaited_once()


async def test_an_experience_failure_never_blocks_boot(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "x")
    with patch("adelia.enrichment.evidence_loader.load_seed_if_empty", AsyncMock()), patch(
        "adelia.enrichment.evidence_loader.load_evidence_file", AsyncMock()
    ), patch("adelia.enrichment.experience_loader.load_experience_dir",
             AsyncMock(side_effect=RuntimeError("boom"))):
        await load_startup_corpora()  # must not raise


async def test_without_an_embedding_key_nothing_is_loaded(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "")
    seed = AsyncMock()
    experience = AsyncMock()
    with patch("adelia.enrichment.evidence_loader.load_seed_if_empty", seed), patch(
        "adelia.enrichment.experience_loader.load_experience_dir", experience
    ):
        await load_startup_corpora()
    seed.assert_not_awaited()
    experience.assert_not_awaited()
