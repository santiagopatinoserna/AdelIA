#!/usr/bin/env bash
# The clinical gate for groups A and B, ON THE SERVER, before `up -d`.
#
# Called by scripts/deploy-prod.sh over ssh, from /opt/adelia, after the code
# is synced and BEFORE the container that serves the mothers is replaced. It
# never starts, stops or recreates a service and never writes to the live
# database. Full account: docs/GOLDEN_GATE_DESPLIEGUE.md.
#
#   1. Build the new api image and its `golden` stage (same layers plus
#      tests/ and pytest). A build failure stops here, with the old
#      containers untouched.
#   2. Copy the production CORPUS into a scratch database on the same
#      Postgres: the whole schema, but data only for alembic_version and the
#      evidence tables. No family's record leaves the live database.
#   3. Run apps/api/scripts/golden_gate.sh in a throwaway api-golden
#      container pointed at the scratch copy: migrate it to the new head,
#      load the new release's corpus as boot would, run the golden set with
#      the production keys and provider.
#   4. Drop the scratch database, whatever happened.
#
# Why a scratch copy and not the live database: migrations run when the new
# container boots (apps/api/Dockerfile CMD), and new corpus files are loaded
# at boot too (adelia/main.py load_startup_corpora). Against the live
# database the gate would measure the new code on the OLD schema and the OLD
# corpus, and migrating it first would leave the old release serving on a
# schema it was not written for if the gate then failed.
#
# Exit status: 0 passed, 1 ran and failed, 2 could not run. deploy-prod.sh
# stops on anything but 0.
#
# Secrets: this script never reads .env.prod; docker compose does, through
# --env-file, as on every deploy. The database user and name are read inside
# the postgres container, from its own environment.
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose
  -f infra/docker-compose.prod.yml -f infra/docker-compose.golden.yml
  --env-file .env.prod --profile golden)
# Must end in _golden_gate: apps/api/scripts/golden_gate.sh refuses any other.
SCRATCH_DB=adelia_golden_gate

say() { printf 'golden gate: %s\n' "$*"; }

# Run inside the postgres container, with the scratch name in its env. The
# guard makes it impossible to drop or overwrite the live database even if
# SCRATCH_DB were edited to its name.
in_postgres() {
  "${COMPOSE[@]}" exec -T -e SCRATCH_DB="${SCRATCH_DB}" postgres bash -c "$1"
}

drop_scratch() {
  in_postgres 'set -eu
[ "$SCRATCH_DB" != "$POSTGRES_DB" ] || exit 1
dropdb -U "$POSTGRES_USER" --if-exists "$SCRATCH_DB"' >/dev/null 2>&1 || true
}

copy_corpus() {
  in_postgres 'set -euo pipefail
[ "$SCRATCH_DB" != "$POSTGRES_DB" ] || { echo "scratch db is the live db" >&2; exit 1; }
dropdb -U "$POSTGRES_USER" --if-exists "$SCRATCH_DB"
createdb -U "$POSTGRES_USER" "$SCRATCH_DB"
dump() { pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges "$@"; }
load() { psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$SCRATCH_DB" >/dev/null; }
# Tables first, then the corpus rows, then indexes and constraints, so the
# vector index is built once over the loaded rows.
dump --section=pre-data | load
dump --section=data -t public.alembic_version -t "public.evidence*" | load
dump --section=post-data | load
psql -At -U "$POSTGRES_USER" -d "$SCRATCH_DB" -c "select count(*) from evidence_chunks" \
  | sed "s/^/corpus copied: /; s/$/ chunks/"'
}

trap drop_scratch EXIT
trap 'exit 2' HUP INT TERM

SECONDS=0
# Only api-golden: building `api` here would retag the serving image before
# the verdict, and after a failed gate any later `up -d api` (an .env.prod
# change, a restart) would roll out the code that failed. Both targets share
# the `base` layers, so the `up -d --build api` that follows a pass is cached.
say "building api-golden (the new code, same base layers as the image about to serve)"
if ! "${COMPOSE[@]}" build api-golden; then
  say "NOT RUN: the new image does not build"
  exit 2
fi

say "copying the production corpus into ${SCRATCH_DB}"
if ! copy_corpus; then
  say "NOT RUN: could not copy the corpus into ${SCRATCH_DB}"
  exit 2
fi

say "running the golden set in a throwaway api-golden container"
"${COMPOSE[@]}" run --rm --no-deps -e POSTGRES_DB="${SCRATCH_DB}" api-golden \
  bash scripts/golden_gate.sh
rc=$?
case "${rc}" in
  0) verdict="PASSED" ;;
  1) verdict="FAILED" ;;
  *) verdict="NOT RUN"; rc=2 ;;
esac
say "${verdict} (duración del gate: ${SECONDS}s, build y copia incluidos)"
exit "${rc}"
