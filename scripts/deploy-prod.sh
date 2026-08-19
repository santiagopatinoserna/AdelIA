#!/usr/bin/env bash
# Deploy AdelIA to the home-server prod instance.
#
# The server's IP is assigned by DHCP and changes across reboots (no router
# access to reserve one). Instead of hardcoding an IP, this script discovers
# the server each run: env override -> known recent IPs -> a short LAN scan.
# mDNS (santiago-mp80.local) does NOT resolve on this network, so that's not
# an option.
#
# Usage:
#   ./scripts/deploy-prod.sh              # rebuild api + web (default)
#   ./scripts/deploy-prod.sh api          # rebuild only api
#   ADELIA_HOST=192.168.1.x ./scripts/deploy-prod.sh   # force the host
#   ./scripts/deploy-prod.sh --discover-only   # just find the host, no
#                                               # sync/build/deploy — safe
#                                               # to run standalone to test
#                                               # discovery in isolation
#
# Steps: discover host -> rsync code (no --delete) -> docker compose
# up -d --build -> verify (HTTP 200s + alembic version) -> summary.
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
  arp -a | grep -i santiago

Then force it for this run (and optionally export it in your shell so
future deploys skip discovery entirely):
  ADELIA_HOST=x.x.x.x ./scripts/deploy-prod.sh
EOF
  exit 1
}

# --- 2. Sync code (rsync, never --delete: server has its own .env.prod etc.)

sync_code() {
  local host="$1"
  log "Syncing repo -> ${REMOTE_USER}@${host}:${REMOTE_DIR}/ (rsync, no --delete)"
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

verify() {
  local host="$1" services="$2"
  log "Verifying deployment..."

  local code_home code_prof db_version expected fail=0

  code_home=$(check_url "https://adelia.godi.ai/es")
  code_prof=$(check_url "https://adelia.godi.ai/es/profesionales")

  db_version=$(ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${host}" \
    'docker exec infra-postgres-1 psql -U adelia -d adelia -t -c "select version_num from alembic_version;"' \
    2>/dev/null | tr -d '[:space:]' || true)
  expected=$(expected_alembic_head)

  [[ "${code_home}" == "200" ]] || { log "FAIL: GET /es -> ${code_home}"; fail=1; }
  [[ "${code_prof}" == "200" ]] || { log "FAIL: GET /es/profesionales -> ${code_prof}"; fail=1; }
  [[ "${db_version}" == "${expected}" ]] || { log "FAIL: alembic_version='${db_version}' expected='${expected}'"; fail=1; }

  cat >&2 <<EOF

================= AdelIA deploy summary =================
Server:                 ${REMOTE_USER}@${host}
Services rebuilt:       ${services}
GET /es:                ${code_home}
GET /es/profesionales:  ${code_prof}
Alembic version:        ${db_version:-<empty>} (expected: ${expected})
===========================================================
EOF

  if [[ "${fail}" -ne 0 ]]; then
    die "Deployment verification FAILED — see summary above."
  fi
  log "Deployment verified OK."
}

# --- main -------------------------------------------------------------

main() {
  local discover_only=0
  if [[ "${1:-}" == "--discover-only" ]]; then
    discover_only=1
    shift
  fi

  local requested_services="${1:-api web}"
  local host

  log "==> AdelIA prod deploy"

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

main "$@"
