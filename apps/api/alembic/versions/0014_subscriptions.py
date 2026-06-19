"""Stripe subscription columns on users (30-day trial → paid).

Revision ID: 0014_subscriptions
Revises: 0013_blob_tombstones
Create Date: 2026-06-19 00:00:00.000000

Adds the billing state mirrored from Stripe webhooks: customer id, status
(none/trialing/active/past_due/canceled), plan, and the trial/period end
timestamps the paywall reads to decide access.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014_subscriptions"
down_revision: Union[str, None] = "0013_blob_tombstones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "subscription_status",
            sa.String(),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("subscription_plan", sa.String(), nullable=True))
    op.add_column("users", sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_users_stripe_customer_id", "users", ["stripe_customer_id"])
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"])


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    op.drop_column("users", "current_period_end")
    op.drop_column("users", "trial_end")
    op.drop_column("users", "subscription_plan")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "stripe_customer_id")
