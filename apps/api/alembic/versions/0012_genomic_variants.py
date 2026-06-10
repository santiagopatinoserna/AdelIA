"""Persist matched genomic variants — stop re-uploading 20MB files.

Revision ID: 0012_genomic_variants
Revises: 0011_gdpr_cascade
Create Date: 2026-06-10 00:00:00.000000

Data minimization by design: only the ~20 clinically-actionable matches
are stored, never the raw 600k-SNP file. Re-upload replaces the set.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0012_genomic_variants"
down_revision: Union[str, None] = "0011_gdpr_cascade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "genomic_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rsid", sa.String(32), nullable=False),
        sa.Column("gene", sa.String(64)),
        sa.Column("user_genotype", sa.String(8), nullable=False),
        sa.Column("risk_alleles", postgresql.JSONB(), nullable=False),
        sa.Column("zygosity", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("phenotype", sa.Text(), nullable=False),
        sa.Column("actionability", sa.Text()),
        sa.Column("evidence_level", sa.Text()),
        sa.Column("url", sa.String(1024)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_genomic_variants_user", "genomic_variants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_genomic_variants_user", table_name="genomic_variants")
    op.drop_table("genomic_variants")
