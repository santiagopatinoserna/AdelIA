# AdelIA

AGPL-3.0 medical vault plus AI analysis for parents of babies (0-24 months). It holds health data.

## Architecture
- `apps/api`: FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic, Postgres 16 + pgvector, MinIO for blobs.
  `apps/web`: Next.js 15, next-intl (es/en/fr), Auth.js. Settings in `adelia/config.py`, read from `.env`.
- Ingestion runs in-process (`routers/documents.py`, steps in `workers/`). There is no durable queue:
  boot reconciliation (`requeue_stuck_documents`) retries whatever a restart killed.
- Three answering surfaces run one LangGraph graph (`agent/graph.py`, docs/specs/AGENT_GRAPH.md):
  the public demo (`routers/demo.py`), the RAG chat (`services/chat_orchestrator.py`) and the agent
  behind /dashboard (`agent/orchestrator.run_turn`). Each lends its capabilities through `GraphDeps`
  (buttons, cards, writes, the tool loop). All wording follows `services/answer_contract.py`.
- Red flags are code, not model: `clinical/red_flags.py` runs before the RAG and short-circuits to a
  referral. Empty retrieval returns `no_evidence_reply()` and never reaches the generative model.
- Every read path takes `Scope(user_id, profile_id)` (`services/scope.py`) so siblings never share a
  vault. Lab ranges are banded by age and age is mandatory (`enrichment/lab_ranges.py`).
- Paying routes sit behind `auth.require_active_subscription`.
- Mistral for OCR, chat and embeddings (1024-dim), Voxtral for speech-to-text, Anthropic for the agent.

## Commands (from the repo root)
- Dev stack: `pnpm dev:infra` (Postgres and MinIO, `infra/docker-compose.dev.yml`). It is often already
  up; check before starting. API: `pnpm dev:api`. Web: `pnpm dev:web`.
- Migrations: `uv --directory apps/api run alembic upgrade head`.
- Tests: `uv --directory apps/api run pytest -q`. Needs Postgres and MinIO. Each test has a 120s ceiling
  (pytest-timeout); mark a slow one with `@pytest.mark.timeout(n)`, do not raise the global value.
- Lint: `uv --directory apps/api run ruff check .`. Passing `apps/api` as the path together with
  `--directory` fails with E902, which is not a lint finding.
- Typecheck: `pnpm --filter @adelia/web typecheck`. Web e2e: `pnpm --filter @adelia/web e2e`, which needs
  the API on :8000 and the web app on :3001 (see the `e2e` job in `.github/workflows/ci.yml`).
- The es/en/fr catalogs in `apps/web/messages/` must keep identical keys; CI checks it.
- `scripts/deploy-prod.sh` deploys to the home server. It is a human's job: it rsyncs the working tree
  and is gated on a clean pushed tree and the clinical golden set (`clinical/golden.py`).

## House rules
- Docstrings explain WHY, often with the incident behind the code. When a change traces to the
  2026-08-31 audit, cite the item (for example "audit 4.4"). Match the density of the file you touch.
- Line length 100. No em dashes and no marketing language in prose.
- Tests sit in `apps/api/tests/test_<module>.py`, next to the behaviour they cover. DB tests gate on
  `tests.pg_gate.PG_AVAILABLE`. A test that needs a live LLM key must `skipif` on the setting: CI has
  no keys and the suite must skip there, not fail.
- Never delete, skip or loosen an existing test to reach green.
- `tests/db_helpers.make_user()` returns an active subscriber. To test the paywall pass
  `subscription_status="none"` and a `created_days_ago` past the free trial.
- The dev database is shared and full of stuck rows. Seed `Document`s with `processed_at` set unless the
  test is about reconciliation, or the next `TestClient(app)` boot requeues them as real pipelines.
- Open DB sessions with `async with AsyncSessionLocal()` and hold none across network I/O (pool
  exhaustion already caused 500s once). Cancel and await background tasks before `engine.dispose()`.
- CI runs lint last on purpose, so a style error cannot hide the test results. Keep that order.
- Commits follow Conventional Commits (`feat(scope):`, `fix:`, `chore:`), one concern each.

## Standing prohibitions
- Never `git push`, open a PR or touch `main` unless asked to in the current conversation.
- Never touch production: no ssh to the server, no `deploy-prod.sh`, no `infra/docker-compose.prod.yml`,
  no requests to the live domain. Never use `--allow-dirty` or `--skip-golden` on the deploy script.
- Never read, print or commit a secret or an `.env` file. Never put API keys in tests or fixtures.
- No dependency bump or lockfile change unless the task is that bump.
