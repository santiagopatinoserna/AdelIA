#!/usr/bin/env bash
# The golden set as the deploy gate, INSIDE the api-golden container.
#
# Started by scripts/prod-golden-gate.sh on the server, in a throwaway
# container of the new image's `golden` stage, with POSTGRES_DB pointing at a
# scratch copy of the production corpus (never at the live database). It
# brings that copy to the state the new release will boot into, then measures
# it (docs/GOLDEN_GATE_DESPLIEGUE.md):
#
#   1. alembic upgrade head: the scratch copy left production at its current
#      revision; the new code is measured on the new schema, and production
#      is not migrated before the release is approved.
#   2. load_startup_corpora(): what the new container does at boot, so the
#      sources a release adds (enrichment/data/evidence_*.json, the crawler)
#      are in the corpus the gate measures. Measuring the live database would
#      only ever measure the corpus of the PREVIOUS release.
#   3. tests/test_rag_golden.py with ADELIA_GOLDEN_DEPLOY=1: groups A, B and C
#      on the production provider; a skip of A and B is a failure here.
#
# Exit status, read by prod-golden-gate.sh and deploy-prod.sh:
#   0  the gate passed
#   1  it ran and failed (recall, refusals, orphans, citations or red flags)
#   2  it could not run (refused database, migration, corpus, no report, or
#      A and B skipped); the deploy stops on this one too
#
# golden_report.json is printed whole, so the deploy log carries recall@4,
# the refusal rate, the orphan citations, the questions that missed and the
# model calls and seconds the run took.
set -uo pipefail

cd "$(dirname "$0")/.."
PY=.venv/bin/python
REPORT=golden_report.json

say() { printf 'golden: %s\n' "$*"; }

# The only database this script may migrate is the scratch copy. A wrong
# environment would otherwise run the new release's migrations against the
# live database while the previous release still serves from it.
case "${POSTGRES_DB:-}" in
  *_golden_gate) ;;
  *)
    say "POSTGRES_DB=${POSTGRES_DB:-<unset>} is not a scratch copy (*_golden_gate); refusing to touch it"
    exit 2
    ;;
esac

rm -f "${REPORT}"

say "alembic upgrade head on ${POSTGRES_DB}"
if ! .venv/bin/alembic upgrade head; then
  say "the migrations of this release fail on a copy of production"
  exit 2
fi

say "loading the corpus this release boots with (load_startup_corpora)"
if ! "${PY}" -c '
import asyncio

from adelia.db import engine
from adelia.main import load_startup_corpora


async def _load():
    try:
        await load_startup_corpora()
    finally:
        await engine.dispose()


asyncio.run(_load())
'; then
  say "the startup corpus load crashed"
  exit 2
fi

say "golden set (groups A, B and C)"
ADELIA_GOLDEN_DEPLOY=1 "${PY}" -m pytest -q -p no:cacheprovider -rsP tests/test_rag_golden.py
rc=$?

if [[ -f "${REPORT}" ]]; then
  say "---- ${REPORT} ----"
  cat "${REPORT}"
fi

if [[ "${rc}" -eq 0 ]]; then
  exit 0
fi
# The report says "skipped_reason": null exactly when A and B ran
# (tests/test_rag_golden.py pins that line); then a failure is a real one.
if [[ -f "${REPORT}" ]] && grep -q '^  "skipped_reason": null,$' "${REPORT}"; then
  exit 1
fi
exit 2
