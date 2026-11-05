"""Chat sessions say which child they were about.

Revision ID: 0024_chat_session_profile
Revises: 0023_observations

"Hoy con <nombre>" (services/today) shows the first "No olvides" line of the
last plan the chat stored. `chat_sessions` had no profile, so with two
children the line could not be attributed and was dropped for both. The chat
router now writes the resolved child of each turn here.

Nullable, with no backfill: a session from before this revision cannot be
attributed after the fact. GET /today reads those only when the account has a
single child, which is what it did before.

`profile_id` cascades on a profile row's deletion, like observations (0023)
and unlike the SET NULL of 0006: a NULL session reads as "the only child's"
once the account is down to one, so SET NULL would hand Adel's conversations
to Nora. Account erasure is unchanged: `user_id` still cascades from users.
The index serves the per-child read, `WHERE user_id = ? AND profile_id = ?`.
Reversible: downgrade drops the index, the constraint and the column.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0024_chat_session_profile"
down_revision: Union[str, None] = "0023_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_sessions ADD COLUMN profile_id UUID")
    op.execute(
        "ALTER TABLE chat_sessions ADD CONSTRAINT fk_chat_sessions_profile "
        "FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX ix_chat_sessions_profile ON chat_sessions (user_id, profile_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_profile")
    op.execute("ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS fk_chat_sessions_profile")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS profile_id")
