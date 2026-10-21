#!/usr/bin/env bash
# Deploy AdelIA to the home-server prod instance.
#
# The server's IP is assigned by DHCP and changes across reboots (no router
# access to reserve one). Instead of hardcoding an IP, this script discovers
# the server each run: env override -> known recent IPs -> a short LAN scan.
# mDNS (the server's .local hostname) does NOT resolve on this network, so that's not
# an option.
#
# Usage:
#   ./scripts/deploy-prod.sh              # rebuild api + web (default)
#   ./scripts/deploy-prod.sh api          # rebuild only api
#   ADELIA_HOST=192.168.1.x ./scripts/deploy-prod.sh   # force the host
#   ./scripts/deploy-prod.sh --discover-only   # just find the host, no
#                                               # sync/build/deploy - safe
#                                               # to run standalone to test
#                                               # discovery in isolation
#   ./scripts/deploy-prod.sh --allow-dirty      # EMERGENCY ONLY: skip the
#                                               # clean-tree/pushed-HEAD gate
#   ./scripts/deploy-prod.sh --skip-golden      # EMERGENCY ONLY: skip the
#                                               # clinical golden-set gate
#
# Steps: check working tree -> golden set (clinical gate) -> discover host ->
# rsync code (no --delete) ->
# docker compose up -d --build -> verify (HTTP 200s + alembic version) ->
# summary.
#
# What rsync sends is the WORKING TREE, not a commit. So the gate below
# refuses to deploy unless `git status --porcelain` is empty and HEAD is the
# same commit as origin/main: otherwise production runs code that exists on
# no branch, that nobody can review, and that no CI run ever tested. Use
# --allow-dirty only for a fire, and write down afterwards what was shipped.
#
# Must be run via `./scripts/deploy-prod.sh` (or `bash scripts/deploy-prod.sh`)
# so the shebang starts a real bash process — do NOT `source` this file from
# a non-bash shell (e.g. zsh): BASH_SOURCE/local-array semantics differ and
# discovery paths can silently miscompute.
#
# Secrets: this script never reads, copies, or prints .env.prod. The
# server's own .env.prod (already on disk at /opt/adelia) is what
# `docker compose --env-file .env.prod` uses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REMOTE_USER="santiago"
REMOTE_DIR="/opt/adelia"

# Known recent IPs, tried before falling back to a subnet scan.
KNOWN_HOSTS=(192.168.1.150 192.168.1.155)
SUBNET_PREFIX="192.168.1"
SCAN_RANGE_START=140
SCAN_RANGE_END=160

# Short timeout for probing many candidates quickly.
PROBE_SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new)
# Longer timeout for the actual work once the host is known. accept-new is
# required here too: a new IP means a known_hosts entry doesn't exist yet,
# and BatchMode=yes alone would refuse to prompt and just fail.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

log() { printf '[deploy] %s\n' "$*" >&2; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. Discover the host ---------------------------------------------

probe_host() {
  local ip="$1"
  ssh "${PROBE_SSH_OPTS[@]}" "${REMOTE_USER}@${ip}" "test -d ${REMOTE_DIR}" >/dev/null 2>&1
}

discover_host() {
  local ip known skip

  if [[ -n "${ADELIA_HOST:-}" ]]; then
    log "Trying \$ADELIA_HOST=${ADELIA_HOST}..."
    if probe_host "${ADELIA_HOST}"; then
      log "  -> reachable, using it"
      printf '%s\n' "${ADELIA_HOST}"
      return 0
    fi
    log "  -> \$ADELIA_HOST unreachable or missing ${REMOTE_DIR}, falling back to autodiscovery"
  fi

  log "Trying known candidates: ${KNOWN_HOSTS[*]}"
  for ip in "${KNOWN_HOSTS[@]}"; do
    log "  probing ${ip}..."
    if probe_host "${ip}"; then
      log "  -> found server at ${ip}"
      printf '%s\n' "${ip}"
      return 0
    fi
  done

  log "Known candidates unreachable — scanning ${SUBNET_PREFIX}.${SCAN_RANGE_START}-${SCAN_RANGE_END}..."
  for ((last = SCAN_RANGE_START; last <= SCAN_RANGE_END; last++)); do
    ip="${SUBNET_PREFIX}.${last}"
    skip=0
    for known in "${KNOWN_HOSTS[@]}"; do
      [[ "${ip}" == "${known}" ]] && skip=1
    done
    [[ "${skip}" -eq 1 ]] && continue
    log "  probing ${ip}..."
    if probe_host "${ip}"; then
      log "  -> found server at ${ip}"
      printf '%s\n' "${ip}"
      return 0
    fi
  done

  return 1
}

no_host_found_message() {
  cat >&2 <<EOF
[deploy] ERROR: could not find the AdelIA server on ${SUBNET_PREFIX}.0/24.

Tried, in order:
  1. \$ADELIA_HOST          (not set, or unreachable)
  2. known IPs:             ${KNOWN_HOSTS[*]}
  3. scan:                  ${SUBNET_PREFIX}.${SCAN_RANGE_START}-${SCAN_RANGE_END}

Find it by hand (run on the same LAN, after pinging the subnet or waking
the machine):
  arp -a | grep -i <server-hostname>

Then force it for this run (and optionally export it in your shell so
future deploys skip discovery entirely):
  ADELIA_HOST=x.x.x.x ./scripts/deploy-prod.sh
EOF
  exit 1
}

# --- 1b. Refuse to deploy anything that is not exactly origin/main --------

# rsync ships the working tree. A dirty tree or an unpushed HEAD means the
# bytes about to run in production are not the bytes anyone reviewed or
# tested. Bypass with --allow-dirty, deliberately and out loud.
check_tree_is_deployable() {
  local allow_dirty="$1"
  local dirty head remote fetch_ok=1

  # `|| true`: outside a git checkout this must reach the explicit error
  # below, not die on set -e with no explanation.
  dirty="$(git -C "${REPO_ROOT}" status --porcelain 2>/dev/null || true)"

  # A stale origin/main would make the comparison meaningless, so refresh it.
  # A failed fetch (no network, no credentials) is not fatal: it downgrades
  # the check to the last known origin/main and says so.
  if ! git -C "${REPO_ROOT}" fetch --quiet origin main 2>/dev/null; then
    fetch_ok=0
  fi

  head="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
  remote="$(git -C "${REPO_ROOT}" rev-parse refs/remotes/origin/main 2>/dev/null || true)"

  if [[ "${fetch_ok}" -eq 0 ]]; then
    log "WARNING: could not fetch origin/main; comparing against the local copy of it."
  fi

  if [[ -z "${dirty}" && -n "${head}" && "${head}" == "${remote}" ]]; then
    log "Working tree clean and HEAD == origin/main (${head:0:8})."
    return 0
  fi

  if [[ "${allow_dirty}" -eq 1 ]]; then
    log "WARNING: --allow-dirty. Deploying a tree that is NOT origin/main."
    [[ -n "${dirty}" ]] && log "WARNING:   uncommitted changes: $(printf '%s\n' "${dirty}" | wc -l | tr -d ' ') file(s)"
    [[ "${head}" != "${remote}" ]] && log "WARNING:   HEAD ${head:0:8} != origin/main ${remote:0:8}"
    log "WARNING: write down what you shipped, and push it as soon as the fire is out."
    return 0
  fi

  {
    printf '[deploy] ERROR: refusing to deploy: the working tree is not origin/main.\n\n'
    if [[ -n "${dirty}" ]]; then
      printf '  Uncommitted changes (git status --porcelain):\n'
      printf '%s\n' "${dirty}" | sed 's/^/    /' | head -20
      printf '\n'
    fi
    if [[ -z "${remote}" ]]; then
      printf '  origin/main is unknown locally (no refs/remotes/origin/main).\n\n'
    elif [[ "${head}" != "${remote}" ]]; then
      printf '  HEAD        %s\n' "${head:-<none>}"
      printf '  origin/main %s\n\n' "${remote}"
    fi
    printf '  rsync sends the working tree, so this would put code in production\n'
    printf '  that no commit contains and no CI run ever tested.\n\n'
    printf '  Fix it:      git add -A && git commit && git push origin main\n'
    printf '  Emergency:   ./scripts/deploy-prod.sh --allow-dirty\n'
  } >&2
  exit 1
}

# --- 1c. The clinical gate: the golden set (audit 3.2) --------------------
#
# Fifteen questions in three groups (adelia/clinical/golden.py). The deploy
# stops if recall@4 in group A is below 0.8, if the refusal rate in group B
# is not 1.0, if any orphan citation appears, or if a single red flag of
# group C fails to fire.
#
# Group C needs neither a key nor a database, so this gate always has teeth:
# it is the part that protects against the audit's risk 1 (a baby harmed by
# an answer that looks sourced and is not). Groups A and B need embeddings
# and a loaded corpus; when they cannot run, the test says so, the report
# records "no ejecutado", and the deploy continues with a warning rather than
# a green tick that means nothing. Bypass with --skip-golden, out loud.
run_golden_gate() {
  local skip="$1"
  if [[ "${skip}" -eq 1 ]]; then
    log "WARNING: --skip-golden. Deploying without the clinical gate."
    return 0
  fi
  if ! command -v uv >/dev/null 2>&1; then
    log "WARNING: uv not found; the golden set did not run."
    return 0
  fi
  log "Golden set (clinical gate)..."
  if ( cd "${REPO_ROOT}/apps/api" && uv run pytest -q tests/test_rag_golden.py -rs ); then
    if [[ -f "${REPO_ROOT}/apps/api/golden_report.json" ]]; then
      sed 's/^/[deploy]   /' "${REPO_ROOT}/apps/api/golden_report.json"
    fi
    return 0
  fi
  {
    printf '[deploy] ERROR: the golden set failed. Not deploying.\n\n'
    printf '  See apps/api/golden_report.json for recall@4, the refusal rate,\n'
    printf '  orphan citations and which questions missed.\n\n'
    printf '  Bypass (deliberately, and write down why): ./scripts/deploy-prod.sh --skip-golden\n'
  } >&2
  exit 1
}

# --- 2. Sync code
#
# Two passes on purpose. The root pass never deletes, because /opt/adelia
# holds files that are not in the repo and must survive (.env.prod, the
# legacy Caddy files, deploy logs). The source directories, which have to
# mirror the commit exactly, are synced WITH --delete: without it a file
# deleted or moved in git lived on forever on the server, and on 31-ago-2026
# that shipped a build failure (the dashboard sections moved into a (paid)
# route group and Next found both the old and the new path). Excluded paths
# are protected from --delete by rsync unless --delete-excluded is passed,
# so node_modules and .next stay put.
MIRRORED_DIRS=(apps scripts infra docs)

sync_code() {
  local host="$1"
  log "Syncing repo -> ${REMOTE_USER}@${host}:${REMOTE_DIR}/ (root: no --delete)"
  rsync -az --human-readable \
    -e "ssh ${SSH_OPTS[*]}" \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='minio-data' \
    --exclude='postgres-data' \
    --exclude='.superpowers' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='.pytest_cache' \
    --exclude='.env.prod' \
    "${REPO_ROOT}/" "${REMOTE_USER}@${host}:${REMOTE_DIR}/"

  local dir
  for dir in "${MIRRORED_DIRS[@]}"; do
    [[ -d "${REPO_ROOT}/${dir}" ]] || continue
    log "Mirroring ${dir}/ (--delete: removals in git reach the server)"
    rsync -az --human-readable --delete \
      -e "ssh ${SSH_OPTS[*]}" \
      --exclude='node_modules' \
      --exclude='.next' \
      --exclude='__pycache__' \
      --exclude='.venv' \
      --exclude='.pytest_cache' \
      --exclude='qa-shots' \
      "${REPO_ROOT}/${dir}/" "${REMOTE_USER}@${host}:${REMOTE_DIR}/${dir}/"
  done
  log "Sync done."
}

# --- 3. Rebuild containers ----------------------------------------------

rebuild() {
  local host="$1" services="$2"
  log "Rebuilding containers on ${host}: ${services}"
  ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${host}" \
    "cd ${REMOTE_DIR} && docker compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d --build ${services}"
  log "Rebuild done."
}

# --- 4. Verify ------------------------------------------------------------

# Expected alembic head, derived from the migration files in this repo
# (the revision that is nobody's down_revision).
expected_alembic_head() {
  local versions_dir="${REPO_ROOT}/apps/api/alembic/versions"
  local revisions down_revisions head

  revisions=$(grep -hoE '^revision:.*=[[:space:]]*"[^"]+"' "${versions_dir}"/*.py 2>/dev/null \
    | sed -E 's/.*"([^"]+)".*/\1/' | sort -u || true)
  down_revisions=$(grep -hoE '^down_revision:.*=[[:space:]]*"[^"]+"' "${versions_dir}"/*.py 2>/dev/null \
    | sed -E 's/.*"([^"]+)".*/\1/' | sort -u || true)

  if [[ -z "${revisions}" ]]; then
    die "Could not read any alembic revisions from ${versions_dir}"
  fi

  head=$(comm -23 <(printf '%s\n' "${revisions}") <(printf '%s\n' "${down_revisions}") || true)

  if [[ -z "${head}" || "$(printf '%s\n' "${head}" | wc -l | tr -d ' ')" != "1" ]]; then
    die "Could not determine a single alembic head in ${versions_dir} (candidates: ${head:-none})"
  fi
  printf '%s\n' "${head}"
}

check_url() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || printf '000'
}

# "<status> <content-type>" of a URL, e.g. "200 image/png".
check_url_type() {
  curl -s -o /dev/null -w '%{http_code} %{content_type}' --max-time 10 "$1" 2>/dev/null || printf '000 -'
}

# PWA surface. A regression here is silent in the browser (no console error,
# the app just stops being installable), so it is asserted on every deploy:
#  - /sw.js must be real JavaScript (a missing public/ made it the HTML home)
#  - the icons the manifest points to and the iOS startup image must be PNGs
#  - /offline.html is the page the service worker caches for offline
#  - the manifest link and the startup images must sit INSIDE <head> (Next
#    streams `metadata` into the body; Chrome ignores a manifest link that is
#    not in <head>)
#  - each locale serves its own manifest (same app: id "/", lang = locale)
# Prints "FAIL: ..." lines and returns 1 when anything is off.
check_pwa() {
  local base="$1" fail=0 res body head_html
  for path in /sw.js; do
    res="$(check_url_type "${base}${path}")"
    [[ "${res}" =~ ^200\ (application|text)/javascript ]] \
      || { log "FAIL: GET ${path} -> '${res}' (want 200 application/javascript)"; fail=1; }
  done
  for path in /icons/icon-192.png /icons/icon-512.png /icons/icon-512-maskable.png /icons/apple-touch-icon.png /icons/splash/393x852@3x.png; do
    res="$(check_url_type "${base}${path}")"
    [[ "${res}" == "200 image/png" ]] \
      || { log "FAIL: GET ${path} -> '${res}' (want 200 image/png)"; fail=1; }
  done
  body="$(curl -s --max-time 10 "${base}/offline.html" 2>/dev/null || true)"
  [[ "${body}" == *"Sin conexión"* ]] \
    || { log "FAIL: GET /offline.html does not contain 'Sin conexión'"; fail=1; }
  body="$(curl -s --max-time 15 "${base}/es" 2>/dev/null || true)"
  head_html="$(printf '%s' "${body}" | tr -d '\n' | sed 's#</head>.*##')"
  [[ "${head_html}" == *'rel="manifest" href="/es/manifest.webmanifest"'* ]] \
    || { log "FAIL: GET /es has no <link rel=\"manifest\"> inside <head>"; fail=1; }
  [[ "${head_html}" == *'apple-touch-startup-image'* ]] \
    || { log "FAIL: GET /es has no apple-touch-startup-image inside <head>"; fail=1; }
  local l
  for l in es en fr; do
    res="$(check_url_type "${base}/${l}/manifest.webmanifest")"
    [[ "${res}" =~ ^200\ application/manifest\+json ]] \
      || { log "FAIL: GET /${l}/manifest.webmanifest -> '${res}'"; fail=1; }
    body="$(curl -s --max-time 10 "${base}/${l}/manifest.webmanifest" 2>/dev/null || true)"
    [[ "${body}" == *"\"lang\":\"${l}\""* && "${body}" == *'"id":"/"'* ]] \
      || { log "FAIL: GET /${l}/manifest.webmanifest lacks lang=${l} or id=/"; fail=1; }
  done
  return "${fail}"
}

# A freshly recreated web container needs a few seconds before Next serves
# traffic; checking immediately after `up -d` reports a 502 that resolves on
# its own. Poll instead of crying wolf.
WAIT_FOR_HTTP_ATTEMPTS=12
WAIT_FOR_HTTP_DELAY=5

wait_for_url() {
  local url="$1" code=""
  for ((attempt = 1; attempt <= WAIT_FOR_HTTP_ATTEMPTS; attempt++)); do
    code="$(check_url "${url}")"
    [[ "${code}" == "200" ]] && { printf '%s\n' "${code}"; return 0; }
    log "  ${url} -> ${code}, retry ${attempt}/${WAIT_FOR_HTTP_ATTEMPTS} in ${WAIT_FOR_HTTP_DELAY}s"
    sleep "${WAIT_FOR_HTTP_DELAY}"
  done
  printf '%s\n' "${code}"
  return 1
}

verify() {
  local host="$1" services="$2"
  log "Verifying deployment..."

  local code_home code_demo code_prof code_priv code_terms code_txt db_version expected fail=0
  local pwa_status="OK"

  code_home=$(wait_for_url "https://adelia.godi.ai/es") || true
  # The landing now hosts the demo. Its old URL must redirect to /es.
  code_demo=$(check_url "https://adelia.godi.ai/es/demo")
  local demo_target
  demo_target=$(curl -sS --max-time 20 -o /dev/null -w '%{redirect_url}' \
    "https://adelia.godi.ai/es/demo" 2>/dev/null || true)
  code_prof=$(check_url "https://adelia.godi.ai/es/profesionales")
  code_priv=$(check_url "https://adelia.godi.ai/es/privacidad")
  code_terms=$(check_url "https://adelia.godi.ai/es/terminos")
  # Locale guard: a dotted path must not render the home as a fake locale.
  code_txt=$(check_url "https://adelia.godi.ai/foo.txt")
  check_pwa "https://adelia.godi.ai" || pwa_status="FAIL"

  db_version=$(ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${host}" \
    'docker exec infra-postgres-1 psql -U adelia -d adelia -t -c "select version_num from alembic_version;"' \
    2>/dev/null | tr -d '[:space:]' || true)
  expected=$(expected_alembic_head)

  [[ "${code_home}" == "200" ]] || { log "FAIL: GET /es -> ${code_home}"; fail=1; }
  # /es/demo redirects to /es since the landing IS the demo (2026-10-21):
  # 307 is the correct answer there. A 200 would mean the redirect is gone.
  [[ "${code_demo}" == "307" || "${code_demo}" == "308" ]] \
    || { log "FAIL: GET /es/demo -> ${code_demo} (want a 307/308 redirect to /es)"; fail=1; }
  [[ "${demo_target}" == "https://adelia.godi.ai/es" ]] \
    || { log "FAIL: /es/demo redirects to '${demo_target}', expected /es"; fail=1; }
  [[ "${code_prof}" == "200" ]] || { log "FAIL: GET /es/profesionales -> ${code_prof}"; fail=1; }
  [[ "${code_priv}" == "200" ]] || { log "FAIL: GET /es/privacidad -> ${code_priv}"; fail=1; }
  [[ "${code_terms}" == "200" ]] || { log "FAIL: GET /es/terminos -> ${code_terms}"; fail=1; }
  [[ "${code_txt}" == "404" ]] || { log "FAIL: GET /foo.txt -> ${code_txt} (want 404)"; fail=1; }
  [[ "${pwa_status}" == "OK" ]] || { log "FAIL: PWA checks (sw.js, icons, offline.html, manifest in <head>)"; fail=1; }
  [[ "${db_version}" == "${expected}" ]] || { log "FAIL: alembic_version='${db_version}' expected='${expected}'"; fail=1; }

  cat >&2 <<EOF

================= AdelIA deploy summary =================
Server:                 ${REMOTE_USER}@${host}
Services rebuilt:       ${services}
GET /es:                ${code_home}
GET /es/demo:           ${code_demo}
GET /es/profesionales:  ${code_prof}
GET /es/privacidad:     ${code_priv}
GET /es/terminos:       ${code_terms}
GET /foo.txt:           ${code_txt} (expected: 404)
PWA (sw/icons/offline): ${pwa_status}
Alembic version:        ${db_version:-<empty>} (expected: ${expected})
===========================================================
EOF

  if [[ "${fail}" -ne 0 ]]; then
    die "Deployment verification FAILED — see summary above."
  fi
  log "Deployment verified OK."
}

# --- main -------------------------------------------------------------

# Argument parsing, extracted so scripts/test-deploy-args.sh can source this
# file and exercise it without deploying anything. Sets three globals:
# DISCOVER_ONLY, ALLOW_DIRTY and REQUESTED_SERVICES.
#
# Flags are accepted ANYWHERE, before or after the service list. The loop used
# to stop at the first non-flag, so `deploy-prod.sh api --allow-dirty` silently
# became a compose service literally named "--allow-dirty": with a clean tree
# it passed the gate, rsynced the tree to /opt/adelia and only then failed on
# the server, leaving new code beside stale containers; with a dirty tree it
# refused, so the operator reaching for the emergency flag in a fire got the
# abort message instead of the deploy.
parse_args() {
  DISCOVER_ONLY=0
  ALLOW_DIRTY=0
  SKIP_GOLDEN=0
  local -a service_args=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --discover-only) DISCOVER_ONLY=1 ;;
      --allow-dirty) ALLOW_DIRTY=1 ;;
      --skip-golden) SKIP_GOLDEN=1 ;;
      --*) die "unknown flag: $1 (known: --discover-only, --allow-dirty, --skip-golden)" ;;
      *) service_args+=("$1") ;;
    esac
    shift
  done

  # Accept both `deploy-prod.sh "api web"` and `deploy-prod.sh api web`.
  REQUESTED_SERVICES="${service_args[*]:-api web}"
}

main() {
  parse_args "$@"
  local discover_only="${DISCOVER_ONLY}"
  local allow_dirty="${ALLOW_DIRTY}"
  local skip_golden="${SKIP_GOLDEN}"
  local requested_services="${REQUESTED_SERVICES}"
  local host

  log "==> AdelIA prod deploy"

  # Before anything reaches the server, and before the LAN scan wastes a
  # minute: is this tree even deployable?
  if [[ "${discover_only}" -eq 0 ]]; then
    check_tree_is_deployable "${allow_dirty}"
    run_golden_gate "${skip_golden}"
  fi

  if host="$(discover_host)"; then
    log "Server: ${REMOTE_USER}@${host}"
  else
    no_host_found_message
  fi

  if [[ "${discover_only}" -eq 1 ]]; then
    log "--discover-only: stopping before sync/build/deploy."
    printf '%s\n' "${host}"
    exit 0
  fi

  sync_code "${host}"
  rebuild "${host}" "${requested_services}"
  verify "${host}" "${requested_services}"
}

# Sourced by scripts/test-deploy-args.sh, which wants parse_args and nothing
# else to happen.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
