"""initial schema v0.1

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("s3_key", sa.String(), nullable=False),
        sa.Column("raw_text", sa.Text()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source IN ('web','manual')", name="documents_source_check"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("coding_system", sa.String()),
        sa.Column("code", sa.String()),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("value", postgresql.JSONB()),
        sa.Column("event_date", sa.Date()),
        sa.Column("status", sa.String()),
        sa.Column("provenance", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("raw_quote", sa.Text()),
        sa.Column("page", sa.Integer()),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "entity_type IN ('condition','medication','allergy','immunization',"
            "'procedure','observation','family_history','device','allergen_reaction','social_history')",
            name="entities_type_check",
        ),
        sa.CheckConstraint(
            "provenance IN ('patient_stated','extracted_from_clinician_doc','clinician_verified')",
            name="entities_provenance_check",
        ),
    )
    op.create_index(
        "ix_entities_user_type_date",
        "entities",
        ["user_id", "entity_type", "status", "event_date"],
    )

    op.create_table(
        "briefings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_specialty", sa.String(), nullable=False),
        sa.Column("reason_for_consult", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("briefing_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_share_links_token", "share_links", ["token"], unique=True)

    op.create_table(
        "user_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("llm_provider", sa.String()),
        sa.Column("api_key_encrypted", postgresql.BYTEA()),
        sa.Column("default_share_ttl_seconds", sa.Integer(), server_default=sa.text("86400")),
        sa.Column("preferred_locale", sa.String(), server_default=sa.text("'es'")),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_index("ix_share_links_token", table_name="share_links")
    op.drop_table("share_links")
    op.drop_table("briefings")
    op.drop_index("ix_entities_user_type_date", table_name="entities")
    op.drop_table("entities")
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
    op.drop_table("chunks")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
