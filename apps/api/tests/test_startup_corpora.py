"""Boot loads the experience fixture from its own directory, after the corpus.

The clinical loop in main.py reads `enrichment/data/evidence_*.json`. The
experience files live in `enrichment/experience/` and go through their own
loader (the tier is set there), so they can never be swept into the clinical
load by matching a glob, and a failure in them never blocks boot or the
evidence that loaded before them.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from mistralai.client.errors import MistralError

from adelia import main
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


# --- boot does not wait for the corpus (2026-11-07) --------------------------------
#
# The 2026-11-06 batch adds 316 sources and 805 chunks to data/. Boot embeds each
# new source with Mistral, one call per source and SOURCE_PACING_S between them,
# so the load takes minutes. It ran inside the lifespan, before uvicorn binds
# its port: /health refused connections all that time, the api container went
# unhealthy after 5 checks 10 s apart (infra/docker-compose.prod.yml), web
# depends on it being healthy, and deploy-prod.sh gives /healthz 12 tries 5 s
# apart. The load now runs beside the server, and the corpus fills in source
# by source as it did before, each one committed whole.

@pytest.fixture
def quiet_lifespan(monkeypatch):
    """Everything the lifespan does besides the corpus, stubbed: the dev
    database is shared and full of stuck rows (CLAUDE.md)."""
    order: list[str] = []
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr("adelia.routers.users.sweep_blob_tombstones", AsyncMock())
    monkeypatch.setattr("adelia.routers.users.drain_erasure_sweeps", AsyncMock())
    monkeypatch.setattr("adelia.routers.documents.requeue_stuck_documents",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr("adelia.routers.documents.cancel_background_pipelines", AsyncMock())
    monkeypatch.setattr("adelia.routers.guest.drain_seed_tasks", AsyncMock())

    async def _dispose():
        order.append("engine disposed")

    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=_dispose))
    return order


async def test_the_api_serves_while_the_corpus_is_still_loading(monkeypatch, quiet_lifespan):
    started, release = asyncio.Event(), asyncio.Event()

    async def _slow_load():
        started.set()
        await release.wait()

    monkeypatch.setattr(main, "load_startup_corpora", _slow_load)
    cm = main.lifespan(main.app)
    await asyncio.wait_for(cm.__aenter__(), timeout=2)
    await asyncio.wait_for(started.wait(), timeout=2)
    release.set()
    await cm.__aexit__(None, None, None)


async def test_shutdown_stops_a_corpus_load_before_the_engine_goes(monkeypatch, quiet_lifespan):
    """A deploy can stop the container mid-load. The task must be cancelled and
    awaited before engine.dispose(), or it checks a connection out of the pool
    the teardown abandons; the source it was on is not committed, and the next
    boot loads it (idempotent by title)."""
    started = asyncio.Event()

    async def _endless_load():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            quiet_lifespan.append("corpus load cancelled")
            raise

    monkeypatch.setattr(main, "load_startup_corpora", _endless_load)
    cm = main.lifespan(main.app)
    await asyncio.wait_for(cm.__aenter__(), timeout=2)
    await asyncio.wait_for(started.wait(), timeout=2)
    await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=2)
    assert quiet_lifespan == ["corpus load cancelled", "engine disposed"]


# --- a file cut by a rate limit is loaded again in the same boot --------------------
#
# Each source is embedded with backoff (evidence_loader.EMBED_RETRY_DELAYS, 77 s in
# all). When Mistral is still saying 429 after that, the file stops at that source;
# what it committed stays, the rest of the file waited for the next boot, and
# production boots only on a deploy. The file is now tried again later in the
# same boot, from where it stopped. An error that waiting does not fix (a broken
# file, no key) is not retried.


class _RateLimited(MistralError):
    def __init__(self):
        self.message = "API error occurred: Status 429. Body: rate_limited"
        Exception.__init__(self, self.message)
        self.status_code = 429


def _evidence_files() -> list[str]:
    data_dir = Path(main.__file__).parent / "enrichment" / "data"
    return sorted(p.name for p in data_dir.glob("evidence_*.json") if p.name != "evidence_seed.json")


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "x")
    monkeypatch.setattr(main, "STARTUP_RETRY_DELAYS", (0.0, 0.0))
    monkeypatch.setattr("adelia.enrichment.evidence_loader.load_seed_if_empty", AsyncMock())
    experience = AsyncMock(return_value=(0, 0))
    monkeypatch.setattr("adelia.enrichment.experience_loader.load_experience_dir", experience)
    return experience


async def test_a_file_cut_by_a_rate_limit_is_loaded_again_in_the_same_boot(monkeypatch, no_wait):
    cut = _evidence_files()[0]
    calls: list[str] = []

    async def _load(path):
        calls.append(path.name)
        if path.name == cut and calls.count(cut) == 1:
            raise _RateLimited()
        return (0, 0)

    monkeypatch.setattr("adelia.enrichment.evidence_loader.load_evidence_file", _load)
    assert await main.load_startup_corpora() == []
    assert calls.count(cut) == 2
    assert all(calls.count(n) == 1 for n in _evidence_files() if n != cut)
    no_wait.assert_awaited_once()


async def test_a_file_that_keeps_failing_is_reported_and_the_rest_still_loads(
    monkeypatch, no_wait
):
    cut = _evidence_files()[-1]
    calls: list[str] = []

    async def _load(path):
        calls.append(path.name)
        if path.name == cut:
            raise _RateLimited()
        return (0, 0)

    monkeypatch.setattr("adelia.enrichment.evidence_loader.load_evidence_file", _load)
    assert await main.load_startup_corpora() == [cut]
    assert calls.count(cut) == 3, "the first pass and one per delay"
    no_wait.assert_awaited_once()


async def test_while_mistral_keeps_limiting_each_pass_stops_at_the_first_cut(
    monkeypatch, no_wait
):
    """Each cut costs the 77 s of backoff. Going on through the other files of
    the pass, every one of them would pay it too (24 files, half an hour, with
    the gate waiting); the rest of the pass waits for the next one instead."""
    calls: list[str] = []

    async def _load(path):
        calls.append(path.name)
        raise _RateLimited()

    monkeypatch.setattr("adelia.enrichment.evidence_loader.load_evidence_file", _load)
    assert await main.load_startup_corpora() == _evidence_files()
    assert calls == [_evidence_files()[0]] * 3


async def test_an_error_waiting_does_not_fix_is_not_retried(monkeypatch, no_wait):
    cut = _evidence_files()[0]
    calls: list[str] = []

    async def _load(path):
        calls.append(path.name)
        if path.name == cut:
            raise ValueError("Expecting ',' delimiter")
        return (0, 0)

    monkeypatch.setattr("adelia.enrichment.evidence_loader.load_evidence_file", _load)
    assert await main.load_startup_corpora() == [cut]
    assert calls.count(cut) == 1


# --- the gate never measures half a corpus ------------------------------------------
#
# scripts/golden_gate.sh awaits the same load_startup_corpora on the scratch copy
# and then measures. Before, a file the rate limit cut was logged and the gate
# measured without the rest of it: a pass for a corpus smaller than the one about
# to boot. Now the load says which files it could not finish, and the gate says it
# did not run (exit 2), which stops the deploy with the old version serving.

GATE_SCRIPT = Path(main.__file__).parents[1] / "scripts" / "golden_gate.sh"


def _gate_load_snippet() -> str:
    text = GATE_SCRIPT.read_text(encoding="utf-8")
    opening = "\"${PY}\" -c '"
    start = text.index(opening) + len(opening)
    return text[start:text.index("'; then", start)]


@pytest.mark.parametrize(("failed", "exits"), [([], False), (["evidence_x.json"], True)])
def test_the_gate_stops_when_a_corpus_file_did_not_load(monkeypatch, failed, exits):
    monkeypatch.setattr(main, "load_startup_corpora", AsyncMock(return_value=failed))
    monkeypatch.setattr("adelia.db.engine", SimpleNamespace(dispose=AsyncMock()))
    code = compile(_gate_load_snippet(), str(GATE_SCRIPT), "exec")
    if exits:
        with pytest.raises(SystemExit) as stop:
            exec(code, {"__name__": "__main__"})
        assert stop.value.code not in (0, None)
    else:
        exec(code, {"__name__": "__main__"})
