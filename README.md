# AdelIA

Open source personal medical vault + AI analysis (self-analysis + doctor briefing).

**Status:** the tag `v0.2.0-rc1` (2026-06-10) marks the v0.1 milestones (M1-M6) plus the v0.2 enrichment layers. `main` is well past that tag: the clinical audit remediation of 2026-09-01 (answer contract, red flags, evidence cut-off, per-profile scope, paywall on the API) is on it. See `docs/ESTADO.md` for the current state and test counts, and `docs/specs/` and `docs/plans/` for design history.

**What works today** (each line checked against the code; the file it rests on is named where it helps):

- 📄 Upload PDF/image/audio → Mistral OCR (PDF, image) or speech-to-text (audio: Voxtral by default, with speaker diarization for consultation recordings; OpenAI `whisper-1` is selectable with `STT_PROVIDER`, without diarization) → entity extraction → hierarchical chunks + embeddings, with a bounded retry on transient API failures (`routers/documents.py`). "Grabar consulta" records in the browser; the Telegram bot (photos, files, voice notes, text diary entries) feeds the same pipeline once `TELEGRAM_BOT_TOKEN` is set. Email forwarding is not wired yet: the Postmark webhook validates the signature and returns attachment metadata, but the attachments are not stored (`ingestion/email_inbound.py`)
- 💬 Chat over your records (SSE streaming, multi-turn memory, dual-RAG with clinical guidelines, citations) and a tool-using agent behind `/dashboard` (needs `ANTHROPIC_API_KEY`). Both answer in ES/EN/FR under the clinical answer contract below, and both scope their reads to the active profile, so two children never share one vault (`services/scope.py`)
- 📋 Doctor briefing generator (SBAR-style, 7 specialty templates plus a default, QA pre-baker that drops any citation whose quote is not verbatim in a source document), localized es/en/fr, including the PDF
- 🔗 Sharing: random opaque tokens with a TTL (24 h default, 30 days maximum) and revoke, public HTML view, WeasyPrint PDF
- ✨ Enrichment: ICD-10/SNOMED normalization (54 curated entries), reference ranges banded by age (age is required), drug-drug interactions (29 curated pairs, offline), ClinicalTrials.gov matching (live call to the public API), 23andMe genomics (a curated set of 20 variants, not full ClinVar), family profiles
- 📥 Import wizards: Apple Health, CCD/MyChart, platform guides, GDPR request templates (Spain, France, US)
- 🌍 UI in Spanish, English and French (next-intl, locale switcher), installable as a PWA

**License:** AGPL-3.0. See `LICENSE`.

> ⚠️ AdelIA is a personal documentation tool, not a medical device.
> It does not provide medical advice. Always verify with your healthcare professional.

## Clinical answer contract

The clinical promise is enforced in code wherever code can enforce it, not only requested of a model in a prompt. Four pieces carry it:

- **One contract for every answering surface.** [`services/answer_contract.py`](apps/api/adelia/services/answer_contract.py) holds the rules once (every clinical statement carries an `[ev_N]` citation, no interpretation without one, the refusal wording, the language). `chat_system_prompt` and `agent_system_prompt` both compose it, so the RAG chat and the `/dashboard` agent cannot drift apart. The disclaimer is a fixed element of the chat and agent screens (`components/clinical-disclaimer.tsx`), not something the model is asked to write.
- **Red flags short-circuit the model.** [`clinical/red_flags.py`](apps/api/adelia/clinical/red_flags.py) is a deterministic detector with 11 flags (fever at 38 C or more under 3 months, non-blanching rash, respiratory distress, cyanosis, seizure, choking, anaphylaxis, bulging fontanelle, lethargy, no wet nappy for 12 hours, dehydration), matched in Spanish, English and French. It runs first in the chat (`services/chat_orchestrator.py`) and in the agent (`agent/orchestrator.py`). When it fires, the code returns a fixed referral that names the emergency number, with the guideline behind it, and no retrieval, embedding or generative call is made. It over-triggers on purpose: a false positive costs a phone call, a false negative costs more.
- **No evidence, no answer.** Clinical retrieval is cut at `evidence_max_distance = 0.19` in [`config.py`](apps/api/adelia/config.py), calibrated against the real corpus: it keeps 240 of 240 in-corpus probes and rejects 14 of 14 off-corpus ones ([method and numbers](apps/api/docs/CALIBRACION_UMBRAL_EVIDENCIA.md)). When neither the guideline search nor the user's own records return anything, the chat returns `no_evidence_reply()` from code and never calls the generative model. The agent reaches the same pipeline through its `buscar_en_expediente` tool, so it receives the same refusal as the tool result; the model still writes that turn, bound by the shared contract.
- **Extracted quotes must be literal.** [`workers/extract.py`](apps/api/adelia/workers/extract.py) asks for a verbatim `raw_quote` with every entity and discards any entity whose quote is not a substring of the document text.

These are guarantees about what the code does with a question, not claims about clinical accuracy. The tests that pin them are `test_red_flags.py`, `test_answer_contract.py`, `test_chat_orchestrator.py`, `test_agent_orchestrator.py` and `test_evidence_threshold_integration.py` under `apps/api/tests/`. The literal-quote rule is the exception: `test_extract.py` asserts it against the live Mistral API only, so a run without keys does not exercise it. The patient-side cut-off (`patient_max_distance = 0.45`) is not calibrated yet; see the roadmap.

## Architecture

- `apps/web` — Next.js 15 frontend (Auth.js v5 magic links via Resend + custom Pg adapter, next-intl es/en/fr, JWT-signing proxy at `/api/backend` so the token never reaches the browser)
- `apps/api` — FastAPI backend (Python 3.12, SQLAlchemy 2, Alembic, pgvector)
- `infra/docker-compose.dev.yml` — Postgres 16 + pgvector + MinIO
- See `docs/specs/2026-05-05-adelia-v0.1-design.md` for the full v0.1 design spec.

### Backend Flow

```
POST /documents (auth + active subscription)
  → validate mime
  → upload to S3 (50 MB max, sanitized filename)
  → create Document row (processed_at empty, so derive_status says processing)
  → schedule an in-process task (concurrency capped by DOC_PROCESSING_CONCURRENCY):
      → fetch from S3
      → Mistral OCR (PDF/image) or speech-to-text (audio)
      → entity extraction (workers/extract.py drops entities with a non-literal quote)
      → hierarchical chunks (350 / 1500 tokens) + embeddings
      → persist raw_text, entities and chunks → set processed_at
      → derive_status returns ready (or failed)
  → at boot, documents still unprocessed after 15 minutes are re-queued

GET /documents (auth) → the account's docs, optionally narrowed with ?profile_id=, soft-delete filtered, newest first, ?limit= (default 50, max 200) and ?offset=
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
2. Drag-drop a PDF (or use the file picker). Allowed types: PDF, PNG, JPEG, audio (mp3, wav, webm, mp4, ogg, m4a, flac). Max 50 MB.
3. After upload you'll be redirected to `/es/dashboard`. The new document appears with status `Procesando…`.
4. Wait ~5–15 seconds for Mistral OCR to complete in the background.
5. Reload the dashboard. The document status flips to `Listo`.
6. Click the document card. The detail page shows the OCR'd text.

> The document detail page polls every 2.5 s while a document is processing and stops after about 5 minutes with an offer to reload (`components/document-detail-view.tsx`). The dashboard list does not refresh itself.

## Tests

**Backend (Python + pytest):**

```bash
pnpm test:api
```

With the dev stack running (Postgres + MinIO) the suite includes live Postgres integration tests (auto-detected via TCP probe, override with `PG_AVAILABLE=0/1`). Tests that call the live Mistral or OpenAI APIs skip when the key is empty, so a checkout with no keys still gets a green run. `CONTRIBUTING.md` has the ports and the `apps/api/.env` setting a fresh machine needs (the dev Postgres listens on 5434, not 5432), and `docs/ESTADO.md` has the current test counts.

**Frontend (typecheck + production build):**

```bash
pnpm --filter @adelia/web typecheck
pnpm --filter @adelia/web build
```

Both should exit 0.

## Self-host

Dev profile: `docker compose -f infra/docker-compose.dev.yml up -d`.

Production profile (builds the API and web images from `apps/api/Dockerfile` and `apps/web/Dockerfile`):

```bash
cp .env.prod.example .env.prod   # fill in secrets
docker compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d --build
```

Web on `:3000`, API on `:8000` (override with `WEB_PORT`/`API_PORT`). The API container runs `alembic upgrade head` on boot. Put a TLS proxy (Caddy/Traefik) in front for anything beyond a LAN.

**Billing is optional and off by default.** Leaving `STRIPE_SECRET_KEY` empty runs the instance with no subscription check at all: `/billing/checkout` answers 503, nothing ever writes `users.subscription_status`, and every product route stays open. Set `STRIPE_SECRET_KEY` (plus `STRIPE_WEBHOOK_SECRET` and `STRIPE_PRICE_ID`) and the paywall turns on for the routes that spend money: uploads, chat and agent turns, briefing generation, share links, PDFs, enrichment and ingestion. Reads, deletes and the data export are never behind it, on any configuration. With billing on, an account that has never touched checkout counts as trialing for `FREE_TRIAL_DAYS` (default 30) from its creation, with no card (`auth.py`); set it to 0 to require checkout from the first screen.

### Data controller (GDPR)

Self-hosting AdelIA makes **you** the data controller (*responsable del tratamiento*) for whatever your instance processes — on the hosted SaaS at `adelia.godi.ai`, that role is Godi.AI. This matters in particular for the **Grabar consulta** (record consultation) feature: it ships with a mandatory consent gate that requires informing the attending healthcare professional, and an audio-deletion window (48h after successful transcription, 7 days on failure) as the data-minimization safeguard the feature's DPIA (`docs/legal/dpia-grabacion-consulta.md`) relies on. If you self-host, keep both active — disabling either changes your instance's legal footing, not just its UX.

The transcription provider is also part of that footing: `STT_PROVIDER` defaults to `mistral` (Voxtral, with speaker diarization, EU data residency), and can be switched to `openai` (`whisper-1` against the EU-residency endpoint, no diarization). Whichever you pick becomes *your* processor (*encargado del tratamiento*) for that audio — self-hosters choose their own processor and must reflect that choice in their own privacy information, not assume the SaaS DPIA's Mistral-specific terms carry over.

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

## Deploy (SaaS propio)

The hosted instance at `adelia.godi.ai` runs on a home server reachable only
by LAN IP, which changes on reboot (DHCP, no router access to reserve it).
`scripts/deploy-prod.sh` handles that: it discovers the host (env override →
known recent IPs → a short LAN scan), rsyncs the repo over (the root pass
never deletes, so the server keeps its own `.env.prod`; `apps`, `scripts`,
`infra` and `docs` are mirrored so a removal in git reaches the server, per
commit `89db9c6`), rebuilds `api`+`web` via
`docker compose -f infra/docker-compose.prod.yml`, and verifies the deploy
(HTTP 200 on `/es` and `/es/profesionales`, alembic version matches head).

```bash
./scripts/deploy-prod.sh                          # deploy api + web
./scripts/deploy-prod.sh api                       # deploy only api
ADELIA_HOST=192.168.1.x ./scripts/deploy-prod.sh   # force the host
```

If discovery fails, find the box with `arp -a | grep -i santiago` and pass it
via `ADELIA_HOST`. See `DEPLOY.md` for first-time server setup (Caddy/TLS).

### PWA: service worker and updates

`next build` mints one build id (`apps/web/next.config.ts`): it becomes Next's
`BUILD_ID`, `NEXT_PUBLIC_BUILD_ID` in the client bundle and the answer of
`GET /api/version`. The page registers `/sw.js?v=<id>`
(`components/sw-register.tsx`) and `public/sw.js` names its cache
`adelia-<id>`, precaches `offline.html` plus the icons, serves `/_next/static`
and `/icons` cache-first, answers navigations from the network with
`offline.html` as the only fallback, and never touches `/api` or dashboard
data. A worker for a new build waits until the user taps "Actualizar" in the
notice (no reload under a recording; a page that already runs that build
activates it silently); on activation it deletes the previous build's cache.
Open tabs poll `/api/version` when they come back to the foreground (at most
every 5 min) so an installed app learns about a deploy without a reload.
`apps/web/e2e/pwa-sw.spec.ts` covers registration, the offline fallback and
the notice; `scripts/server-verify.sh` runs it.

### Cloudflare Web Analytics (beacon): switch it off

Cloudflare injects its Web Analytics beacon into every HTML response of
`adelia.godi.ai` (`<script src="https://static.cloudflareinsights.com/beacon.min.js/..." data-cf-beacon=...>`,
which posts to `https://cloudflareinsights.com/cdn-cgi/rum`). No page or
component in this repository loads it: the only occurrences under `apps/`
are the two CSP origins in `apps/web/next.config.ts`. The
privacy policy promises no tracking, so it has to be disabled in the
Cloudflare dashboard, zone `godi.ai`:

1. **Analytics & Logs → Web Analytics** → site `adelia.godi.ai` → **Manage
   site** → disable the automatic setup (JS snippet injection), or remove the
   site from Web Analytics altogether.
2. On older dashboards the same toggle lives under **Speed → Optimization →
   Content Optimization → Cloudflare Web Analytics → Off**.
3. Check: `curl -s https://adelia.godi.ai/es | grep -c cloudflareinsights`
   must print `0`.

Until then the CSP in `apps/web/next.config.ts` allows those two origins
(`script-src https://static.cloudflareinsights.com`,
`connect-src https://cloudflareinsights.com`) so the console stays free of
the blocked-script error; remove them once the beacon is off.

## Roadmap

- **Now:** what the repository itself marks as pending.
  - Email forwarding: the Postmark webhook, the per-user alias and the dashboard page that shows it exist, but attachments are not stored (`ingestion/email_inbound.py`, "deferred to v0.2.1"). Wire them to the document pipeline, or hide the alias page until then.
  - Calibrate `patient_max_distance` (0.45 today, a noise filter) against real patient documents. Production held none on 2026-08-31 (`config.py`).
  - Replace the in-process document tasks with a worker queue (`config.py`, `doc_processing_concurrency`). Re-queueing stuck documents at boot is the current safety net.
  - Switch off the Cloudflare Web Analytics beacon (section above), then drop its two CSP origins.
  - Pre-launch ops that depend on accounts and keys outside this repository: Resend domain verification, the Postmark inbound token, the Telegram bot token (the Telegram code is merged and tested).
- **v0.2.x:** streaming transcription during a consultation (Grabar consulta today records first and transcribes after), WhatsApp ingest, `clinician_verified` provenance (the schema accepts the value; nothing writes it yet).
- **v0.3:** doctor query mode (QR + ephemeral session), Mon Espace Santé (FR) integration (today there is an import guide only), Sanidad ES (per CCAA). The agent with cards that `docs/specs/2026-07-02-adelia-v0.3-agent-mode-cards-design.md` scoped as v0.3 has already shipped.

## Contributing

See `CONTRIBUTING.md`. Use DCO sign-off (`git commit -s`). No CLA.

## Security

See `SECURITY.md` for vulnerability reporting.
