from datetime import date as date_type, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    id: UUID
    source: Literal["web", "manual", "consulta"]
    mime_type: str
    file_name: str
    raw_text: str | None
    created_at: datetime
    processed_at: datetime | None
    status: Literal["processing", "ready", "failed"]
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


class ChatCitation(BaseModel):
    """Citation for a chat answer.

    source_type discriminates what chunk_id points at: a chunks.id for the
    RAG path, an entities.id for the structured-temporal path (the field
    name predates the split; renaming would break persisted messages).
    """
    chunk_id: UUID
    document_id: UUID
    raw_quote: str
    page: int | None = None
    source_type: Literal["chunk", "entity"] = "chunk"


class ChatMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[ChatCitation] = Field(default_factory=list)
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
    locale: Literal["es", "en", "fr"] = "es"  # answer language


# ============================================================================
# M5: Briefing schemas
# ============================================================================


class Specialty(str, Enum):
    PEDIATRICS = "pediatrics"
    ENDOCRINOLOGY = "endocrinology"
    CARDIOLOGY = "cardiology"
    GYNECOLOGY = "gynecology"
    GASTROENTEROLOGY = "gastroenterology"
    DERMATOLOGY = "dermatology"
    GENERAL_MEDICINE = "general_medicine"
    DEFAULT = "default"


class BriefingStatus(str, Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Citation(BaseModel):
    document_id: UUID
    entity_id: UUID | None = None
    raw_quote: str = Field(min_length=1, max_length=2000)
    page: int | None = None


class ProblemItem(BaseModel):
    name: str
    status: str | None = None  # active | resolved | unknown
    onset_date: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class MedicationItem(BaseModel):
    name: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    started: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class AllergyItem(BaseModel):
    substance: str
    reaction: str | None = None
    severity: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class ImmunizationItem(BaseModel):
    name: str
    date: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class ProcedureItem(BaseModel):
    name: str
    date: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class FamilyHistoryItem(BaseModel):
    relation: str
    condition: str
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class ObservationItem(BaseModel):
    name: str           # 'HbA1c', 'BP', 'glucose'
    value: str
    unit: str | None = None
    date: str | None = None
    trend: str | None = None  # 'rising' | 'falling' | 'stable' | None
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


class QAItem(BaseModel):
    question: str
    answer: str
    citations: list[Citation]


class BriefingSections(BaseModel):
    reason_for_consult: str | None
    active_problems: list[ProblemItem]
    medications: list[MedicationItem]
    allergies: list[AllergyItem] | Literal["no_known_allergies"]
    immunizations: list[ImmunizationItem] | None  # None = hidden by specialty filter
    procedures: list[ProcedureItem]
    family_history: list[FamilyHistoryItem] | None  # None = hidden
    relevant_observations: list[ObservationItem]
    open_questions: list[QAItem]


class PatientHeader(BaseModel):
    name: str
    age: int
    sex: str


class AppliedFilter(BaseModel):
    specialty: str
    rules_version: str


class LLMMeta(BaseModel):
    model: str
    tokens_used: int
    cost_estimate_usd: float


class EvidenceCitation(BaseModel):
    """Clinical evidence citation (separate namespace from patient Citation)."""
    tag: str  # e.g. 'ev_1'
    source_id: str
    chunk_id: str
    title: str
    organization: str | None = None
    year: int | None = None
    url: str | None = None
    snippet: str


class BriefingPayload(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    locale: Literal["es", "en", "fr"] = "es"
    generated_at: datetime
    target_specialty: Specialty
    patient: PatientHeader
    sections: BriefingSections
    applied_filter: AppliedFilter
    llm_meta: LLMMeta
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)


class BriefingCreate(BaseModel):
    target_specialty: Specialty
    locale: Literal["es", "en", "fr"] = "es"


class BriefingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_specialty: Specialty
    status: BriefingStatus
    is_stale: bool
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class BriefingDetailOut(BriefingOut):
    payload: BriefingPayload | None = None
    html_render: str | None = None


# ============================================================================
# M4 ingestion surfaces
# ============================================================================


IngestionSource = Literal[
    "web", "telegram", "email", "apple_health", "ccd_import", "gdpr_response"
]


class TelegramLinkOut(BaseModel):
    user_id: UUID
    chat_id: int
    username: str | None
    linked_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TelegramLinkRequest(BaseModel):
    """Web returns a signed token; user sends /start <token> to the bot."""
    bot_url: str
    link_token: str
    expires_at: datetime


class EmailAliasOut(BaseModel):
    user_id: UUID
    alias: str  # e.g. "abc12345@in.adelia.app"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionEventOut(BaseModel):
    id: UUID
    source: IngestionSource
    document_count: int
    entity_count: int
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionImportResult(BaseModel):
    """Returned by /ingestion/apple-health/import and /ingestion/ccd/import."""
    event_id: UUID
    source: IngestionSource
    document_count: int
    entity_count: int
    elapsed_seconds: float
    sample_names: list[str] = Field(default_factory=list)  # first 5 entity names for UX


class GuideSummary(BaseModel):
    slug: str
    title: str
    description: str
    estimated_time: str | None = None


class GuideContent(GuideSummary):
    markdown: str  # full body
    front_matter: dict = Field(default_factory=dict)


class GDPRTemplateSummary(BaseModel):
    country: str  # 'ES', 'FR', 'US'
    authority: str
    legal_basis: str
    response_deadline: str
    output_language: str


class GDPRTemplateContent(GDPRTemplateSummary):
    markdown: str
