# AdelIA API — production image (also the Fly.io build).
#
# Three stages. `base` is the whole production image. `golden` adds the dev
# tools and tests/ on top of the same layers, for the deploy's clinical gate
# (scripts/prod-golden-gate.sh, docs/GOLDEN_GATE_DESPLIEGUE.md): the gate runs
# the code that is about to serve, not a rebuild of it. `runtime` is `base`
# again and comes LAST, so it stays the default target: `docker compose build
# api` and the Fly build produce exactly the production image, with no tests
# and no pytest in it.
FROM python:3.12-slim-bookworm AS base

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
# --no-proxy-headers: request.client stays the connection's peer. It used to be
# --proxy-headers --forwarded-allow-ips=*, which made the client the FIRST
# X-Forwarded-For entry, written by the client: a forged one per request was a
# fresh rate-limit bucket each time (PR #57 review). Behind Cloudflare the real
# address comes from CF-Connecting-IP instead (TRUST_CF_CONNECTING_IP,
# adelia/ratelimit.client_ip). The API builds no URL from the request, so the
# forwarded scheme is not needed either.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn adelia.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers"]

# The deploy gate's image: built only with `--target golden` (the compose
# overlay infra/docker-compose.golden.yml), run once and thrown away.
FROM base AS golden
RUN uv sync --frozen
COPY tests ./tests

FROM base AS runtime
