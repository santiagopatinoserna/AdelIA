import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from adelia.config import settings
from adelia.db import engine
from adelia.routers import (
    briefings,
    chat,
    documents,
    enrichment,
    health,
    ingestion,
    ingestion_webhooks,
    sharing,
)


logger = logging.getLogger("adelia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.auth_secret:
        # Auth endpoints will answer 503 until this is fixed (adelia/auth.py).
        logger.critical("AUTH_SECRET is not set — all authenticated requests will be rejected")
    yield
    await engine.dispose()


app = FastAPI(title="AdelIA API", version="0.1.0", lifespan=lifespan)

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
app.include_router(ingestion.router)
app.include_router(ingestion_webhooks.router)
app.include_router(enrichment.router)
app.include_router(sharing.router)
