"""Observations: what she notes about her child, one row per fact.

Revision ID: 0023_observations
Revises: 0022_evidence_tier

AGENT_GRAPH build step 4, decision 2: the record node ("hoy ha tenido 37,8",
"se ha tomado 150 ml") writes here, with a numeric value and a unit from the
start, so a reading can be compared with yesterday's and plotted later. The
Telegram diary stays free text and does not change.

Tenancy follows the rest of the record: `user_id` cascades on account
erasure (GDPR art. 17, the DELETE /users/me path deletes the user row and
lets ON DELETE CASCADE do the rest), and `profile_id` cascades on a profile
row's deletion, because an observation of one child must never be reassigned
to the account and read as her sibling's. Writes happen only after a
confirmation card (principle 3); `source` says which surface wrote it.

The kinds and sources are CHECK-constrained here and in models.py; adding one
means a migration, on purpose. Reversible: downgrade drops the table.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0023_observations"
down_revision: Union[str, None] = "0022_evidence_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE observations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            profile_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
            kind VARCHAR(24) NOT NULL,
            value DOUBLE PRECISION,
            unit VARCHAR(16),
            text TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            source VARCHAR(16) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_observations_kind CHECK (kind IN (
                'temperature', 'feed', 'sleep', 'stool', 'nappy', 'weight',
                'symptom', 'medication', 'vaccine', 'note'
            )),
            CONSTRAINT ck_observations_source CHECK (source IN ('agent', 'chat', 'telegram'))
        )
        """
    )
    op.execute("CREATE INDEX ix_observations_user ON observations (user_id)")
    op.execute(
        "CREATE INDEX ix_observations_profile_kind_time "
        "ON observations (profile_id, kind, observed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS observations")
