"""Telegram diary: per-link UI locale so the bot speaks the parent's language.

Revision ID: 0016_telegram_link_locale
Revises: 0015_consulta_recording

telegram_links.locale (es/en/fr) is captured at /start from the link token
minted by the web UI. Existing rows default to 'es', the only language the
bot spoke until now.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_telegram_link_locale"
down_revision: Union[str, None] = "0015_consulta_recording"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_links",
        sa.Column("locale", sa.String(8), nullable=False, server_default="es"),
    )


def downgrade() -> None:
    op.drop_column("telegram_links", "locale")
