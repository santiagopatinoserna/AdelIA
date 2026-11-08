import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from adelia import ratelimit
from adelia.qa_traffic import QATrafficMiddleware
from adelia.config import settings
from adelia.db import engine
from adelia.services import usage
from adelia.routers import (
    agent,
    analytics,
    billing,
    briefings,
    chat,
    consent,
    demo,
    documents,
    enrichment,
    funnel,
    guest,
    health,
    ingestion,
    ingestion_webhooks,
    clinical,
    sharing,
    today,
    users,
)


logger = logging.getLogger("adelia")
# uvicorn only configures its own loggers; give the adelia namespace a
# stdout handler so access/slow-request lines actually surface.
if not logging.getLogger("adelia").handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger("adelia").addHandler(_handler)
    logging.getLogger("adelia").setLevel(logging.INFO)
# Never print the Telegram bot token (part of every Bot API URL) in logs.
from adelia.services.telegram_diary import install_log_redaction  # noqa: E402

install_log_redaction()


SWEEP_INTERVAL_S = 3600


async def _periodic_tombstone_sweep() -> None:
    """Hourly loop so 48h/7d consulta tombstones actually get deleted without
    waiting for the next reboot/upload to trigger the opportunistic sweep."""
    from adelia.routers.users import sweep_blob_tombstones

    while True:
        await asyncio.sleep(SWEEP_INTERVAL_S)
        try:
            await sweep_blob_tombstones()
        except Exception:  # noqa: BLE001 — one bad tick must not kill the loop
            logger.exception("periodic blob tombstone sweep failed")


#: Daily, like the retention it enforces: 13 months to the day is precise
#: enough when the cut runs every 24 hours.
ANALYTICS_PURGE_INTERVAL_S = 24 * 3600


#: The boot purge is awaited before the app serves; this bounds it, so a slow
#: database can delay a boot by seconds, never block it.
ANALYTICS_BOOT_PURGE_TIMEOUT_S = 30.0


async def _purge_analytics_once() -> None:
    """Delete visitor journeys past 13 months and consent proofs past theirs."""
    from adelia.services import analytics as analytics_service

    try:
        deleted = await analytics_service.purge_expired()
        if any(deleted.values()):
            logger.info("analytics retention purge: %s", deleted)
    except Exception:  # noqa: BLE001 — one bad tick must not kill the loop
        logger.exception("analytics retention purge failed")


async def _periodic_analytics_purge() -> None:
    """Daily after the boot purge: a server that restarts often purges on
    boot (lifespan), one that never restarts purges anyway."""
    while True:
        await asyncio.sleep(ANALYTICS_PURGE_INTERVAL_S)
        await _purge_analytics_once()


def seconds_until_next_reminder(now, hour: int) -> float:
    """Real seconds from `now` (aware, local tz) to the next `hour`:00 local.

    Computed on epoch timestamps, not on the wall-clock timedelta: two
    datetimes sharing one ZoneInfo subtract their naive values, which is
    24 h on a DST day when the real gap is 23 h or 25 h (a reminder one hour
    late in March, two reminders in October)."""
    from datetime import timedelta

    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(0.0, target.timestamp() - now.timestamp())


async def _daily_diary_reminder() -> None:
    """Telegram-first daily diary: at diary_reminder_hour (local tz) nudge
    every linked chat that hasn't written today's entry."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from adelia.services.telegram_diary import send_daily_reminders

    tz = ZoneInfo(settings.diary_reminder_tz)
    while True:
        await asyncio.sleep(seconds_until_next_reminder(datetime.now(tz), settings.diary_reminder_hour))
        try:
            sent = await send_daily_reminders()
            logger.info("daily diary reminder sent to %d chat(s)", sent)
        except Exception:  # noqa: BLE001 — one bad day must not kill the loop
            logger.exception("daily diary reminder failed")


#: Waits before trying again a corpus file that stopped on a 429 or a network
#: error, after embed_with_retry's own 77 s of backoff ran out. The load runs
#: beside the server (lifespan), so waiting costs nothing but time; the gate
#: (scripts/golden_gate.sh) awaits the same function and waits with it.
STARTUP_RETRY_DELAYS: tuple[float, ...] = (60.0, 300.0)


async def load_startup_corpora() -> list[str]:
    """`_load_startup_corpora`, its provider calls counted as `corpus`: the
    corpus embeddings at boot are the product's cost, not a mother's
    (services/usage). A plain function, not a decorator, so its code object
    stays in this file for tests/test_startup_corpora.py."""
    with usage.surface("corpus"):
        return await _load_startup_corpora()


async def _load_startup_corpora() -> list[str]:
    """Load the clinical corpora, then the experience fixture, at boot.

    Clinical evidence: seed plus per-topic `enrichment/data/evidence_*.json`.
    Idempotent by title, so re-running on every boot is safe; new topics drop
    in as JSON. Then `enrichment/experience/*.json`, what other mothers say,
    through its own loader (adelia.enrichment.experience_loader), which is
    what writes `tier = 'experience'` on every row: a separate directory and a
    separate glob, so no experience file can ever be swept into the clinical
    load by matching a name. Each stage swallows its own failure: evidence
    must never block boot, and experience must never block evidence.

    A file that stops on an error waiting can fix (evidence_loader.
    is_transient: a 429 that outlasted the backoff, the network) is tried
    again after each of STARTUP_RETRY_DELAYS, from the source where it
    stopped, because each source is committed whole, and the files after it
    in that pass wait with it. Before 2026-11-07 the rest of it waited for the
    next boot, and production boots on a deploy. With Mistral limiting all the
    way through, the whole load gives up after about 10 minutes (three cuts
    of 77 s plus the two waits), not one cut per file.

    Returns the evidence files that did not load whole, so the golden gate
    never measures a corpus smaller than the one about to serve.
    """
    if not settings.mistral_api_key:
        return []
    failed: list[str] = []
    try:
        from adelia.enrichment import evidence_loader

        # A seed that fails stops the files too, as before: loaded on an empty
        # table they would make it non-empty, and the seed loads only then.
        await evidence_loader.load_seed_if_empty()
        _data_dir = Path(__file__).parent / "enrichment" / "data"
        pending = [
            f for f in sorted(_data_dir.glob("evidence_*.json")) if f.name != "evidence_seed.json"
        ]
        for delay in (None, *STARTUP_RETRY_DELAYS):
            if not pending:
                break
            if delay is not None:
                logger.warning("startup evidence load: %d file(s) cut short, again in %.0fs",
                               len(pending), delay)
                await asyncio.sleep(delay)
            retry: list[Path] = []
            for i, _f in enumerate(pending):
                try:
                    await evidence_loader.load_evidence_file(_f)
                except Exception as exc:  # noqa: BLE001 — one bad file must not skip the rest
                    logger.exception("startup evidence load failed for %s", _f.name)
                    if not evidence_loader.is_transient(exc):
                        failed.append(_f.name)
                        continue
                    # Each cut has already cost 77 s of backoff; the other
                    # files would pay it too, so they wait for the next pass.
                    retry = pending[i:]
                    break
            pending = retry
        failed += [f.name for f in pending]
    except Exception:  # noqa: BLE001 — evidence load must never block boot
        logger.exception("startup evidence load failed")
        failed.append("evidence (load aborted)")
    try:
        from adelia.enrichment import experience_loader

        await experience_loader.load_experience_dir()
    except Exception:  # noqa: BLE001 — experience load must never block boot
        logger.exception("startup experience load failed")
    if failed:
        logger.error("startup evidence load incomplete: %s", ", ".join(failed))
    return failed


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.auth_secret:
        # Auth endpoints will answer 503 until this is fixed (adelia/auth.py).
        logger.critical("AUTH_SECRET is not set — all authenticated requests will be rejected")
    # Retry blob deletions a crashed/failed GDPR erasure left behind.
    try:
        from adelia.routers.users import sweep_blob_tombstones

        await sweep_blob_tombstones()
    except Exception:  # noqa: BLE001 — sweep must never block boot
        logger.exception("startup blob tombstone sweep failed")
    # Reconciliation (audit 4.4): whatever a crash, an OOM or the last deploy
    # left half-processed gets cleaned of its partial derivatives and run
    # again. This is the only retry the in-process pipeline has until a
    # durable queue exists, and it is why a document can no longer sit at
    # "procesando" for ever.
    try:
        from adelia.routers.documents import requeue_stuck_documents

        requeued = await requeue_stuck_documents()
        if requeued:
            logger.warning("boot reconciliation requeued %d document(s)", len(requeued))
    except Exception:  # noqa: BLE001 — reconciliation must never block boot
        logger.exception("startup document reconciliation failed")
    # Retention of the consented journeys (13 months), once before serving
    # and then daily. Awaited, not raced beside the first requests: a purge
    # holding a pooled connection while they arrive is the pool exhaustion
    # this app already had once.
    try:
        await asyncio.wait_for(_purge_analytics_once(), ANALYTICS_BOOT_PURGE_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("analytics retention purge at boot timed out; the daily loop retries")
    # Beside the server, not before it (2026-11-07). The 2026-11-06 batch is
    # 316 sources, one Mistral call each with SOURCE_PACING_S between them:
    # minutes. Awaited here, uvicorn did not bind its port until it ended, so
    # /health refused, the container went unhealthy after 5 checks 10 s apart
    # (web waits on it being healthy) and deploy-prod.sh's 60 s of /healthz
    # failed. Meanwhile retrieval reads the corpus loaded so far, which only
    # grows, one whole source at a time.
    corpus_task = asyncio.create_task(load_startup_corpora())
    sweep_task = asyncio.create_task(_periodic_tombstone_sweep())
    analytics_purge_task = asyncio.create_task(_periodic_analytics_purge())
    logger.info("periodic blob tombstone sweep scheduled every %ds", SWEEP_INTERVAL_S)
    reminder_task = None
    if settings.telegram_bot_token:
        reminder_task = asyncio.create_task(_daily_diary_reminder())
        logger.info("daily diary reminder scheduled at %02d:00 %s",
                    settings.diary_reminder_hour, settings.diary_reminder_tz)
    yield
    # Boot reconciliation's pipelines use the engine: they must be gone before
    # it is disposed, or they check out connections from the rebuilt pool that
    # the loop teardown then abandons (see cancel_background_pipelines).
    await documents.cancel_background_pipelines()
    # Same for the sweep an account erasure starts after its 204.
    from adelia.routers.users import drain_erasure_sweeps

    await drain_erasure_sweeps()
    # And the embedding fills a guest's creation starts after its 201.
    await guest.drain_seed_tasks()
    for task in (corpus_task, sweep_task, analytics_purge_task, reminder_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Last, the usage counts the provider replies above scheduled, the corpus
    # load's included (services/usage): one short upsert each.
    await usage.drain()
    await engine.dispose()


app = FastAPI(title="AdelIA API", version="0.1.0", lifespan=lifespan)

SLOW_REQUEST_THRESHOLD_S = 2.0


@app.middleware("http")
async def rate_limiting(request: Request, call_next):
    """Outermost guard: cheap fixed-window limits before any real work."""
    if settings.rate_limit_enabled and request.url.path != "/health":
        identity = ratelimit.identity_for(request)
        allowed, retry_after = ratelimit.check(
            request.method, request.url.path, identity
        )
        if not allowed:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline security headers on every API response. The public share
    HTML (/s/{token}) loads its stylesheet from /s/_assets/, same origin,
    because the production proxy only forwards /s/ to the API."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/s/"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
    return response


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Minimal structured access log + slow-request warning.

    Fly.io/Grafana pick logs from stdout — this is the v0.1.1 observability
    baseline until OpenTelemetry lands. Skips /health to keep probes quiet.
    """
    if request.url.path == "/health":
        return await call_next(request)
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.exception(
            "request_failed method=%s path=%s elapsed_ms=%.0f",
            request.method, request.url.path, elapsed_ms,
        )
        raise
    elapsed = time.monotonic() - start
    log = logger.warning if elapsed > SLOW_REQUEST_THRESHOLD_S else logger.info
    log(
        "request method=%s path=%s status=%d elapsed_ms=%.0f",
        request.method, request.url.path, response.status_code, elapsed * 1000,
    )
    return response

# Test traffic (X-AdelIA-QA: 1) is served as usual and only left out of the
# counters (adelia/qa_traffic.py).
app.add_middleware(QATrafficMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(briefings.router)
app.include_router(consent.router)
app.include_router(ingestion.router)
app.include_router(ingestion_webhooks.router)
app.include_router(enrichment.router)
app.include_router(sharing.router)
app.include_router(users.router)
app.include_router(clinical.router)
app.include_router(billing.router)
app.include_router(agent.router)
app.include_router(today.router)
# Public, unauthenticated, and deliberately last so the list reads as
# "everything above needs a session; these do not" (audit 4.6, 4.8). The
# analytics reads are admin-only, but its writes are public like the funnel's.
app.include_router(demo.router)
app.include_router(guest.router)
app.include_router(funnel.router)
app.include_router(analytics.router)
