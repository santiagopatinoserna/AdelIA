"""telegram_links + email_aliases + ingestion_events tables

Revision ID: 0004_ingestion_surfaces
Revises: 0003_briefing_cols_citations
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_ingestion_surfaces"
down_revision: Union[str, None] = "0003_briefing_cols_citations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "email_aliases",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("alias", sa.String(length=128), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_email_aliases_alias", "email_aliases", ["alias"])

    op.create_table(
        "ingestion_events",
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
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_ingestion_events_source",
        "ingestion_events",
        "source IN ('web', 'telegram', 'email', 'apple_health', 'ccd_import', 'gdpr_response')",
    )
    op.create_index(
        "idx_ingestion_events_user",
        "ingestion_events",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_ingestion_events_user", table_name="ingestion_events")
    op.drop_constraint("ck_ingestion_events_source", "ingestion_events", type_="check")
    op.drop_table("ingestion_events")
    op.drop_index("idx_email_aliases_alias", table_name="email_aliases")
    op.drop_table("email_aliases")
    op.drop_table("telegram_links")
