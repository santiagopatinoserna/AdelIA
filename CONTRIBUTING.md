# Contributing to AdelIA

Thanks for considering a contribution. AdelIA is an open source project under AGPL-3.0.

## Sign-off (DCO)

All commits must be signed off:

```bash
git commit -s -m "feat: your change"
```

This appends `Signed-off-by: Your Name <you@example.com>` to the commit message, certifying that you have the right to contribute the change under the AGPL-3.0 license. See the [Developer Certificate of Origin](https://developercertificate.org/).

## Workflow

1. Fork the repo and create a feature branch from `main`.
2. Run tests locally: `pnpm test:api` and `pnpm --filter @adelia/web typecheck`. The backend run needs the dev stack and one setting in `apps/api/.env`; see "Local test gate" below.
3. Open a PR against `main`. Reference any related Issue.
4. Squash on merge. Commit messages follow Conventional Commits:
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation only
   - `chore:` tooling, deps, or non-functional changes
   - `refactor:` internal change without behavior modification
   - `test:` test additions/changes only

## Local test gate

The backend suite is the gate for a PR, and it runs against the dev stack, not against mocks of it. Bring the stack up first.

**1. Start the dev stack** (`infra/docker-compose.dev.yml`):

```bash
pnpm dev:infra
```

| Service | Host address | Credentials |
| --- | --- | --- |
| Postgres 16 + pgvector | `127.0.0.1:5434` | user `adelia`, password `adelia_dev`, database `adelia` |
| MinIO S3 API | `127.0.0.1:9000` | `minioadmin` / `minioadmin`, bucket `adelia-dev` (an init container creates it) |
| MinIO console | `127.0.0.1:9001` | same as the S3 API |

Both services are bound to loopback on purpose, because their credentials are published in the compose file. Postgres is published on host port **5434**, not 5432, because 5432 is commonly taken (a Homebrew Postgres, other containers).

**2. Tell the API about the port.** `apps/api/adelia/config.py` defaults `postgres_port` to 5432, so `apps/api/.env` must set:

```
POSTGRES_PORT=5434
```

Every other default (host `localhost`, user, password, database, MinIO endpoint, bucket) already matches the compose file. The `.env` file is read relative to `apps/api`, which `uv --directory apps/api` makes the working directory.

**3. Apply the migrations** (the Postgres tests expect the schema to exist):

```bash
uv --directory apps/api run alembic upgrade head
```

**4. Run the gate:**

```bash
uv --directory apps/api run pytest -q
uv --directory apps/api run ruff check .
```

Run ruff as written. With `--directory apps/api` the path is relative to `apps/api`, so `ruff check apps/api` fails with E902.

**What passes, skips and fails**

- **Postgres-backed tests skip, they do not fail, when Postgres is not found.** `apps/api/tests/pg_gate.py` makes a 0.5 s TCP probe of `POSTGRES_HOST:POSTGRES_PORT` (override with `PG_AVAILABLE=1` or `0`). With the port wrong, most of the database tests skip and the run can still exit 0, so read the summary line and check the skip count.
- **`tests/test_storage.py` has no guard.** It talks to MinIO on `:9000` and fails if MinIO is not up.
- **Live-API tests skip without keys.** Tests that call Mistral (OCR, embeddings, extraction, transcription, the briefing QA pre-baker) skip when `MISTRAL_API_KEY` is empty, and the one OpenAI transcription test skips without `OPENAI_API_KEY`. A contributor with no keys gets a green suite. A new test that needs a live key must use `pytest.mark.skipif(not settings.<key_name>, ...)` like the existing ones, and no test may require a key to pass.
- **There is no separate test database.** The suite uses the dev database `adelia` and inserts throwaway users (`tests/db_helpers.py`), so do not point it at data you care about.

Reference run on 2026-10-14, stack up, no API keys: 798 tests collected, 787 passed, 11 skipped (every skip is a key gate), in about 21 s. `docs/ESTADO.md` keeps the current numbers.

## Code style

- **Python (apps/api):** ruff (line-length 100, target Python 3.12). Run `uv --directory apps/api run ruff check .`.
- **TypeScript (apps/web):** strict mode + bundler resolution. Run `pnpm --filter @adelia/web typecheck`.

Tests must accompany substantive changes. Backend uses pytest. Frontend behaviour is covered by Playwright specs in `apps/web/e2e` (`pnpm --filter @adelia/web e2e`, which does not start a server: it expects the web app at `E2E_BASE_URL`, default `http://localhost:3001`, with the API behind it); the backend suite and the typecheck are what you run before opening a PR.

## Known carry-overs

These are tracked tech debt items that contributions are welcome on:

- **`Link` migration:** `apps/web/app/[locale]/dashboard/(paid)/briefings/[id]/page.tsx` still imports from `next/link`, and so does `apps/web/app/not-found.tsx` (which sits outside the `[locale]` tree, so check whether a locale-aware Link applies there). Migrate to `@/lib/navigation` Link where it does.
- **Hydration-safe date formatting:** `new Date(...).toLocaleString()` and `.toLocaleDateString()` are called without a locale argument in `apps/web/components/briefing/share-dialog.tsx` and `apps/web/app/[locale]/dashboard/(paid)/enrichment/genomics/page.tsx`. Use `next-intl`'s `useFormatter` or pass an explicit locale.
- **`auth_secret` empty default in API config:** `apps/api/adelia/config.py` still defaults to `""`. The API no longer verifies tokens against an empty secret (`decode_session_token` in `apps/api/adelia/auth.py` raises, and authenticated routes answer 503) and `main.py` logs a critical line at boot, but the process still starts. Failing fast at boot would be stricter.
- **Server-only guard on `api-client.ts`:** add `import "server-only"` to prevent accidental client imports.

## Reporting issues

Use GitHub Issues. Include reproduction steps, expected vs actual, and AdelIA version (commit SHA or tag) when applicable.

## License

AdelIA is AGPL-3.0. By contributing, you agree your contribution is licensed under AGPL-3.0 alongside the project.
