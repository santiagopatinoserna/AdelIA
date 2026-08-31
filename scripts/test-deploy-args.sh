#!/usr/bin/env bash
# Regression test for deploy-prod.sh's argument parsing.
#
# `./scripts/deploy-prod.sh api --allow-dirty` used to hand "--allow-dirty" to
# `docker compose up -d --build` as if it were a service name: the flag loop
# stopped at the first non-flag. On a clean tree that passed the gate, rsynced
# the working tree to /opt/adelia and only then failed on the server, leaving
# new code beside stale containers. On a dirty tree it refused — so the one
# situation the flag exists for, an operator typing it in a fire, was exactly
# the one where it did nothing.
#
# Sources deploy-prod.sh (guarded, so main never runs) and calls parse_args.
# Run: bash scripts/test-deploy-args.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fails=0

expect() {
  local label="$1" want="$2" got="$3"
  if [[ "${want}" == "${got}" ]]; then
    printf '  ok   %s\n' "${label}"
  else
    printf '  FAIL %s\n       want: %s\n       got:  %s\n' "${label}" "${want}" "${got}"
    fails=$((fails + 1))
  fi
}

# Each case runs in its own subshell: die() exits, and a shared shell would
# take the whole test run with it.
run_case() {
  (
    # shellcheck source=/dev/null
    source "${SCRIPT_DIR}/deploy-prod.sh"
    parse_args "$@"
    printf 'discover=%s dirty=%s services=%s\n' \
      "${DISCOVER_ONLY}" "${ALLOW_DIRTY}" "${REQUESTED_SERVICES}"
  ) 2>/dev/null
}

echo "deploy-prod.sh parse_args"
expect "flag AFTER the service list is a flag, not a service" \
  "discover=0 dirty=1 services=api" "$(run_case api --allow-dirty)"
expect "flag before the service list still works" \
  "discover=0 dirty=1 services=api" "$(run_case --allow-dirty api)"
expect "two services, no flags" \
  "discover=0 dirty=0 services=api web" "$(run_case api web)"
expect "one quoted argument holding both services" \
  "discover=0 dirty=0 services=api web" "$(run_case "api web")"
expect "no arguments falls back to api web" \
  "discover=0 dirty=0 services=api web" "$(run_case)"
expect "--discover-only anywhere" \
  "discover=1 dirty=1 services=web" "$(run_case web --discover-only --allow-dirty)"

# An unknown flag must abort, wherever it sits, before anything is synced.
out="$(run_case api --bogus)"
expect "unknown flag after a service aborts" "" "${out}"
if (source "${SCRIPT_DIR}/deploy-prod.sh"; parse_args api --bogus) >/dev/null 2>&1; then
  echo "  FAIL unknown flag exited 0"
  fails=$((fails + 1))
else
  echo "  ok   unknown flag exits non-zero"
fi

if [[ "${fails}" -eq 0 ]]; then
  echo "ALL GREEN"
  exit 0
fi
echo "${fails} failing case(s)"
exit 1
