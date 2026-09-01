"""Baby onboarding: remember that the account was asked about the child.

Revision ID: 0017_users_onboarded_at
Revises: 0016_telegram_link_locale

Audit 4.3: between the magic link and the first useful pixel there was a
credit card and not one question about the baby, so every clinical surface ran
without a date of birth, which is the fact the red-flag rules, the lab ranges,
the growth percentiles and the briefing header all depend on.

The "already asked" flag lives on the row, not in a cookie: a mother who
skipped on her phone must not be asked again on her laptop, and a cookie is
also the first thing a privacy-minded parent clears. NULL means the account has
never seen the screen; a timestamp means it answered or skipped, and the answer
itself is the `child` profile.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_users_onboarded_at"
down_revision: Union[str, None] = "0016_telegram_link_locale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Accounts that already have a child profile have answered the question by
    # other means (the agent's completar_perfil tool, the profiles screen);
    # asking them again would be a regression for the only users there are.
    op.execute(
        """
        UPDATE users SET onboarded_at = now()
        WHERE id IN (
            SELECT user_id FROM profiles
            WHERE relationship = 'child' AND deleted_at IS NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "onboarded_at")
