# apps/api/adelia/models.py
import uuid

from sqlalchemy import (
    Column, String, Text, DateTime, Date, Integer, Float, Boolean,
    ForeignKey, CheckConstraint, LargeBinary, Index, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    target_specialty = Column(String, nullable=False)
    reason_for_consult = Column(Text)
    payload = Column(JSONB, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


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
