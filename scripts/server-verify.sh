#!/usr/bin/env bash
# Full verification cycle ON THE SERVER (/opt/adelia-dev checkout), so the
# improve→test loop never loads the laptop: backend suite against a real
# Postgres+MinIO (compose project "adelia-dev", isolated from prod), web
# build, and the recorder e2e against a temporary api+web pair on dev ports.
#
# Run from anywhere:  ssh santiago@<server> 'bash /opt/adelia-dev/scripts/server-verify.sh'
# Exit 0 = everything green (safe to deploy). Non-zero = do NOT deploy.
set -euo pipefail

DEV_DIR="/opt/adelia-dev"
API_PORT="${VERIFY_API_PORT:-8002}"
WEB_PORT="${VERIFY_WEB_PORT:-3002}"
PG_ENV=(POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_USER=adelia
        POSTGRES_PASSWORD=adelia_dev POSTGRES_DB=adelia)
S3_ENV=(S3_ENDPOINT_URL=http://localhost:9000 S3_ACCESS_KEY=minioadmin
        S3_SECRET_KEY=minioadmin S3_BUCKET=adelia-dev)
AUTH_ENV=(AUTH_SECRET=ci-only-secret AUTH_TRUST_HOST=true)

log() { printf '[verify] %s\n' "$*" >&2; }
# Kill by command pattern, not PID: `uv run`/`pnpm exec` wrappers orphan the
# real uvicorn/next-server child when only the parent PID is killed (learned
# from this script's own first run leaving both alive).
cleanup() {
  pkill -f "uvicorn adelia.main:app --port ${API_PORT}" 2>/dev/null || true
  pkill -f "next start -p ${WEB_PORT}" 2>/dev/null || true
  pkill -f "next-server" 2>/dev/null && sleep 1 || true
}
trap cleanup EXIT

cd "${DEV_DIR}"
log "Updating checkout to origin/main..."
git fetch origin main --quiet
git reset --hard origin/main --quiet
log "HEAD: $(git log --oneline -1)"

log "Syncing deps..."
(cd apps/api && uv sync --quiet)
pnpm install --frozen-lockfile --silent

log "Data stack (compose project adelia-dev, isolated from prod)..."
docker compose -p adelia-dev -f infra/docker-compose.dev.yml up -d --quiet-pull 2>/dev/null
for _ in $(seq 1 30); do
  docker ps --filter name=adelia-dev-postgres --format '{{.Status}}' | grep -q healthy && break
  sleep 2
done
(cd apps/api && env "${PG_ENV[@]}" uv run alembic upgrade head 2>&1 | tail -1)

log "Backend suite..."
(cd apps/api && env "${PG_ENV[@]}" "${S3_ENV[@]}" AUTH_SECRET=ci-only-secret uv run pytest -q 2>&1 | tail -1)

log "Web build..."
pnpm --filter @adelia/web build 2>&1 | grep -E "✓ Compiled|Error" | head -1

log "Booting api:${API_PORT} + web:${WEB_PORT} for e2e..."
cleanup
(cd apps/api && env "${PG_ENV[@]}" "${S3_ENV[@]}" AUTH_SECRET=ci-only-secret \
  nohup uv run uvicorn adelia.main:app --port "${API_PORT}" >/tmp/verify-api.log 2>&1 & echo $! > /tmp/verify-api.pid)
for _ in $(seq 1 45); do curl -sf "localhost:${API_PORT}/health" >/dev/null && break; sleep 2; done
curl -sf "localhost:${API_PORT}/health" >/dev/null || { log "API never came up"; tail -5 /tmp/verify-api.log >&2; exit 1; }

(cd apps/web && env "${AUTH_ENV[@]}" \
  DATABASE_URL=postgresql://adelia:adelia_dev@localhost:5434/adelia \
  API_INTERNAL_URL="http://localhost:${API_PORT}" \
  nohup pnpm exec next start -p "${WEB_PORT}" >/tmp/verify-web.log 2>&1 & echo $! > /tmp/verify-web.pid)
for _ in $(seq 1 45); do curl -sf -o /dev/null "localhost:${WEB_PORT}/es" && break; sleep 2; done
curl -sf -o /dev/null "localhost:${WEB_PORT}/es" || { log "web never came up"; tail -5 /tmp/verify-web.log >&2; exit 1; }

log "E2E (recorder + a11y)..."
(cd apps/web && env "${PG_ENV[@]}" AUTH_SECRET=ci-only-secret \
  E2E_BASE_URL="http://localhost:${WEB_PORT}" \
  pnpm exec playwright test e2e/consulta-record.spec.ts e2e/a11y.spec.ts --reporter=line 2>&1 | tail -3)

log "ALL GREEN — safe to deploy."
