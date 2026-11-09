"""What she closed on the panel: one row per account and card kind.

Revision ID: 0028_ui_dismissals
Revises: 0027_analytics

"La barra de conectar a Telegram nunca desaparece" (Santiago, 2026-11-09).
The suggestion cards are rebuilt on every request, so a card she closed came
back after every reload and on every device. The kind of card she closed
("link_telegram", "daily_diary"...) is kept here, per account, and
agent/suggestions.py does not build it again. No health data: a key from a
closed vocabulary and a date. Erased with the account (ON DELETE CASCADE).
A branch that adds a migration before this one lands has to chain it again.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028_ui_dismissals"
down_revision: Union[str, None] = "0027_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ui_dismissals (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key VARCHAR(40) NOT NULL,
            dismissed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ui_dismissals")
