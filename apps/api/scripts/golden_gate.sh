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
#   3. tests/test_rag_golden.py with ADELIA_GOLDEN_DEPLOY=1: groups A, B and C;
#      a skip of A and B is a failure here.
#
# Without a model, unless --with-model (2026-11-06, Santiago's rule: the app's
# Anthropic budget is 200 $ a month and the mothers who ask pay it). The set
# runs with ADELIA_GOLDEN_MODEL_FREE=1: real retrieval and cut-offs, a fixed
# text instead of each answer, the routing rules instead of the routing model,
# and no call to Anthropic at all. --with-model is the full pass on the
# production provider (about 40 generations and the routing calls).
#
# --candidates GLOB (always without a model): after that run, the CANDIDATES
# questions are previewed, the candidate files are loaded into this scratch
# copy (scripts/golden_candidates.py, never the live database, never boot),
# and the set and the preview run again; then both are compared. The exit
# status is still the verdict on the release as it would serve, without the
# candidates; the comparison is printed for whoever decides what enters data/.
#
# --explain IDS (2026-11-07, always without a model): the named questions, e.g.
# A1,A5,B6, previewed with --explain after the set (and again after the
# candidates load): their nearest sources with distance, the cut and the file
# each comes from, then side by side (golden_candidates.py explain). The first
# server run of the 2026-11-06 candidates said which questions broke but not
# which sources broke them. A diagnostic: it never changes the exit status.
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

WITH_MODEL=0
CANDIDATES=""
EXPLAIN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-model) WITH_MODEL=1 ;;
    --candidates)
      CANDIDATES="${2:-}"
      [[ -n "${CANDIDATES}" ]] || { say "--candidates needs a glob"; exit 2; }
      shift ;;
    --explain)
      EXPLAIN="${2:-}"
      # Question ids only (A1,A5,B6): anything else is a typo, or worse.
      [[ "${EXPLAIN}" =~ ^[ABC][0-9]+(,[ABC][0-9]+)*$ ]] || {
        say "--explain needs question ids separated by commas, e.g. A1,A5,B6"; exit 2; }
      shift ;;
    *) say "unknown argument: $1 (known: --with-model, --candidates GLOB, --explain IDS)"
       exit 2 ;;
  esac
  shift
done
if [[ "${WITH_MODEL}" -eq 1 && -n "${CANDIDATES}" ]]; then
  say "candidates are measured without a model only; drop --with-model"
  exit 2
fi
if [[ "${WITH_MODEL}" -eq 1 ]]; then
  MODEL_FREE=0
  MODE="con modelo: el proveedor de producción genera y enruta"
else
  MODEL_FREE=1
  MODE="sin modelo: recuperación real, ni una llamada a Anthropic (GOLDEN_WITH_MODEL=1 para la pasada completa)"
fi

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

# Last run's files, so a run that writes nothing is never read as this one.
rm -f "${REPORT}" golden_report.*_candidatos.json golden_preview.*_candidatos.json \
  golden_explain.*_candidatos.json

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

# Without a model the run gets no Anthropic key at all: the test's fake
# client catches what reaches it, and with no key nothing it did not foresee
# can spend either. Mistral stays: embeddings are allowed.
run_set() {
  local -a drop=()
  [[ "${MODEL_FREE}" -eq 1 ]] && drop=(-u ANTHROPIC_API_KEY)
  env ${drop[@]+"${drop[@]}"} ADELIA_GOLDEN_DEPLOY=1 ADELIA_GOLDEN_MODEL_FREE="${MODEL_FREE}" \
    "${PY}" -m pytest -q -p no:cacheprovider -rsP tests/test_rag_golden.py
}

print_report() {
  if [[ -f "$1" ]]; then
    say "---- $1 ----"
    cat "$1"
  fi
}

# 0 passed, 1 ran and failed, 2 did not run. The report says
# "skipped_reason": null exactly when A and B ran (tests/test_rag_golden.py
# pins that line); then a failure is a real one.
verdict() {
  local rc="$1" report="$2"
  [[ "${rc}" -eq 0 ]] && return 0
  if [[ -f "${report}" ]] && grep -q '^  "skipped_reason": null,$' "${report}"; then
    return 1
  fi
  return 2
}

# The CANDIDATES questions through guard and retrieval, no model; a preview
# that cannot measure (no embedding key) is said, not fatal: the gate's own
# comparison still stands.
preview() {
  if ! PYTHONPATH=. "${PY}" scripts/preview_golden_candidates.py --no-model --json "$1"; then
    [[ -f "$1" ]] || say "preview of the CANDIDATES questions not measured ($1)"
  fi
}

# --explain: the named questions, source by source, into $1. Never fatal.
explain_run() {
  [[ -n "${EXPLAIN}" ]] || return 0
  local -a origins=()
  [[ -n "${CANDIDATES}" ]] && origins=(--origins "${CANDIDATES}")
  say "explicación de ${EXPLAIN} ($1)"
  PYTHONPATH=. "${PY}" scripts/preview_golden_candidates.py --no-model --ids "${EXPLAIN}" \
    --explain ${origins[@]+"${origins[@]}"} --json "$1" \
    || [[ -f "$1" ]] || say "explicación no medida ($1)"
}

# $1 "with": the candidates were loaded and explained too. A file that a
# failed explanation never wrote is said by golden_candidates.py, not fatal.
explain_side_by_side() {
  [[ -n "${EXPLAIN}" ]] || return 0
  local -a args=(--without golden_explain.sin_candidatos.json)
  [[ "${1:-}" == "with" ]] && args+=(--with golden_explain.con_candidatos.json)
  PYTHONPATH=. "${PY}" scripts/golden_candidates.py explain "${args[@]}" || true
}

say "golden set (groups A, B and C), ${MODE}"
run_set
rc=$?
print_report "${REPORT}"
verdict "${rc}" "${REPORT}"
status=$?

if [[ "${status}" -eq 2 ]]; then
  [[ -n "${CANDIDATES}" ]] && say "candidatos: not measured, the run without them did not measure either"
  exit 2
fi
if [[ -z "${CANDIDATES}" ]]; then
  explain_run golden_explain.sin_candidatos.json
  explain_side_by_side
  exit "${status}"
fi

WITHOUT=golden_report.sin_candidatos.json
WITH=golden_report.con_candidatos.json
cp "${REPORT}" "${WITHOUT}"
say "candidatos: ${CANDIDATES}; preview of the CANDIDATES questions without them"
preview golden_preview.sin_candidatos.json
explain_run golden_explain.sin_candidatos.json
say "candidatos: loading them into ${POSTGRES_DB} (the scratch copy; never the live database)"
if PYTHONPATH=. "${PY}" scripts/golden_candidates.py load "${CANDIDATES}"; then
  say "golden set again, with the candidates, ${MODE}"
  # A run that dies before writing its report must not leave the one
  # without candidates under this name: the comparison would call it a tie.
  rm -f "${REPORT}"
  run_set
  print_report "${REPORT}"
  [[ -f "${REPORT}" ]] && mv "${REPORT}" "${WITH}"
  preview golden_preview.con_candidatos.json
  explain_run golden_explain.con_candidatos.json
  compare_args=(--without "${WITHOUT}" --with "${WITH}")
  if [[ -f golden_preview.sin_candidatos.json && -f golden_preview.con_candidatos.json ]]; then
    compare_args+=(--preview-without golden_preview.sin_candidatos.json
                   --preview-with golden_preview.con_candidatos.json)
  fi
  PYTHONPATH=. "${PY}" scripts/golden_candidates.py compare "${compare_args[@]}"
  explain_side_by_side with
else
  say "candidatos: NO SE PUDIERON CARGAR; the verdict below is the release's, without them"
fi
# The release's report, as the deploy and golden_gate's callers read it.
cp "${WITHOUT}" "${REPORT}"
exit "${status}"
