"""evidence_chunks table for dual-RAG (clinical guidelines + papers)

Revision ID: 0005_evidence_chunks
Revises: 0004_ingestion_surfaces
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from pgvector.sqlalchemy import Vector


revision: str = "0005_evidence_chunks"
down_revision: Union[str, None] = "0004_ingestion_surfaces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),  # 'guideline' | 'paper' | 'protocol' | 'reference'
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("organization", sa.String(length=128)),  # 'ADA', 'NICE', 'AHA', 'WHO'
        sa.Column("publication_year", sa.Integer()),
        sa.Column("url", sa.String(length=1024)),
        sa.Column("specialties", postgresql.JSONB()),  # array of specialty tags as JSONB
        sa.Column("license", sa.String(length=64)),  # 'public', 'creative_commons', 'fair_use'
        sa.Column("language", sa.String(length=8), server_default="en"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_check_constraint(
        "ck_evidence_sources_type",
        "evidence_sources",
        "source_type IN ('guideline', 'paper', 'protocol', 'reference')",
    )
    op.create_index("idx_evidence_sources_specialties", "evidence_sources", ["specialties"], postgresql_using="gin")  # JSONB GIN index

    op.create_table(
        "evidence_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSONB()),  # section, page, citation_anchor
        sa.Column("embedding", Vector(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_evidence_chunks_source", "evidence_chunks", ["source_id"])
    # HNSW pgvector index for cosine similarity
    op.execute(
        "CREATE INDEX idx_evidence_chunks_embedding ON evidence_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_evidence_chunks_embedding")
    op.drop_index("idx_evidence_chunks_source", table_name="evidence_chunks")
    op.drop_table("evidence_chunks")
    op.drop_index("idx_evidence_sources_specialties", table_name="evidence_sources")
    op.drop_constraint("ck_evidence_sources_type", "evidence_sources", type_="check")
    op.drop_table("evidence_sources")
