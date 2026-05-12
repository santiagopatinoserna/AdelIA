#!/usr/bin/env bash
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

step "1. M2 prerequisites"
if [[ ! -f scripts/m2-acceptance.sh ]]; then
  fail "M2 acceptance script missing — run M2 first"
fi
pass "M2 acceptance script present"

step "2. New M3 imports resolve"
cd apps/api
uv run python -c "
from adelia.services.temporal import detect_temporal_intent
from adelia.services.structured_query import query_observations_by_name_and_date_range
from adelia.services.retrieval import retrieve_relevant_chunks
from adelia.services.chat_repo import (
    create_session, list_sessions, get_session_with_messages,
    persist_message, delete_session,
)
from adelia.services.chat_orchestrator import answer_question_streaming, ChatEvent
from adelia.routers.chat import router as chat_router
print('OK')
" || fail "M3 module imports failed"
pass "All M3 services + router importable"

step "3. Temporal + orchestrator unit tests (no API)"
uv run pytest tests/test_temporal.py tests/test_chat_orchestrator.py -v 2>&1 | tail -15
TEST_EXIT=${PIPESTATUS[0]}
[[ $TEST_EXIT -eq 0 ]] || fail "Temporal/orchestrator tests failed"
pass "Temporal + orchestrator unit tests passed (11+)"

step "4. Full backend test suite (gated tests run live if keys + PG up)"
uv run pytest tests/ -v 2>&1 | tail -30
TEST_EXIT=${PIPESTATUS[0]}
[[ $TEST_EXIT -eq 0 ]] || fail "Backend tests had failures"
pass "Backend tests passed"

cd "$ROOT"

step "5. Frontend builds clean with new chat route"
pnpm --filter @adelia/web typecheck > /dev/null 2>&1 || fail "Frontend typecheck failed"
pnpm --filter @adelia/web build > /dev/null 2>&1 || fail "Frontend build failed"
pass "Frontend typecheck + build clean"

echo -e "\n${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  M3 ACCEPTANCE — HEADLESS CHECKS PASS  ${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "Next: run docs/M3_ACCEPTANCE.md UI checklist (chat + citations + sessions)."
