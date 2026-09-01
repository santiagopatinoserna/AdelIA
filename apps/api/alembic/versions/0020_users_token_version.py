"""users.token_version — the number that lets signing out mean something.

Revision ID: 0020_users_token_version
Revises: 0019_access_path_indexes

Audit 4 ("El JWT puente de FastAPI se sirve al navegador por
`GET /api/auth/session`"): the bridge token was valid for 7 days, carried no
`jti`, and `get_current_user` checked only the signature and that the user row
still existed. Nothing short of rotating `AUTH_SECRET` (which signs every
account out of the whole instance) could revoke one.

The web now mints a 15-minute token per request instead of handing the browser
a week-long one, and stamps into it the `tv` it was signed under. The API
refuses any token whose `tv` is not the current `users.token_version`, so
`POST /users/me/sessions/revoke` (called on sign-out) invalidates every token
already out there by incrementing one integer.

Default 0, NOT NULL: a token minted before this migration carries no `tv` at
all, and `auth.get_current_user` reads a missing claim as 0, so existing
sessions keep working until their owner signs out. There is nothing to
backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020_users_token_version"
down_revision: Union[str, None] = "0019_access_path_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
