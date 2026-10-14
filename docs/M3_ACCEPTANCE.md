# M3 Acceptance Test — Manual UI Checklist

Run AFTER `scripts/m3-acceptance.sh` exits green AND M2 acceptance is verified.

## Prereqs

- All M1+M2 env vars (AUTH_SECRET + RESEND_API_KEY + MISTRAL_API_KEY + OPENAI_API_KEY)
- `alembic upgrade head` applied — verify with `\dt chat_*` in psql, expect chat_sessions + chat_messages tables present
- At least one document with extracted entities + embedded chunks already in the DB (upload + wait for processing from M2)

## UI flow

### Test 1: New conversation + RAG path

- [ ] Navigate to `/es/dashboard/chat`
- [ ] **Verify:** sidebar shows "Sin conversaciones todavía" + "+ Nueva conversación" button
- [ ] **Verify:** header shows "Chat con tu historia clínica"
- [ ] Type "¿Qué medicamentos tomo actualmente?" in the input + press Enter
- [ ] **Verify:** input disables + button shows "Pensando…"
- [ ] **Verify:** assistant bubble appears with streaming tokens (you should see text appear progressively, not all at once)
- [ ] **Verify:** within ~10s the answer completes; footnote chips `[1] Ver fuente`, `[2] Ver fuente`, ... appear at the bottom of the assistant bubble
- [ ] Click any footnote chip
- [ ] **Verify:** navigates to `/es/dashboard/documents/<doc-id>` and shows the source document raw_text
- [ ] Go back to chat
- [ ] **Verify:** the assistant message is still there; sidebar now shows a session with default title "Nueva conversación"

### Test 2: Temporal query path

- [ ] In the same conversation, type: "Dame la curva de glucosa de los últimos 5 años"
- [ ] **Verify:** assistant responds (streaming) with a structured answer referencing specific glucose readings + dates
- [ ] **Verify:** the answer cites the underlying entities (footnote chips link to the documents containing the lab values)
- [ ] (Optional, dev tools) Check Postgres: the assistant message's `citations` JSONB array should have `chunk_id` values matching `entities.id` for the glucose observations

### Test 3: Session persistence

- [ ] Close the browser tab
- [ ] Reopen `/es/dashboard/chat`
- [ ] **Verify:** sidebar shows the conversation from Test 1 + 2
- [ ] Click the session
- [ ] **Verify:** all messages reload (user + assistant) with citations intact
- [ ] Click "+ Nueva conversación"
- [ ] **Verify:** message area clears; you can ask a question and get a separate conversation

### Test 4: Session deletion

- [ ] Hover over a session in the sidebar
- [ ] **Verify:** "×" delete button appears
- [ ] Click it
- [ ] **Verify:** session disappears from sidebar
- [ ] (Dev tools) Verify in Postgres: `SELECT deleted_at FROM chat_sessions WHERE id = '<id>'` shows a non-NULL timestamp (soft-delete)

### Test 5: Empty context / hallucination guard

- [ ] Ask a question that should have no answer: "¿Qué dijo el psiquiatra sobre mi último episodio?"
  (Replace with something you have no data on)
- [ ] **Verify:** assistant responds with "No tengo información suficiente." (per the system prompt)
- [ ] **Verify:** no citations on this response (or empty citation list)

### Test 6: Cross-user isolation

- [ ] Sign out, sign in as a different email
- [ ] Visit `/es/dashboard/chat`
- [ ] **Verify:** sidebar is empty (does NOT show the other user's sessions)
- [ ] Try to fetch the previous user's session via dev tools: `fetch('/chat/sessions/<previous-id>')`
- [ ] **Verify:** 404 returned (opaque, not 403)

## Known v0.1 / v0.1.1 limitations (acceptable)

- No parent-chunk content expansion in retrieval (small chunks 350 tokens carry enough context for chat). Tracked as v0.1.1 carry-over.
- Temporal heuristic is regex-only; complex temporal questions ("últimos 3 meses excepto enero") fall through to standard RAG. v0.2 could add an LLM-based intent classifier.
- No retry on transient Mistral 5xx in streaming. Single failed stream surfaces as an error event.
- Citation chunk_id is repurposed for entity IDs in the temporal path (since chunks aren't searched). v0.1.1 may separate the Citation schema by path type.
- No timeout on the orchestrator stream. v0.1.1 should add asyncio.wait_for(60s).
- No conversation history passed to orchestrator (one-shot per question). Multi-turn context awareness is v0.1.1.
- raw_text.find() multi-occurrence carry-over from M2-T6 orchestrator still applies. RESOLVED 2026-10-14: `locate_quote` (workers/extract.py) returns a range only for a quote that occurs exactly once; an ambiguous quote keeps its entity but gets no chunk link.

## Tagging

Once all tests pass:

```bash
git tag -a v0.1-m3 -m "M3 RAG chat (Modo A) complete: streaming + persistence + temporal"
git push origin v0.1-m3
```
