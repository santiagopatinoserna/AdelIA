"""Consulta recording: consent_events, source='consulta', tombstone grace.

Revision ID: 0015_consulta_recording
Revises: 0014_subscriptions

consent_events is the append-only RGPD accountability log for consultation
recordings (who informed the professional, when, under which policy text).
Deliberately minimal: NO doctor name/center (data minimization). Deleted in
cascade with the user account. blob_tombstones.not_before adds a deferred
deletion window (48h audio grace) — NULL keeps today's immediate semantics.

Note: downgrade() fails if any documents.source='consulta' rows still exist —
recreating documents_source_check without 'consulta' rejects that existing
data (the constraint isn't created NOT VALID). Purge/migrate those rows first.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_consulta_recording"
down_revision: Union[str, None] = "0014_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("documents_source_check", "documents", type_="check")
    op.create_check_constraint(
        "documents_source_check", "documents", "source IN ('web','manual','consulta')"
    )
    op.create_table(
        "consent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "profile_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('recording_informed_professional','recording_declined')",
            name="ck_consent_events_type",
        ),
    )
    op.create_index("ix_consent_events_user_id", "consent_events", ["user_id"])
    op.add_column(
        "blob_tombstones",
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blob_tombstones", "not_before")
    op.drop_index("ix_consent_events_user_id", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_constraint("documents_source_check", "documents", type_="check")
    op.create_check_constraint(
        "documents_source_check", "documents", "source IN ('web','manual')"
    )
