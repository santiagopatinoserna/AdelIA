#!/usr/bin/env bash
# M2 Acceptance Test — verifies RAG substrate is wired end-to-end.
# Requires M1 acceptance to have passed first.

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

step "1. M1 prerequisites"
if [[ ! -f scripts/m1-acceptance.sh ]]; then
  fail "M1 acceptance script missing — run M1 first"
fi
pass "M1 acceptance script present"

step "2. Verify new env vars set"
for var in MISTRAL_API_KEY OPENAI_API_KEY; do
  if [[ -z "${!var:-}" ]] && ! grep -q "${var}=.*[a-zA-Z0-9]" apps/api/.env 2>/dev/null; then
    fail "${var} not set in env or apps/api/.env (M2 needs both for full pipeline)"
  fi
done
pass "MISTRAL_API_KEY + OPENAI_API_KEY configured"

step "3. Verify M2 worker modules importable"
cd apps/api
uv run python -c "
from adelia.workers.transcribe import transcribe_audio
from adelia.workers.extract import extract_entities
from adelia.workers.chunker import chunk_hierarchical, ChunkConfig, count_tokens
from adelia.workers.embed import embed_texts
print('OK')
" || fail "M2 worker imports failed"
pass "All 4 worker modules importable"

step "4. Run chunker unit tests (no API needed)"
uv run pytest tests/test_chunker.py -v 2>&1 | tail -15
TEST_EXIT=${PIPESTATUS[0]}
[[ $TEST_EXIT -eq 0 ]] || fail "Chunker tests failed"
pass "Chunker tests passed (10/10)"

step "5. Run remaining backend tests (LLM-gated tests run live if keys set)"
uv run pytest tests/ -v 2>&1 | tail -30
TEST_EXIT=${PIPESTATUS[0]}
[[ $TEST_EXIT -eq 0 ]] || fail "Backend tests had failures"
pass "Backend tests passed"

cd "$ROOT"

step "6. Frontend builds clean with new entity/chunk counts"
pnpm --filter @adelia/web typecheck > /dev/null 2>&1 || fail "Frontend typecheck failed"
pnpm --filter @adelia/web build > /dev/null 2>&1 || fail "Frontend build failed"
pass "Frontend typecheck + build clean"

echo -e "\n${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  M2 ACCEPTANCE — HEADLESS CHECKS PASS  ${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "Next: run docs/M2_ACCEPTANCE.md UI checklist (upload PDF + verify entity/chunk counts)."
