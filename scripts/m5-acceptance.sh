#!/usr/bin/env bash
# M5 acceptance — headless backend E2E test.
# Requires: docker compose up (postgres + minio), MISTRAL_API_KEY + OPENAI_API_KEY in env.
# Usage: AUTH_SECRET=... MISTRAL_API_KEY=... OPENAI_API_KEY=... bash scripts/m5-acceptance.sh
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
EMAIL="m5-test-$(date +%s)@example.com"

echo "==> [1/6] Health check"
curl -fsS "${API_BASE}/health" | grep -q '"status":"ok"' || { echo "FAIL health"; exit 1; }

echo "==> [2/6] Mint JWT for test user (local mint — seeds user + signs with AUTH_SECRET)"
TOKEN=$(cd apps/api && uv run python scripts/mint_dev_jwt.py "${EMAIL}")
[ -n "${TOKEN}" ] || { echo "FAIL JWT mint"; exit 1; }

echo "==> [3/6] Upload a clinical doc"
FIXTURE="${FIXTURE:-apps/api/tests/fixtures/sample-lab-result.pdf}"
[ -f "${FIXTURE}" ] || { echo "FAIL fixture missing: ${FIXTURE}"; exit 1; }
DOC_ID=$(curl -fsS -X POST "${API_BASE}/documents" \
    -H "Authorization: Bearer ${TOKEN}" \
    -F "file=@${FIXTURE}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
[ -n "${DOC_ID}" ] || { echo "FAIL upload"; exit 1; }
echo "    doc_id=${DOC_ID}"

echo "==> [4/6] Wait for doc processing (max 60s)"
STATUS="wait"
for i in $(seq 1 60); do
    STATUS=$(curl -fsS "${API_BASE}/documents/${DOC_ID}" \
        -H "Authorization: Bearer ${TOKEN}" \
        | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('processed_at') and 'done' or 'wait')")
    [ "${STATUS}" = "done" ] && { echo "    doc processed in ${i}s"; break; }
    sleep 1
done
[ "${STATUS}" = "done" ] || { echo "FAIL doc processing timeout"; exit 1; }

echo "==> [5/6] POST briefing endocrinology"
BRIEFING_ID=$(curl -fsS -X POST "${API_BASE}/briefings" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"target_specialty":"endocrinology"}' \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
[ -n "${BRIEFING_ID}" ] || { echo "FAIL briefing POST"; exit 1; }
echo "    briefing_id=${BRIEFING_ID}"

echo "==> [6/6] Poll briefing until ready (max 90s)"
for i in $(seq 1 90); do
    BODY=$(curl -fsS "${API_BASE}/briefings/${BRIEFING_ID}" -H "Authorization: Bearer ${TOKEN}")
    BSTATUS=$(echo "${BODY}" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
    if [ "${BSTATUS}" = "ready" ]; then
        echo "    ready in ${i}s"
        BODY="${BODY}" python3 <<'PY'
import json, os
data = json.loads(os.environ["BODY"])
assert data["status"] == "ready", f"expected ready, got {data['status']}"
payload = data["payload"]
assert payload is not None, "payload is None"
assert "sections" in payload
sections = payload["sections"]
for key in ["active_problems", "medications", "allergies", "procedures", "relevant_observations", "open_questions"]:
    assert key in sections, f"missing section {key}"
qa = sections["open_questions"]
assert 0 <= len(qa) <= 5, f"open_questions count out of range: {len(qa)}"
print(f"OK — briefing payload has {len(qa)} open_questions, allergies={sections['allergies']!r}")
PY
        echo ""
        echo "✅ M5 acceptance passed"
        exit 0
    fi
    if [ "${BSTATUS}" = "failed" ]; then
        echo "FAIL briefing generation: $(echo "${BODY}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("error_message","?"))')"
        exit 1
    fi
    sleep 1
done
echo "FAIL polling timeout"
exit 1
