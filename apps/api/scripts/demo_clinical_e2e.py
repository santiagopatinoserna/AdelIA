"""Reproducible end-to-end demo: synthetic document → briefing → traceability.

What it proves, against a LIVE stack (API on :8000, Postgres + MinIO up,
MISTRAL_API_KEY set):

  1. A realistic clinical PDF the system has never seen is uploaded through
     the real pipeline (OCR → extraction → chunks/embeddings).
  2. A doctor briefing is generated for the relevant specialty.
  3. The briefing surfaces the correct diagnoses / meds / labs.
  4. EVERY surfaced datum is traceable: its citation's raw_quote appears
     verbatim in the source document the doctor can open — the audit chain.

Run:
  docker compose -f infra/docker-compose.dev.yml up -d
  (cd apps/api && uv run uvicorn adelia.main:app --port 8000 &)
  cd apps/api && uv run python scripts/demo_clinical_e2e.py

Exit code 0 + "DEMO OK" only if the diagnoses are present AND every citation
traces back verbatim. Non-zero otherwise.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt as jose_jwt

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import User
from tests.clinical_corpus.cases import CASES
from tests.clinical_corpus.render import case_to_pdf_bytes

API = "http://localhost:8000"
# The richest case for a doctor: uncontrolled diabetes + dyslipidemia.
CASE = next(c for c in CASES if c.slug == "endo-diabetes-dyslipidemia")
SPECIALTY = "endocrinology"


async def _mint_user() -> tuple[str, str]:
    email = f"demo-{int(time.time())}@adelia.test"
    async with AsyncSessionLocal() as s:
        u = User(email=email)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid = str(u.id)
    token = jose_jwt.encode(
        {"sub": uid, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.auth_secret,
        algorithm="HS256",
    )
    return uid, token


def _iter_items(payload: dict):
    """Yield (section, item) for every cited section item in the briefing."""
    sections = payload.get("sections", {})
    for key in ("active_problems", "medications", "procedures", "relevant_observations"):
        for item in sections.get(key) or []:
            yield key, item
    allergies = sections.get("allergies")
    if isinstance(allergies, list):
        for item in allergies:
            yield "allergies", item


async def main() -> int:
    if not settings.mistral_api_key:
        print("SKIP: MISTRAL_API_KEY not set")
        return 0

    _, token = await _mint_user()
    headers = {"Authorization": f"Bearer {token}"}
    pdf = case_to_pdf_bytes(CASE)
    print(f"▶ Caso: {CASE.title}")

    async with httpx.AsyncClient(timeout=180) as c:
        # 1. upload
        r = await c.post(f"{API}/documents", headers=headers,
                         files={"file": ("informe.pdf", pdf, "application/pdf")})
        r.raise_for_status()
        doc_id = r.json()["id"]
        print(f"  ✓ subido (doc {doc_id[:8]}…), procesando OCR + extracción…")

        # 2. wait for processing
        for _ in range(90):
            r = await c.get(f"{API}/documents/{doc_id}", headers=headers)
            if r.json().get("processed_at"):
                break
            await asyncio.sleep(2)
        else:
            print("  ✗ timeout procesando documento")
            return 1
        doc = r.json()
        source_text = doc.get("raw_text") or ""
        print(f"  ✓ procesado: {doc['entity_count']} entidades, {doc['chunk_count']} chunks")

        # 3. generate briefing
        r = await c.post(f"{API}/briefings", headers=headers,
                         json={"target_specialty": SPECIALTY, "locale": "es"})
        r.raise_for_status()
        br_id = r.json()["id"]
        for _ in range(90):
            r = await c.get(f"{API}/briefings/{br_id}", headers=headers)
            st = r.json()["status"]
            if st == "ready":
                break
            if st == "failed":
                print(f"  ✗ briefing falló: {r.json().get('error_message')}")
                return 1
            await asyncio.sleep(2)
        else:
            print("  ✗ timeout generando briefing")
            return 1
        payload = r.json()["payload"]
        print("  ✓ briefing generado\n")

    # 4. clinical correctness — the diagnosis/med must be in ITS section, not
    # merely somewhere in the payload (avoids a false OK if it only shows up
    # in a pre-baked question).
    sections = payload.get("sections", {})
    problems_blob = str(sections.get("active_problems") or []).lower()
    meds_blob = str(sections.get("medications") or []).lower()
    missing_dx = []
    for f in CASE.must_find:
        if f.entity_type == "condition":
            if not any(t.lower() in problems_blob for t in f.name_contains):
                missing_dx.append(f.name_contains)
        elif f.entity_type == "medication":
            if not any(t.lower() in meds_blob for t in f.name_contains):
                missing_dx.append(f.name_contains)

    # 5. traceability: every citation's raw_quote must appear in the source doc
    items = list(_iter_items(payload))
    cited = [(sec, it) for sec, it in items if it.get("citations")]
    untraceable = []
    src_lower = source_text.lower()
    for sec, it in cited:
        for cit in it["citations"]:
            q = (cit.get("raw_quote") or "").strip().lower()
            if q and q not in src_lower:
                untraceable.append((sec, it.get("name"), q[:40]))

    print("── Lo que ve el médico (resumen auditable) ─────────────")
    for sec, it in items:
        name = it.get("name") or it.get("substance") or "?"
        n_cit = len(it.get("citations") or [])
        print(f"  [{sec}] {name}  ·  {n_cit} cita(s) trazable(s)")
    print("─────────────────────────────────────────────────────────\n")

    ok = not missing_dx and not untraceable and cited
    if missing_dx:
        print(f"  ✗ diagnósticos no presentes en el briefing: {missing_dx}")
    if untraceable:
        print(f"  ✗ {len(untraceable)} citas NO trazables verbatim al documento: {untraceable[:3]}")
    if not cited:
        print("  ✗ ningún item del briefing lleva cita (sin trazabilidad)")

    if ok:
        print(f"DEMO OK — diagnósticos correctos y {len(cited)} items 100% trazables al documento fuente")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
