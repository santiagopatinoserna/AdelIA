"""Usage counters: what the AI providers cost us, one row per day and model.

Revision ID: 0026_usage_counters
Revises: 0025_guest_accounts

Written as 0024_usage_counters on 2026-11-03 (6773d0b, never merged) and
renumbered behind main's 0024 and 0025 when it was integrated on 2026-11-08.
A branch that adds a migration before this one lands has to chain it again.

The app's Anthropic bill is about 200 $ a month and nobody could say what it
is spent on; Mistral credits are prepaid, so a busy day can empty them.
/privacidad promises that the counters we keep cannot say who you are or
whether you came back (audit 4.8), so this table has the shape of
funnel_counters: a day, a few labels that describe the CALL, and integers.
There is no user, profile, document, session or IP column, on purpose.

The primary key is the whole label set, so recording a call is one atomic
upsert (services/usage.record). Cached input tokens have their own columns
because they are priced apart. Reversible: downgrade drops the table.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0026_usage_counters"
down_revision: Union[str, None] = "0025_guest_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE usage_counters (
            day DATE NOT NULL,
            surface VARCHAR(16) NOT NULL,
            operation VARCHAR(32) NOT NULL,
            provider VARCHAR(16) NOT NULL,
            model VARCHAR(128) NOT NULL,
            calls BIGINT NOT NULL DEFAULT 0,
            input_tokens BIGINT NOT NULL DEFAULT 0,
            output_tokens BIGINT NOT NULL DEFAULT 0,
            cache_read_tokens BIGINT NOT NULL DEFAULT 0,
            cache_write_tokens BIGINT NOT NULL DEFAULT 0,
            pages BIGINT NOT NULL DEFAULT 0,
            audio_seconds BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (day, surface, operation, provider, model)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_counters")
