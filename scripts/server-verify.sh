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
# Diary cards (agent suggestions) are only offered when a bot token exists;
# the diary e2e needs one. Dummy value: nothing here talks to Telegram.
TELEGRAM_ENV=(TELEGRAM_BOT_TOKEN=e2e-dummy)
# Live Mistral tests (OCR/embed/extract/Voxtral/clinical) self-skip without
# MISTRAL_API_KEY. The key comes ONLY from an operator-private file, never
# from /opt/adelia (prod):  install -m 600 /dev/null ~/.config/godi/adelia-mistral.env
# and write MISTRAL_API_KEY=<dev key>. It always reaches the e2e api boot;
# it reaches pytest only with VERIFY_LIVE=1 (each run then costs real calls).
MISTRAL_ENV=()
MISTRAL_ENV_FILE="${HOME}/.config/godi/adelia-mistral.env"
if [[ -r "${MISTRAL_ENV_FILE}" ]]; then
  MISTRAL_ENV=("MISTRAL_API_KEY=$(sed -n 's/^MISTRAL_API_KEY=//p' "${MISTRAL_ENV_FILE}" | head -1)")
fi
PYTEST_LIVE_ENV=()
if [[ "${VERIFY_LIVE:-0}" == "1" && ${#MISTRAL_ENV[@]} -gt 0 ]]; then
  PYTEST_LIVE_ENV=("${MISTRAL_ENV[@]}")
fi

log() { printf '[verify] %s\n' "$*" >&2; }
# Kill by command pattern, not PID: `uv run`/`pnpm exec` wrappers orphan the
# real uvicorn/next-server child when only the parent PID is killed (learned
# from this script's own first run leaving both alive).
cleanup() {
  # By PORT, never by process name: name patterns miss the orphaned
  # next-server (its title is not in the cmdline) and could hit the OTHER
  # next apps this box runs (pm2 on :3001, prod in Docker). fuser -k kills
  # exactly whoever listens on OUR verify ports and nothing else.
  fuser -k "${API_PORT}/tcp" 2>/dev/null || true
  fuser -k "${WEB_PORT}/tcp" 2>/dev/null || true
  sleep 1
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

if [[ ${#PYTEST_LIVE_ENV[@]} -eq 0 ]]; then
  log "Backend suite (live Mistral tests skipped: no key or VERIFY_LIVE!=1)..."
else
  log "Backend suite (VERIFY_LIVE=1: live Mistral tests enabled)..."
fi
# -rs: show WHICH tests were skipped and why, so "N passed, 10 skipped" is
# never mistaken for full coverage.
(cd apps/api && env "${PG_ENV[@]}" "${S3_ENV[@]}" "${PYTEST_LIVE_ENV[@]}" AUTH_SECRET=ci-only-secret \
  uv run pytest -q -rs 2>&1 | grep -E "^SKIPPED|passed|failed|error" | tail -20)

# Colour system guards (cheap, text-only): the two dark blocks in globals.css
# must declare the same tokens, and every role pair must clear its WCAG
# threshold in BOTH schemes. Both fail in under a second, before the build.
log "Colour system (dark token sync + contrast in both schemes)..."
(cd apps/web && node scripts/check-dark-tokens.mjs && node scripts/check-contrast.mjs)

log "Web build..."
pnpm --filter @adelia/web build 2>&1 | grep -E "✓ Compiled|Error" | head -1

log "Booting api:${API_PORT} + web:${WEB_PORT} for e2e..."
cleanup
(cd apps/api && env "${PG_ENV[@]}" "${S3_ENV[@]}" "${MISTRAL_ENV[@]}" "${TELEGRAM_ENV[@]}" AUTH_SECRET=ci-only-secret \
  nohup uv run uvicorn adelia.main:app --port "${API_PORT}" >/tmp/verify-api.log 2>&1 & echo $! > /tmp/verify-api.pid)
for _ in $(seq 1 45); do curl -sf "localhost:${API_PORT}/health" >/dev/null && break; sleep 2; done
curl -sf "localhost:${API_PORT}/health" >/dev/null || { log "API never came up"; tail -5 /tmp/verify-api.log >&2; exit 1; }

(cd apps/web && env "${AUTH_ENV[@]}" \
  DATABASE_URL=postgresql://adelia:adelia_dev@localhost:5434/adelia \
  API_INTERNAL_URL="http://localhost:${API_PORT}" \
  nohup pnpm exec next start -p "${WEB_PORT}" >/tmp/verify-web.log 2>&1 & echo $! > /tmp/verify-web.pid)
for _ in $(seq 1 45); do curl -sf -o /dev/null "localhost:${WEB_PORT}/es" && break; sleep 2; done
curl -sf -o /dev/null "localhost:${WEB_PORT}/es" || { log "web never came up"; tail -5 /tmp/verify-web.log >&2; exit 1; }

# PWA surface (same assertions as deploy-prod.sh verify(), against the dev
# pair): sw.js is JavaScript, the manifest icons and the iOS startup image are
# PNGs, offline.html is the cached offline page, the manifest link and the
# startup images sit inside <head>, each locale serves its own manifest, and a
# dotted path does not render the home as a bogus locale.
log "PWA checks on :${WEB_PORT}..."
pwa_fail=0
check_type() { curl -s -o /dev/null -w '%{http_code} %{content_type}' --max-time 10 "$1" 2>/dev/null || printf '000 -'; }
res="$(check_type "localhost:${WEB_PORT}/sw.js")"
[[ "${res}" =~ ^200\ (application|text)/javascript ]] || { log "FAIL: /sw.js -> '${res}'"; pwa_fail=1; }
for path in /icons/icon-192.png /icons/icon-512.png /icons/icon-512-maskable.png /icons/apple-touch-icon.png /icons/splash/393x852@3x.png; do
  res="$(check_type "localhost:${WEB_PORT}${path}")"
  [[ "${res}" == "200 image/png" ]] || { log "FAIL: ${path} -> '${res}'"; pwa_fail=1; }
done
body="$(curl -s --max-time 10 "localhost:${WEB_PORT}/offline.html" || true)"
[[ "${body}" == *"Sin conexión"* ]] || { log "FAIL: /offline.html lacks 'Sin conexión'"; pwa_fail=1; }
body="$(curl -s --max-time 15 "localhost:${WEB_PORT}/es" || true)"
head_html="$(printf '%s' "${body}" | tr -d '\n' | sed 's#</head>.*##')"
[[ "${head_html}" == *'rel="manifest" href="/es/manifest.webmanifest"'* ]] || { log "FAIL: /es has no manifest link inside <head>"; pwa_fail=1; }
[[ "${head_html}" == *'apple-touch-startup-image'* ]] || { log "FAIL: /es has no apple-touch-startup-image inside <head>"; pwa_fail=1; }
# One manifest per language (app/[locale]/manifest.webmanifest/route.ts), the
# same installed app in the three (id "/"), texts in the page's language.
for l in es en fr; do
  res="$(check_type "localhost:${WEB_PORT}/${l}/manifest.webmanifest")"
  [[ "${res}" =~ ^200\ application/manifest\+json ]] || { log "FAIL: /${l}/manifest.webmanifest -> '${res}'"; pwa_fail=1; }
  body="$(curl -s --max-time 10 "localhost:${WEB_PORT}/${l}/manifest.webmanifest" || true)"
  [[ "${body}" == *"\"lang\":\"${l}\""* && "${body}" == *'"id":"/"'* ]] \
    || { log "FAIL: /${l}/manifest.webmanifest lacks lang=${l} or id=/"; pwa_fail=1; }
done
res="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "localhost:${WEB_PORT}/foo.txt" || true)"
[[ "${res}" == "404" ]] || { log "FAIL: /foo.txt -> ${res} (want 404)"; pwa_fail=1; }
# Build-id plumbing (next.config.ts): /api/version must report the id of the
# build that is being served, which is what the service worker is versioned by.
build_id="$(cat apps/web/.next/BUILD_ID 2>/dev/null || true)"
body="$(curl -s --max-time 10 "localhost:${WEB_PORT}/api/version" || true)"
[[ -n "${build_id}" && "${body}" == *"\"buildId\":\"${build_id}\""* ]] \
  || { log "FAIL: /api/version -> '${body}' (want buildId ${build_id:-<none>})"; pwa_fail=1; }
[[ "${pwa_fail}" -eq 0 ]] || { log "PWA checks FAILED"; exit 1; }
log "PWA checks OK."

log "E2E (recorder + a11y light&dark + theme + diary + showcase + landing + pwa service worker)..."
# One retry: a layout or focus assertion can lose a race under the full
# suite's parallel load, and a single flake must not block a deploy. A test
# that fails twice is a real failure and stops the script; flaky ones are
# named so they get fixed instead of tolerated. On failure the tail is long
# enough to carry the actual assertion (`tail -3` hid it, twice).
E2E_LOG=/tmp/verify-e2e.log
if (cd apps/web && env "${PG_ENV[@]}" AUTH_SECRET=ci-only-secret \
  E2E_BASE_URL="http://localhost:${WEB_PORT}" \
  pnpm exec playwright test e2e/consulta-record.spec.ts e2e/a11y.spec.ts e2e/theme.spec.ts e2e/diary.spec.ts e2e/showcase.spec.ts e2e/landing-day.spec.ts e2e/pwa-sw.spec.ts --retries=1 --reporter=line >"${E2E_LOG}" 2>&1); then
  tail -3 "${E2E_LOG}"
  grep -E "^\s+.\s+\[?flaky|flaky\b" "${E2E_LOG}" | head -5 || true
else
  log "E2E FAILED (full output in ${E2E_LOG} on the server):"
  tail -60 "${E2E_LOG}" >&2
  exit 1
fi

log "ALL GREEN — safe to deploy."
