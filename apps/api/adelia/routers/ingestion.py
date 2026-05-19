"""Ingestion router — M4 surfaces.

Endpoints:
- GET  /ingestion/guides                       → list platform guides
- GET  /ingestion/guides/{slug}                → full guide markdown + frontmatter
- GET  /ingestion/gdpr-templates               → list GDPR/HIPAA templates
- GET  /ingestion/gdpr-templates/{country}     → full template markdown
- GET  /ingestion/events                       → user's audit log of ingestion batches
- POST /ingestion/apple-health/import          → parse export.xml from uploaded ZIP, bulk-insert entities
- POST /ingestion/ccd/import                   → parse CCD XML, bulk-insert entities

Telegram + email webhooks live in a separate `ingestion_webhooks.py` router (deferred —
needs Telegram BotFather token + Postmark Inbound setup which require user OPS).

Cross-user isolation: all routes use Depends(get_current_user_id).
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import get_db
from adelia.ingestion.apple_health_parser import parse_health_records
from adelia.ingestion.ccd_parser import parse_ccd
from adelia.ingestion.content_loader import (
    list_gdpr_templates,
    list_guides,
    load_gdpr_template,
    load_guide,
)
from adelia.models import Document, Entity, IngestionEvent
from adelia.schemas import (
    GDPRTemplateContent,
    GDPRTemplateSummary,
    GuideContent,
    GuideSummary,
    IngestionEventOut,
    IngestionImportResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion"])


_MAX_IMPORT_FILE_SIZE = 200 * 1024 * 1024  # 200MB safety cap (matches M1 limit)


# ----------------------------------------------------------------------------
# Guides
# ----------------------------------------------------------------------------


@router.get("/guides", response_model=list[GuideSummary])
async def list_ingestion_guides(_user_id: UUID = Depends(get_current_user_id)):
    """List all platform import guides (5 in v0.1)."""
    return [
        GuideSummary(
            slug=g.slug,
            title=g.title,
            description=g.description,
            estimated_time=g.estimated_time,
        )
        for g in list_guides()
    ]


@router.get("/guides/{slug}", response_model=GuideContent)
async def get_ingestion_guide(slug: str, _user_id: UUID = Depends(get_current_user_id)):
    """Full markdown content + frontmatter for a platform guide."""
    guide = load_guide(slug)
    if guide is None:
        raise HTTPException(status_code=404, detail="Guide not found")
    return GuideContent(
        slug=guide.slug,
        title=guide.title,
        description=guide.description,
        estimated_time=guide.estimated_time,
        markdown=guide.markdown,
        front_matter=guide.front_matter,
    )


# ----------------------------------------------------------------------------
# GDPR/HIPAA templates
# ----------------------------------------------------------------------------


@router.get("/gdpr-templates", response_model=list[GDPRTemplateSummary])
async def list_gdpr_template_endpoint(_user_id: UUID = Depends(get_current_user_id)):
    """List all GDPR/HIPAA request templates (3 countries in v0.1)."""
    return [
        GDPRTemplateSummary(
            country=t.country,
            authority=t.authority,
            legal_basis=t.legal_basis,
            response_deadline=t.response_deadline,
            output_language=t.output_language,
        )
        for t in list_gdpr_templates()
    ]


@router.get("/gdpr-templates/{country}", response_model=GDPRTemplateContent)
async def get_gdpr_template(country: str, _user_id: UUID = Depends(get_current_user_id)):
    """Full markdown content for a GDPR/HIPAA template by country code."""
    tpl = load_gdpr_template(country)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return GDPRTemplateContent(
        country=tpl.country,
        authority=tpl.authority,
        legal_basis=tpl.legal_basis,
        response_deadline=tpl.response_deadline,
        output_language=tpl.output_language,
        markdown=tpl.markdown,
    )


# ----------------------------------------------------------------------------
# Ingestion events (audit log)
# ----------------------------------------------------------------------------


@router.get("/events", response_model=list[IngestionEventOut])
async def list_ingestion_events(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Audit log: every ingestion batch (Apple Health import, CCD upload, etc.)."""
    stmt = (
        select(IngestionEvent)
        .where(IngestionEvent.user_id == user_id)
        .order_by(IngestionEvent.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ----------------------------------------------------------------------------
# Apple Health import
# ----------------------------------------------------------------------------


@router.post(
    "/apple-health/import",
    status_code=status.HTTP_201_CREATED,
    response_model=IngestionImportResult,
)
async def import_apple_health(
    file: Annotated[UploadFile, File(description="export.zip from Apple Health")],
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Parse Apple Health export.zip and bulk-create observation entities.

    Reads `export.xml` from the zip (stream-parsing inside the parser to bound memory).
    Creates ONE Document row marking the import batch, then N Entity rows.
    """
    if file.content_type not in {"application/zip", "application/x-zip-compressed"}:
        raise HTTPException(status_code=400, detail="Expected a ZIP archive")

    body = await file.read()
    if len(body) > _MAX_IMPORT_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 200MB limit")

    start = time.monotonic()

    # Open zip, locate export.xml
    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    export_xml_name = next(
        (n for n in zf.namelist() if n.lower().endswith("export.xml")),
        None,
    )
    if export_xml_name is None:
        raise HTTPException(status_code=400, detail="export.xml not found in archive")

    # Create batch Document row. Pre-assign UUID so tests with mocked DB also work.
    batch_doc = Document(
        id=uuid4(),
        user_id=user_id,
        source="manual",  # M4 extends documents.source enum in v0.1.1; reuse 'manual' for now
        mime_type="application/xml",
        s3_key=f"apple-health-import/{uuid4()}.xml",
        raw_text=f"Apple Health import batch from {file.filename}",
        processed_at=datetime.now(timezone.utc),
    )
    db.add(batch_doc)
    await db.flush()

    entity_count = 0
    sample_names: list[str] = []

    with zf.open(export_xml_name) as xml_stream:
        for record in parse_health_records(xml_stream):
            ent = Entity(
                user_id=user_id,
                document_id=batch_doc.id,
                entity_type="observation",
                name=record.name,
                value={
                    "value": record.value,
                    "unit": record.unit,
                    "source": record.source_name,
                    "apple_type": record.apple_type,
                },
                event_date=record.event_date,
                provenance="patient_stated",
                raw_quote=record.raw_quote,
            )
            db.add(ent)
            entity_count += 1
            if len(sample_names) < 5:
                sample_names.append(record.name)
            # Bulk flush every 500 records
            if entity_count % 500 == 0:
                await db.flush()

    # Log ingestion event. Pre-assign UUID for mocked-DB test compatibility.
    event = IngestionEvent(
        id=uuid4(),
        user_id=user_id,
        source="apple_health",
        document_count=1,
        entity_count=entity_count,
    )
    db.add(event)
    await db.flush()

    await db.commit()

    elapsed = time.monotonic() - start
    logger.info(
        "apple_health import user=%s entities=%d elapsed=%.2fs",
        user_id,
        entity_count,
        elapsed,
    )

    return IngestionImportResult(
        event_id=event.id,
        source="apple_health",
        document_count=1,
        entity_count=entity_count,
        elapsed_seconds=elapsed,
        sample_names=sample_names,
    )


# ----------------------------------------------------------------------------
# CCD import
# ----------------------------------------------------------------------------


@router.post(
    "/ccd/import",
    status_code=status.HTTP_201_CREATED,
    response_model=IngestionImportResult,
)
async def import_ccd(
    file: Annotated[UploadFile, File(description="CCD XML from patient portal")],
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Parse C-CDA XML and bulk-create entities.

    Compatible with MyChart, Cerner, Allscripts, Athena, eClinicalWorks output.
    """
    if file.content_type not in {"application/xml", "text/xml", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Expected an XML file")

    body = await file.read()
    if len(body) > _MAX_IMPORT_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 200MB limit")

    start = time.monotonic()
    try:
        doc = parse_ccd(io.BytesIO(body))
    except Exception as e:
        logger.exception("CCD parse failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid CCD: {e}")

    batch_doc = Document(
        id=uuid4(),
        user_id=user_id,
        source="manual",  # M4 extends source enum v0.1.1
        mime_type="application/xml",
        s3_key=f"ccd-import/{uuid4()}.xml",
        raw_text=f"CCD import: {doc.patient.given_name or ''} {doc.patient.family_name or ''}",
        processed_at=datetime.now(timezone.utc),
    )
    db.add(batch_doc)
    await db.flush()

    sample_names: list[str] = []
    for entry in doc.entries:
        ent = Entity(
            user_id=user_id,
            document_id=batch_doc.id,
            entity_type=entry.entity_type,
            name=entry.name,
            coding_system=entry.coding_system,
            code=entry.code,
            value=entry.value or {},
            event_date=entry.event_date,
            provenance="extracted_from_clinician_doc",
            raw_quote=entry.raw_quote,
        )
        db.add(ent)
        if len(sample_names) < 5:
            sample_names.append(entry.name)

    event = IngestionEvent(
        id=uuid4(),
        user_id=user_id,
        source="ccd_import",
        document_count=1,
        entity_count=len(doc.entries),
    )
    db.add(event)
    await db.commit()

    elapsed = time.monotonic() - start
    logger.info(
        "ccd import user=%s entities=%d elapsed=%.2fs",
        user_id,
        len(doc.entries),
        elapsed,
    )

    return IngestionImportResult(
        event_id=event.id,
        source="ccd_import",
        document_count=1,
        entity_count=len(doc.entries),
        elapsed_seconds=elapsed,
        sample_names=sample_names,
    )
