from datetime import date as date_type, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    id: UUID
    source: Literal["web", "manual"]
    mime_type: str
    s3_key: str
    raw_text: str | None
    created_at: datetime
    processed_at: datetime | None
    status: Literal["uploaded", "processing", "ready", "failed"]
    entity_count: int = 0
    chunk_count: int = 0

    model_config = ConfigDict(from_attributes=True)


def derive_status(raw_text: str | None, processed_at: datetime | None) -> Literal["processing", "ready", "failed"]:
    if processed_at and raw_text is not None:
        return "ready"
    if processed_at and raw_text is None:
        return "failed"
    return "processing"


class ExtractedEntity(BaseModel):
    """LLM-extracted entity, validated before persistence to entities table.

    raw_quote MUST appear verbatim in the source document raw_text — this is the
    anti-hallucination invariant per spec section 6.1. Extractor filters out
    entities whose raw_quote does not substring-match the input.
    """
    entity_type: Literal[
        "condition",
        "medication",
        "allergy",
        "immunization",
        "procedure",
        "observation",
        "family_history",
        "device",
        "allergen_reaction",
        "social_history",
    ]
    name: str
    value: dict | None = None
    event_date: date_type | None = None
    status: str | None = None
    coding_system: str | None = None
    code: str | None = None
    raw_quote: str
    page: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Literal[
        "patient_stated",
        "extracted_from_clinician_doc",
        "clinician_verified",
    ] = "extracted_from_clinician_doc"


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    raw_quote: str
    page: int | None = None


class ChatMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ChatSessionOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ChatSessionDetailOut(ChatSessionOut):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: UUID | None = None  # if None → create new session
    question: str = Field(min_length=1, max_length=4000)
