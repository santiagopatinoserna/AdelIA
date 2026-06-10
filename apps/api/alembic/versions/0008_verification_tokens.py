"""verification_tokens for Auth.js magic-link flow + users.email_verified.

Revision ID: 0008_verification_tokens
Revises: 0007_briefings_id_default
Create Date: 2026-06-10 00:00:00.000000

The web app's Resend (email) provider requires an Auth.js adapter; without
one every magic-link request 500s with MissingAdapter. The web app ships a
minimal custom adapter (apps/web/lib/auth-adapter.ts) backed by the SAME
users table the API owns — keeping token.sub == users.id so backend FKs
hold. This migration adds the only storage that flow needs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_verification_tokens"
down_revision: Union[str, None] = "0007_briefings_id_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verification_tokens",
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("identifier", "token"),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified")
    op.drop_table("verification_tokens")
