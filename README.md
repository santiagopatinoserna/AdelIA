# AdelIA

Open source personal medical vault + AI analysis (self-analysis + doctor briefing).

**Status:** v0.2.0-rc1 — all v0.1 milestones (M1-M6) + v0.2 enrichment layers shipped on `main`. See `docs/specs/` and `docs/plans/` for design history.

**What works today** (verified E2E):

- 📄 Upload PDF/image/audio → Mistral OCR / Whisper → entity extraction → hierarchical chunks + embeddings (auto-retry on transient API failures)
- 💬 Chat over your records (SSE streaming, multi-turn memory, dual-RAG with clinical guidelines, citations) — answers in ES/EN/FR
- 📋 Doctor briefing generator (SBAR-style, 8 specialties, anti-hallucination QA pre-baker) — fully localized es/en/fr, including the PDF
- 🔗 Sharing: signed links with TTL + revoke, public HTML view, WeasyPrint PDF
- ✨ Enrichment: ICD-10/SNOMED normalization, lab reference ranges, drug-drug interactions, ClinicalTrials.gov matching, 23andMe genomics, family profiles
- 📥 Import wizards: Apple Health, CCD/MyChart, platform guides, GDPR request templates
- 🌍 UI in Spanish, English and French (next-intl, locale switcher)

**License:** AGPL-3.0. See `LICENSE`.

> ⚠️ AdelIA is a personal documentation tool, not a medical device.
> It does not provide medical advice. Always verify with your healthcare professional.

## Architecture

- `apps/web` — Next.js 15 frontend (Auth.js v5 magic links via Resend + custom Pg adapter, next-intl es/en/fr, JWT-signing proxy at `/api/backend` so the token never reaches the browser)
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
pnpm dev:web    # Next.js on :3000 (use -p 3001 if :3000 is taken — keep NEXTAUTH_URL in sync)
```

**6. Visit the app:**

http://localhost:3000/es (or /en, /fr)

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

With Docker Compose running (Postgres + MinIO) and keys set in `apps/api/.env`, the full suite runs ~280 tests including live Postgres integration tests (auto-detected via TCP probe — override with `PG_AVAILABLE=0/1`) and live Mistral OCR/extract tests when `MISTRAL_API_KEY` is set.

**Frontend (typecheck + production build):**

```bash
pnpm --filter @adelia/web typecheck
pnpm --filter @adelia/web build
```

Both should exit 0.

## Self-host

Dev profile: `docker compose -f infra/docker-compose.dev.yml up -d`.

Production profile (builds the API and web images — same Dockerfiles a Fly.io deploy uses):

```bash
cp .env.prod.example .env.prod   # fill in secrets
docker compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d --build
```

Web on `:3000`, API on `:8000` (override with `WEB_PORT`/`API_PORT`). The API container runs `alembic upgrade head` on boot. Put a TLS proxy (Caddy/Traefik) in front for anything beyond a LAN.

### Backups

A `backup` sidecar runs `pg_dump` (custom format, compressed) every 24h into the `pgbackups` volume, pruning dumps older than 14 days (`BACKUP_INTERVAL_SECONDS` / `BACKUP_RETENTION_DAYS`). Restore:

```bash
# list available dumps
docker compose -f infra/docker-compose.prod.yml exec backup ls -lh /backups
# restore one (drops and recreates objects)
docker compose -f infra/docker-compose.prod.yml exec backup \
  pg_restore --clean --if-exists -d adelia /backups/adelia-YYYYMMDD-HHMMSS.dump
```

Document blobs live in the `miniodata` volume — snapshot it at the filesystem level alongside the DB dumps (the dump covers metadata; blobs are the original files).

## Roadmap

- **Now (pre-launch ops):** Fly.io deploy, Resend domain verification, Telegram bot + Postmark inbound keys (scaffolding is merged and tested).
- **v0.2.x:** live consultation recording (Whisper streaming), WhatsApp ingest, hosted subscription tier, clinician_verified provenance.
- **v0.3:** doctor query mode (QR + ephemeral session), Mon Espace Santé (FR) integration, Sanidad ES (per CCAA).

## Contributing

See `CONTRIBUTING.md`. Use DCO sign-off (`git commit -s`). No CLA.

## Security

See `SECURITY.md` for vulnerability reporting.
