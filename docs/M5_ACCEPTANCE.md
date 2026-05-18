# M5 — Briefing Generator: Frontend Acceptance Checklist

> **Pre-requisites:** docker compose up + alembic upgrade head + valid MISTRAL_API_KEY in env.
> Run `bash scripts/m5-acceptance.sh` first to confirm backend works headlessly.

## Manual UI flow

- [ ] Open `http://localhost:3000/es/dashboard/briefings`. Page loads. If user has no briefings, see empty state copy ("Aún no has generado ningún briefing").

- [ ] Click **"Crear nuevo briefing"** button. Routes to `/es/dashboard/briefings/new`.

- [ ] Specialty dropdown shows 8 options + "Otra / No listada" (default). All labels ES.

- [ ] Select "Endocrinología". Click **"Generar briefing"**. Routes to `/es/dashboard/briefings/{id}` with status "Generando…" badge.

- [ ] Detail page polls every 2 seconds (Network tab shows GET /briefings/{id} every ~2s).

- [ ] Within 30-45 seconds, status flips to "Listo". HTML render appears with sections:
  - **Reason for consult** (if provided)
  - **Active problems** (or "No active problems recorded.")
  - **Current medications**
  - **Allergies** (or "No known allergies." if user has no allergy entities)
  - **Procedures**
  - **Relevant observations** (whitelisted: HbA1c, glucose, TSH, T4, T3, cortisol, vitamin_D for endocrinology)
  - **Open questions** (Q&A pre-baker, 3-5 items expected)

- [ ] Verify **Immunizations** section is NOT shown (default rule for endocrinology).

- [ ] Verify **Family history** section IS shown (endocrinology rule says include).

- [ ] Provenance badges visible next to each item (🟡 for extracted, 🟠 for patient-stated).

- [ ] Citation footnotes appear as `<sup>[1]</sup>` etc. Clicking toggles red color (M5 visual cue; full source-doc highlight is v0.1.1).

- [ ] Disclaimer footer present: "AI-generated briefing. Verify all clinical findings with the source documents. AdelIA is a personal documentation tool, not a medical device."

## Specialty filter tests

- [ ] Create a new briefing with specialty "Pediatría". Immunizations section APPEARS. Family history section HIDDEN.

- [ ] Create a briefing with "Otra / No listada" (default). Immunizations + Family history BOTH HIDDEN. All observations visible (no whitelist).

## Stale flag flow

- [ ] After creating a briefing successfully, go to `/es/dashboard` (documents page) and upload a new document.

- [ ] Wait until it processes (badge "Procesado").

- [ ] Go back to `/es/dashboard/briefings`. The previous briefing card shows **"stale"** badge.

- [ ] Open the stale briefing. **Yellow banner** appears at the top: "Has subido data nueva desde que generaste este briefing. ¿Regenerar?"

- [ ] Click **"Regenerar"**. Routes to a NEW briefing page with status "Generando…" — original briefing remains accessible.

- [ ] Wait for completion. New briefing reflects the newly-uploaded data.

## Cross-user isolation

- [ ] Open browser DevTools. Note a briefing ID from your account.
- [ ] Log out, log in as different user, manually navigate to `/es/dashboard/briefings/{stolen-id}`.
- [ ] Page shows error ("Error: briefings.getById: 404"). No data leaks.

## Error handling

- [ ] (Optional, requires test fixture) Force a briefing failure by temporarily unsetting MISTRAL_API_KEY before regenerate. Status flips to "Falló" with error banner showing the message.

## Cleanup

- [ ] Soft-delete a briefing via API or future delete button. List page no longer shows it. Direct URL → 404.

---

If all checks pass: tag `v0.1-m5-rc1` and proceed to M4 (ingestion surfaces) or M6 (sharing + deploy) per ROADMAP.
