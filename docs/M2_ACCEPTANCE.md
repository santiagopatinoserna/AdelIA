# M2 Acceptance Test — Manual UI Checklist

Run this AFTER `scripts/m2-acceptance.sh` exits green AND M1 acceptance is verified.

## Prereqs

In addition to M1 prereqs, you need:

- `OPENAI_API_KEY` in `apps/api/.env` (for Whisper transcription on audio uploads)
- `MISTRAL_API_KEY` is already required for OCR + now also entity extraction + embeddings

## UI flow

### Test 1: PDF upload → entity + chunk counts

- [ ] Sign in (per M1 flow)
- [ ] Upload a real PDF lab result or clinical note (not the empty fixture)
- [ ] Wait until the dashboard shows status `Listo`
- [ ] Click the document
- [ ] **Verify:** beneath the timestamp, you see `"N entidades · M chunks"` where both are non-zero
- [ ] **Verify:** raw_text shows the OCR'd content
- [ ] (Optional, dev tools) Open Postgres and run:
  ```sql
  SELECT entity_type, name, raw_quote FROM entities WHERE document_id = '<your doc id>' LIMIT 10;
  SELECT chunk_index, jsonb_array_length(metadata->'entity_ids') AS n_entities FROM chunks WHERE document_id = '<your doc id>' ORDER BY chunk_index LIMIT 10;
  ```
- [ ] **Verify:** entities have non-empty `raw_quote` AND those quotes appear in raw_text
- [ ] **Verify:** chunks have non-null `embedding` (1024-dim)

### Test 2: Audio upload → transcript + entities

- [ ] Record 30-60 seconds of yourself reading a medical note (or use any sample medical podcast clip < 25 MB)
- [ ] Upload the .mp3/.wav/.m4a
- [ ] Wait for status `Listo` (~20-30s for Whisper + extract + embed)
- [ ] **Verify:** detail page raw_text contains the transcript
- [ ] **Verify:** if your audio mentioned a medication, condition, or lab, it should appear in `entity_count` ≥ 1
- [ ] **Verify:** chunk_count > 0

### Test 3: Anti-hallucination invariant

- [ ] Pick any entity from the entities table for a real document
- [ ] **Verify:** the `raw_quote` field appears literally (substring) in the document's `raw_text`. If the LLM tried to hallucinate a quote, our extract.py filter would have dropped it before persistence.

### Test 4: Stage failure isolation

- [ ] Temporarily unset `OPENAI_API_KEY` in `apps/api/.env` and restart `pnpm dev:api`
- [ ] Upload an audio file
- [ ] **Verify:** status flips to `Error` (`derive_status` returns "failed")
- [ ] **Verify:** `processed_at` is set (document is not stuck in processing)
- [ ] **Verify:** server log lines show `process_document failed for document_id=...` exception trace
- [ ] Re-set the key and re-upload — pipeline should now succeed.

## Known v0.1 / v0.2 limitations (acceptable)

- No retry on transient Mistral 5xx — single failed call drops the document to `failed`. v0.2 retry queue.
- Embedding batching is one Mistral call per document (fine for documents < 50 chunks). For very long docs, batch into multiple calls in v0.2.
- No client-side polling on detail page — manually reload after `~20-30s` for the full pipeline.
- Whisper API limit: 25 MB per file. Backend rejects >50 MB at upload (T8 M1) but Whisper itself caps tighter; long audio will fail at transcribe stage.
- `entity_ranges` uses `raw_text.find()` first-occurrence: entities citing repeated phrases may be mis-tagged to the first occurrence in chunk metadata. v0.1.1 carry-over with same root cause as the T4 chunker fix. RESOLVED 2026-10-14: `locate_quote` (workers/extract.py) returns a range only for a quote that occurs exactly once; an ambiguous quote keeps its entity but gets no chunk link.

## Tagging

Once all tests pass:

```bash
git tag -a v0.1-m2 -m "M2 RAG substrate complete: transcribe + extract + chunk + embed"
git push origin v0.1-m2
```

If any test fails, do NOT promote `v0.1-m2-rc1` to `v0.1-m2`.
