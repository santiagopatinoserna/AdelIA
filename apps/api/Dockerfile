# AdelIA API — production image (also the Fly.io build).
FROM python:3.12-slim-bookworm

# WeasyPrint needs pango/cairo at runtime; curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Layer-cache deps: lockfile first, code later.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY adelia ./adelia
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Migrations run on boot — idempotent, single-writer safe for one replica.
# Scale-out later moves this to a release command (fly deploy --release-command).
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn adelia.main:app --host 0.0.0.0 --port 8000"]
