"""Durable blob-deletion tombstones for GDPR erasure.

Revision ID: 0013_blob_tombstones
Revises: 0012_genomic_variants
Create Date: 2026-06-10 00:00:00.000000

DELETE /users/me committed the DB erase and then deleted S3 blobs
best-effort: a crash or S3 outage in between left medical PDFs orphaned
forever, with no record to retry. Tombstones are written in the SAME
transaction as the user delete; a startup sweep retries leftovers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_blob_tombstones"
down_revision: Union[str, None] = "0012_genomic_variants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blob_tombstones",
        sa.Column("s3_key", sa.String(1024), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("blob_tombstones")
