from datetime import date as date_type, datetime
from enum import Enum
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DropReason = Literal["schema_invalid", "quote_not_verbatim", "validation_error", "duplicate"]
DROP_REASONS: tuple[str, ...] = get_args(DropReason)


class ExtractionReport(BaseModel):
    """What the extractor did with the model's reply, so a thin record has a reason.

    Every entity the extractor discarded used to vanish with a `continue` and
    a log line nobody joined to a document (the audit flagged it): a child's
    record came out thinner and nothing said why. The counts separate
    "the model broke the shape" (schema_invalid, validation_error) from "the
    model invented a quote" (quote_not_verbatim) and from harmless repetition
    (duplicate), which are very different problems to fix.

    Invariant: received == kept + sum(dropped.values()). `ambiguous_quote` is
    NOT a drop: those entities are kept (their quote is verbatim) but have no
    single place in the document, see workers.extract.locate_quote.
    """

    path: Literal["json_schema", "json_object"] = "json_object"
    received: int = 0
    kept: int = 0
    dropped: dict[str, int] = Field(default_factory=lambda: dict.fromkeys(DROP_REASONS, 0))
    ambiguous_quote: int = 0
    # True when the reply carried no usable {"entities": [...]} at all, so
    # `received == 0` means "unreadable", not "the document had no facts".
    unusable_reply: bool = False

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())


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
    # User-assigned names for diarized speakers ("1" -> "Pediatra"), stored
    # in documents.metadata. None for non-consulta docs or before naming.
    speaker_names: dict[str, str] | None = None
    # Post-recording essence bullets (consulta docs only, best-effort).
    summary: str | None = None
    # Daily diary entries (Telegram-first): ISO date the entry is about.
    diary_date: str | None = None
    # What the extractor kept and discarded for this document (the audit
    # flagged the silent drops). None for documents processed before this
    # existed and for pipelines that fail before extraction.
    extraction: ExtractionReport | None = None

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
    # Whose record the question is about. None resolves to the user's default
    # profile. The router reads the age off it, which is what lets the
    # red-flag detector apply "under 3 months" (audit 3.3).
    profile_id: UUID | None = None


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
    """Who the briefing is about, as the specialist reads it first.

    `age` was an `int` fixed at 0 for every patient (audit 3.10). In
    pediatrics the age is the first determinant of every interpretation, so
    "0 años" on an 18-month-old invalidates percentiles, doses and the
    vaccination schedule at a glance, and costs the document its credibility
    in front of the professional. It is now the age in months and it is
    nullable: `age_label` renders "edad no registrada" rather than a number
    nobody entered.
    """

    name: str
    #: Age in MONTHS, or None when the profile has no date of birth.
    age_months: int | None = None
    #: "M", "F", or None when unknown. Never "?" in the payload.
    sex: str | None = None

    @property
    def age_label(self) -> str:
        if self.age_months is None:
            return "edad no registrada"
        if self.age_months < 24:
            unit = "mes" if self.age_months == 1 else "meses"
            return f"{self.age_months} {unit}"
        years = self.age_months // 12
        return f"{years} año" if years == 1 else f"{years} años"

    @property
    def sex_label(self) -> str:
        return {"M": "niño", "F": "niña"}.get(self.sex or "", "sexo no registrado")


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
    # Which child the briefing is about. None resolves to the account's
    # default profile, the same fallback the chat uses. The router checks
    # ownership before anything is written (audit 4.1).
    profile_id: UUID | None = None


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
