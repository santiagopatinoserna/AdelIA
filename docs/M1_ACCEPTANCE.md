# M1 Acceptance Test — Manual UI Checklist

Run this AFTER `scripts/m1-acceptance.sh` exits green.

## Setup

1. Headless prereqs (covered by `scripts/m1-acceptance.sh`):
   - `pnpm dev:infra` — Postgres + MinIO running
   - `uv --directory apps/api run alembic upgrade head` — schema applied
   - `apps/api/.env` has `AUTH_SECRET` + `MISTRAL_API_KEY`
   - `apps/web/.env` has `AUTH_SECRET` (matching) + `RESEND_API_KEY` + `NEXT_PUBLIC_API_URL=http://localhost:8000`
2. Servers:
   - `pnpm dev:api` — FastAPI on `http://localhost:8000`
   - `pnpm dev:web` — Next.js on `http://localhost:3000`

## Manual UI Flow

### Test 1: Home page renders ES content

- [ ] Open `http://localhost:3000/es`
- [ ] **Verify**: page title is "AdelIA"
- [ ] **Verify**: hero text reads `"Tu historia clínica, tuya. Análisis IA en 2 modos."`
- [ ] **Verify**: subhero reads `"Self-analysis libre + briefing portable para cualquier especialista."`
- [ ] **Verify**: CTA button reads `"Empezar"`

### Test 2: Sign-in flow

- [ ] Click `Empezar`
- [ ] **Verify**: redirect to `http://localhost:3000/es/signin` (no session)
- [ ] **Verify**: page shows email input + `"Enviar magic link"` button
- [ ] Enter your email
- [ ] Click `"Enviar magic link"`
- [ ] **Verify**: page shows redirect to `/api/auth/verify-request` (Auth.js default)
- [ ] **Verify**: email arrives in inbox within ~30s (from `noreply@adelia.godi.ai` — domain must be verified in Resend)
- [ ] Click magic link
- [ ] **Verify**: redirect lands on `http://localhost:3000/es/dashboard`

### Test 3: Empty dashboard

- [ ] **Verify**: dashboard title reads `"Mis documentos"`
- [ ] **Verify**: shows `"Aún no has subido nada"` empty state (assuming first-time user)
- [ ] **Verify**: top-right `"Subir archivo"` button visible

### Test 4: Upload flow

- [ ] Click `"Subir archivo"`
- [ ] **Verify**: redirect to `/es/dashboard/upload`
- [ ] **Verify**: page title is `"Subir documento"`
- [ ] **Verify**: drag-drop zone reads `"Arrastra un PDF, imagen o audio aquí"` + `"o"` + `"Elige un archivo"` button
- [ ] Drag a small PDF onto the drop zone (or use file picker)
- [ ] **Verify**: status text changes to `"Subiendo…"` (amber color)
- [ ] **Verify**: redirect lands on `/es/dashboard` within 5s
- [ ] **Verify**: new document card appears with status badge `"Procesando…"` (amber)

### Test 5: OCR completion

- [ ] Wait 5–15 seconds
- [ ] Reload `/es/dashboard`
- [ ] **Verify**: document card status badge is now `"Listo"` (green)
- [ ] Click the document card
- [ ] **Verify**: redirect lands on `/es/dashboard/documents/<uuid>`
- [ ] **Verify**: page shows the original filename + `"Listo"` badge + ISO timestamp
- [ ] **Verify**: `<pre>` block shows extracted text from the PDF (non-empty, recognizable from the source)

### Test 6: Failure mode (mime not allowed)

- [ ] Try to upload a `.docx` file
- [ ] **Verify**: error message appears in upload zone (rose color), text contains `415`

### Test 7: Cross-user isolation

- [ ] Sign out (manually clear session cookies, or use a private window)
- [ ] Sign in as a different email
- [ ] **Verify**: dashboard for the new user is empty (does NOT show the previous user's documents)
- [ ] Try to access the previous user's document URL `/es/dashboard/documents/<previous-uuid>` directly
- [ ] **Verify**: returns 404 (not 403 — opaque error per spec)

### Test 8: Browser console clean

- [ ] On any page, open DevTools console
- [ ] **Verify**: no red errors. Warnings about React strict mode double-renders are acceptable in dev.

## Tagging

Once all tests pass:

```bash
git tag -a v0.1-m1 -m "M1 foundation complete: full v0.1 backend + frontend"
git push origin v0.1-m1
```

If any test fails, file an issue + open a fix branch. Do NOT bump from `v0.1-m1-rc1` to `v0.1-m1` until all 8 tests pass.

## Known v0.1 limitations (acceptable, not failures)

- No auto-poll on document detail page — manual reload required for `processing → ready` transition.
- Spanish UI only. EN + FR strings ship in v0.1.1.
- Error display uses raw status codes (e.g., "Error: status 415"). Polish in v0.1.1.
- `pages.signIn` and `signin redirectTo` hardcoded to `/es/...` (Auth.js v5 limitation).
- No pagination on `GET /documents` — fetches all of a user's docs. v0.1.1 will add cursor pagination.
- Storage tests use live MinIO (no moto). Document tests gated with `skipif(True)` — toggle to enable when running locally.
