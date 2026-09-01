"""Aggregate funnel counters, one row per (day, event). No people in it.

Revision ID: 0018_funnel_counters
Revises: 0017_users_onboarded_at

Audit 4.8: the product had a funnel with a credit card at the door and not a
single number anywhere, so "nobody converts" and "nobody arrives" were
indistinguishable. The obvious fix (an analytics script) is the one thing
/privacidad promises never to do: "No te rastreamos: no hay analítica ni
publicidad en AdelIA."

So the counters are a COUNTER, in the strict sense. The table holds a date, an
event name and an integer, and there is no column that could hold a person: no
IP, no user agent, no session id, no user id, no referrer, no cookie is set or
read to write a row. Two visitors and one visitor visiting twice are the same
+2, and that is on purpose, not a limitation to be fixed later.

Only the two PRE-account events live here (a landing view and a press of
"Empezar"). Signups and activations are NOT counted: they are derived at read
time from users.created_at and users.onboarded_at, which already exist, so the
funnel needs no second copy of them (services/funnel.summary).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_funnel_counters"
down_revision: Union[str, None] = "0017_users_onboarded_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "funnel_counters",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        # (day, event) is the whole identity of a row: the upsert that
        # increments it depends on this being the conflict target.
        sa.PrimaryKeyConstraint("day", "event", name="funnel_counters_pkey"),
    )


def downgrade() -> None:
    op.drop_table("funnel_counters")
