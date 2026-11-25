"""Whether she said the hour of what she noted.

Revision ID: 0029_observation_timed
Revises: 0028_ui_dismissals

"Toda la info del bebé, desde el nacimiento" (Santiago, 2026-11-21). The record
node now reads the day a line names («al nacer pesó 3,2 kg», «el 12 de
octubre», «hace 3 semanas»), and most of those lines name a day and no hour.
Such an entry is stored at midday, and `timed` false says so: the card, the
reply and her notes read back show the day alone instead of an hour she never
said. Every row written before this one was timed (today, yesterday, a clock).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029_observation_timed"
down_revision: Union[str, None] = "0028_ui_dismissals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE observations ADD COLUMN timed BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE observations DROP COLUMN IF EXISTS timed")
