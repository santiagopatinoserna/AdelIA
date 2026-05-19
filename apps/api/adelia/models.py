# apps/api/adelia/models.py
import uuid
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger, Boolean, Column, CheckConstraint, Date, DateTime, Float, ForeignKey,
    Index, Integer, LargeBinary, String, Text, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from adelia.db import Base


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    s3_key = Column(String, nullable=False)
    raw_text = Column(Text)
    document_metadata = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    deleted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source IN ('web','manual')", name="documents_source_check"),
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024))
    chunk_index = Column(Integer, nullable=False)
    chunk_metadata = Column("metadata", JSONB)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String, nullable=False)
    coding_system = Column(String)
    code = Column(String)
    name = Column(String, nullable=False)
    value = Column(JSONB)
    event_date = Column(Date)
    status = Column(String)
    provenance = Column(String, nullable=False)
    confidence = Column(Float)
    raw_quote = Column(Text)
    page = Column(Integer)
    needs_review = Column(Boolean, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('condition','medication','allergy','immunization',"
            "'procedure','observation','family_history','device','allergen_reaction','social_history')",
            name="entities_type_check",
        ),
        CheckConstraint(
            "provenance IN ('patient_stated','extracted_from_clinician_doc','clinician_verified')",
            name="entities_provenance_check",
        ),
        Index("ix_entities_user_type_date", "user_id", "entity_type", "status", "event_date"),
    )


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_specialty: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="processing")
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_render: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    citations: Mapped[list["BriefingCitation"]] = relationship(
        "BriefingCitation", back_populates="briefing", cascade="all, delete-orphan"
    )


class BriefingCitation(Base):
    __tablename__ = "briefing_citations"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    briefing_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("briefings.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    briefing: Mapped["Briefing"] = relationship("Briefing", back_populates="citations")


class ShareLink(Base):
    __tablename__ = "share_links"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    briefing_id = Column(UUID(as_uuid=True), ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    token = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, server_default=text("false"))
    access_count = Column(Integer, server_default=text("0"))
    last_accessed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    llm_provider = Column(String)
    api_key_encrypted = Column(LargeBinary)
    default_share_ttl_seconds = Column(Integer, server_default=text("86400"))
    preferred_locale = Column(String, server_default=text("'es'"))


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False, default="Nueva conversación")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(String, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    citations = Column(JSONB)  # list of {chunk_id, document_id, raw_quote, page}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="chat_messages_role_check"),
    )


# ============================================================================
# M4 ingestion surface models
# ============================================================================


class TelegramLink(Base):
    __tablename__ = "telegram_links"
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id = Column(BigInteger, nullable=False, unique=True)
    username = Column(String(64))
    linked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmailAlias(Base):
    __tablename__ = "email_aliases"
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    alias = Column(String(128), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(32), nullable=False)
    document_count = Column(Integer, nullable=False, server_default=text("0"))
    entity_count = Column(Integer, nullable=False, server_default=text("0"))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source IN ('web', 'telegram', 'email', 'apple_health', 'ccd_import', 'gdpr_response')",
            name="ck_ingestion_events_source",
        ),
    )
