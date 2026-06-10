"""Multi-profile support — user can manage N profiles (self, child, parent).

Revision ID: 0006_profiles
Revises: 0005_evidence_chunks
Create Date: 2026-05-18 00:00:00.000000

Approach: introduce `profiles` table. Each User has at least 1 profile (default
'self'). Documents + Entities + Chunks gain optional `profile_id` FK; legacy
rows with NULL profile_id are interpreted as belonging to the user's default
profile (lazy migration).

This migration is ADDITIVE — does NOT break existing v0.1 data. The profile_id
column is nullable and a backfill job populates default profiles for existing
users separately (see scripts/backfill_profiles.py — v0.2.1).

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_profiles"
down_revision: Union[str, None] = "0005_evidence_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False, server_default="self"),  # self|child|parent|spouse|sibling|other
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=8), nullable=True),  # M | F | other
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_profiles_relationship",
        "profiles",
        "relationship IN ('self', 'child', 'parent', 'spouse', 'sibling', 'other')",
    )
    op.create_index("idx_profiles_user", "profiles", ["user_id"])
    op.create_index(
        "idx_profiles_one_default_per_user",
        "profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
    )

    # Add optional profile_id to existing tables. Backfill happens separately.
    for table in ("documents", "entities", "chunks", "briefings"):
        op.add_column(
            table,
            sa.Column(
                "profile_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("profiles.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(
            f"idx_{table}_profile",
            table,
            ["profile_id"],
            postgresql_where=sa.text("profile_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in ("briefings", "chunks", "entities", "documents"):
        op.drop_index(f"idx_{table}_profile", table_name=table)
        op.drop_column(table, "profile_id")
    op.drop_index("idx_profiles_one_default_per_user", table_name="profiles")
    op.drop_index("idx_profiles_user", table_name="profiles")
    op.drop_constraint("ck_profiles_relationship", "profiles", type_="check")
    op.drop_table("profiles")
