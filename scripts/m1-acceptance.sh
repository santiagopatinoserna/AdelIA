#!/usr/bin/env bash
# M1 Acceptance Test — runs the headless smoke test.
# Requires: docker compose up + alembic upgrade head + AUTH_SECRET + MISTRAL_API_KEY in env.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

step() { echo -e "\n${YELLOW}▶ $1${NC}"; }
pass() { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; exit 1; }

step "1. Verify Docker stack is up"
if ! docker compose -f infra/docker-compose.dev.yml ps --status running | grep -q postgres; then
  fail "Postgres container not running. Run: pnpm dev:infra"
fi
if ! docker compose -f infra/docker-compose.dev.yml ps --status running | grep -q minio; then
  fail "MinIO container not running. Run: pnpm dev:infra"
fi
pass "Docker stack running"

step "2. Verify Postgres has pgvector extension and schema"
docker compose -f infra/docker-compose.dev.yml exec -T postgres \
  psql -U adelia -d adelia -tA \
  -c "SELECT extname FROM pg_extension WHERE extname='vector'" | grep -q vector \
  || fail "pgvector extension missing"
pass "pgvector extension installed"

docker compose -f infra/docker-compose.dev.yml exec -T postgres \
  psql -U adelia -d adelia -tA -c "\dt" | grep -q documents \
  || fail "documents table missing — run: uv --directory apps/api run alembic upgrade head"
pass "Schema applied (documents table present)"

step "3. Verify MinIO bucket is reachable"
curl -sf http://localhost:9000/minio/health/live > /dev/null \
  || fail "MinIO not reachable on :9000"
pass "MinIO healthy"

step "4. Verify AUTH_SECRET set"
if [[ -z "${AUTH_SECRET:-}" ]] && ! grep -q "AUTH_SECRET=.*[a-zA-Z0-9]" apps/api/.env 2>/dev/null; then
  fail "AUTH_SECRET not set in env or apps/api/.env"
fi
pass "AUTH_SECRET configured"

step "5. Verify MISTRAL_API_KEY set"
if [[ -z "${MISTRAL_API_KEY:-}" ]] && ! grep -q "MISTRAL_API_KEY=.*[a-zA-Z0-9]" apps/api/.env 2>/dev/null; then
  fail "MISTRAL_API_KEY not set in env or apps/api/.env. Live OCR test will skip."
fi
pass "MISTRAL_API_KEY configured (live OCR test will run)"

step "6. Run backend test suite"
pnpm test:api 2>&1 | tail -20
TEST_EXIT=${PIPESTATUS[0]}
if [[ $TEST_EXIT -eq 0 ]]; then
  pass "Backend tests passed (0 failures)"
else
  fail "Backend tests had failures or errors. Inspect output above."
fi

step "7. Verify frontend builds clean"
pnpm --filter @adelia/web typecheck > /dev/null 2>&1 || fail "Frontend typecheck failed"
pass "Frontend typecheck clean"

pnpm --filter @adelia/web build > /dev/null 2>&1 || fail "Frontend build failed"
pass "Frontend production build succeeds"

step "8. Verify all expected routes registered"
ROUTES_OUT=$(pnpm --filter @adelia/web build 2>&1)
for route in "/[locale]" "/[locale]/dashboard" "/[locale]/dashboard/upload" "/[locale]/dashboard/documents/\[id\]" "/[locale]/signin" "/api/auth/\[...nextauth\]"; do
  echo "$ROUTES_OUT" | grep -q "$route" || fail "Route missing: $route"
done
pass "All 6 expected routes registered"

echo -e "\n${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  M1 ACCEPTANCE — HEADLESS CHECKS PASS  ${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "Next: run docs/M1_ACCEPTANCE.md UI checklist manually in browser."
