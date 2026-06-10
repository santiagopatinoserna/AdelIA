# AdelIA

Open source personal medical vault + AI analysis (self-analysis + doctor briefing).

**Status:** v0.1 in development. M1 (foundation) — see `docs/specs/` and `docs/plans/`.

**License:** AGPL-3.0. See `LICENSE`.

> ⚠️ AdelIA is a personal documentation tool, not a medical device.
> It does not provide medical advice. Always verify with your healthcare professional.

## Architecture

- `apps/web` — Next.js 15 frontend (Auth.js v5 magic links via Resend, next-intl ES strings)
- `apps/api` — FastAPI backend (Python 3.12, SQLAlchemy 2, Alembic, pgvector)
- `infra/docker-compose.dev.yml` — Postgres 16 + pgvector + MinIO
- See `docs/specs/2026-05-05-adelia-v0.1-design.md` for the full v0.1 design spec.

### v0.1 Backend Flow

```
POST /documents (auth)
  → validate mime
  → upload to S3 (50 MB max, sanitized filename)
  → create Document row (status=processing)
  → schedule BackgroundTask:
      → fetch from S3
      → Mistral OCR (PDF/image) or [audio: M2 Whisper integration]
      → persist raw_text → set processed_at
      → derive_status returns ready (or failed)

GET /documents (auth) → user's docs, soft-delete filtered, ordered by created_at desc
GET /documents/{id} (auth) → 404 opaque on missing/wrong-user/deleted
```

## Quickstart (dev)

**Prerequisites:**

- Docker Desktop (for Postgres + MinIO)
- Node 20+ and pnpm 9+
- Python 3.12+ and [uv 0.4+](https://docs.astral.sh/uv/)

**1. Clone and install:**

```bash
git clone https://github.com/santiagopatinoserna/AdelIA.git
cd AdelIA
pnpm install
uv --directory apps/api sync
```

**2. Copy env files and fill in keys:**

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

Required keys (replace placeholders):

- `AUTH_SECRET` — must match in both `apps/api/.env` and `apps/web/.env`. Generate: `openssl rand -base64 32`
- `RESEND_API_KEY` — Resend account → API Keys → Create
- `MISTRAL_API_KEY` — La Plateforme account → API Keys

**3. Start infrastructure:**

```bash
pnpm dev:infra
```

This brings up Postgres 16 (with pgvector extension) + MinIO + an init container that auto-creates the `adelia-dev` bucket.

**4. Apply database migrations:**

```bash
uv --directory apps/api run alembic upgrade head
```

**5. Start servers (in two terminals):**

```bash
pnpm dev:api    # FastAPI on :8000
pnpm dev:web    # Next.js on :3000
```

**6. Visit the app:**

http://localhost:3000/es

You should see the AdelIA home page. Click "Empezar" → sign in with magic link → dashboard.

### Smoke test the upload flow

1. Navigate to `/es/dashboard/upload`.
2. Drag-drop a PDF (or use the file picker). Allowed types: PDF, PNG, JPEG, audio (mp3/wav). Max 50 MB.
3. After upload you'll be redirected to `/es/dashboard`. The new document appears with status `Procesando…`.
4. Wait ~5–15 seconds for Mistral OCR to complete in the background.
5. Reload the dashboard. The document status flips to `Listo`.
6. Click the document card. The detail page shows the OCR'd text.

> v0.1 has no auto-poll on the detail page — manually reload until status changes. Auto-poll lands in v0.1.1.

## Tests

**Backend (Python + pytest):**

```bash
pnpm test:api
```

With Docker Compose running and AUTH_SECRET set in `apps/api/.env`, you should see 7+ passed tests. With `MISTRAL_API_KEY` set, the OCR test runs live. Document tests use `skipif(True)` and need to be enabled manually (toggle to `False` in `tests/test_documents.py`).

**Frontend (typecheck + production build):**

```bash
pnpm --filter @adelia/web typecheck
pnpm --filter @adelia/web build
```

Both should exit 0.

## Self-host

`docker compose -f infra/docker-compose.dev.yml` is a dev profile. A production self-host compose file is on the v0.1.1 roadmap.

## Roadmap

- **v0.1 (this milestone):** core OCR ingest + dashboard + detail. Spanish UI only. Manual reload for status.
- **v0.1.1 (post-launch):** EN + FR i18n strings, auto-poll on detail page, Telegram bot ingest, email forwarding ingest, PWA installable, pagination.
- **v0.2:** Whisper audio transcription, WhatsApp ingest, hosted subscription tier ($5/mo), clinician_verified provenance.
- **v0.3:** Doctor query mode, Mon Espace Santé (FR) integration, Sanidad ES (per CCAA).

## Contributing

See `CONTRIBUTING.md`. Use DCO sign-off (`git commit -s`). No CLA.

## Security

See `SECURITY.md` for vulnerability reporting.
