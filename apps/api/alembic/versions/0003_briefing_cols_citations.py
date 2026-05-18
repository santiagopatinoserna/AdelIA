"""briefing status/stale columns and briefing_citations table

Revision ID: 0003_briefing_cols_citations
Revises: 0002_chat_tables
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_briefing_cols_citations"
down_revision: Union[str, None] = "0002_chat_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CRITICAL: allow payload=None so orchestrator can INSERT a 'processing' row before the LLM runs
    op.alter_column(
        "briefings",
        "payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    )

    op.add_column(
        "briefings",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
    )
    op.create_check_constraint(
        "ck_briefings_status",
        "briefings",
        "status IN ('processing', 'ready', 'failed')",
    )
    op.add_column(
        "briefings",
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("briefings", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("briefings", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("briefings", sa.Column("html_render", sa.Text(), nullable=True))

    # CRITICAL: drop columns now carried by payload JSONB — sync ORM with DB schema
    op.drop_column("briefings", "reason_for_consult")
    op.drop_column("briefings", "generated_at")

    op.create_index(
        "idx_briefings_user_created",
        "briefings",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "briefing_citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "briefing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("briefings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("raw_quote", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_briefing_citations_briefing", "briefing_citations", ["briefing_id"])
    op.create_index("idx_briefing_citations_document", "briefing_citations", ["document_id"])


def downgrade() -> None:
    op.drop_index("idx_briefing_citations_document", table_name="briefing_citations")
    op.drop_index("idx_briefing_citations_briefing", table_name="briefing_citations")
    op.drop_table("briefing_citations")
    op.drop_index("idx_briefings_user_created", table_name="briefings")
    op.drop_column("briefings", "html_render")
    op.drop_column("briefings", "completed_at")
    op.drop_column("briefings", "error_message")
    op.drop_column("briefings", "is_stale")
    op.drop_constraint("ck_briefings_status", "briefings", type_="check")
    op.drop_column("briefings", "status")
    # restore columns dropped in upgrade (were part of 0001_initial schema)
    op.add_column(
        "briefings",
        sa.Column("reason_for_consult", sa.Text(), nullable=True),
    )
    op.add_column(
        "briefings",
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # restore NOT NULL constraint on payload
    op.alter_column(
        "briefings",
        "payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
