import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from adelia import ratelimit
from adelia.config import settings
from adelia.db import engine
from adelia.routers import (
    agent,
    billing,
    briefings,
    chat,
    consent,
    documents,
    enrichment,
    health,
    ingestion,
    ingestion_webhooks,
    clinical,
    sharing,
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


async def _daily_diary_reminder() -> None:
    """Telegram-first daily diary: at diary_reminder_hour (local tz) nudge
    every linked chat that hasn't written today's entry."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from adelia.services.telegram_diary import send_daily_reminders

    tz = ZoneInfo(settings.diary_reminder_tz)
    while True:
        now = datetime.now(tz)
        target = now.replace(hour=settings.diary_reminder_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            sent = await send_daily_reminders()
            logger.info("daily diary reminder sent to %d chat(s)", sent)
        except Exception:  # noqa: BLE001 — one bad day must not kill the loop
            logger.exception("daily diary reminder failed")


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
    # Load clinical evidence corpora (seed + per-topic files). Idempotent by
    # title, so re-running on every boot is safe; new topics drop in as JSON.
    if settings.mistral_api_key:
        try:
            from pathlib import Path as _Path

            from adelia.enrichment.evidence_loader import (
                load_evidence_file,
                load_seed_if_empty,
            )

            await load_seed_if_empty()
            _data_dir = _Path(__file__).parent / "enrichment" / "data"
            for _f in sorted(_data_dir.glob("evidence_*.json")):
                if _f.name != "evidence_seed.json":
                    await load_evidence_file(_f)
        except Exception:  # noqa: BLE001 — evidence load must never block boot
            logger.exception("startup evidence load failed")
    sweep_task = asyncio.create_task(_periodic_tombstone_sweep())
    logger.info("periodic blob tombstone sweep scheduled every %ds", SWEEP_INTERVAL_S)
    reminder_task = None
    if settings.telegram_bot_token:
        reminder_task = asyncio.create_task(_daily_diary_reminder())
        logger.info("daily diary reminder scheduled at %02d:00 %s",
                    settings.diary_reminder_hour, settings.diary_reminder_tz)
    yield
    for task in (sweep_task, reminder_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await engine.dispose()


app = FastAPI(title="AdelIA API", version="0.1.0", lifespan=lifespan)

SLOW_REQUEST_THRESHOLD_S = 2.0


@app.middleware("http")
async def rate_limiting(request: Request, call_next):
    """Outermost guard: cheap fixed-window limits before any real work."""
    if settings.rate_limit_enabled and request.url.path != "/health":
        identity = ratelimit.identity_from(
            request.headers.get("authorization"),
            request.client.host if request.client else "unknown",
        )
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
    HTML (/s/{token}) renders styles from /static — same-origin CSP."""
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
