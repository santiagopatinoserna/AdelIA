"""Guest accounts: the demo is the real app (decision of 2026-11-06).

Revision ID: 0025_guest_accounts
Revises: 0024_chat_session_profile

A visitor of the landing now uses the real panel with Lucía as her child, and
everything she does is kept, per user, on the server. That needs:

* `users.is_guest`: a row created without an email. `users.email` stays NOT
  NULL and UNIQUE (the Auth.js adapter and every lookup by email rely on it),
  so a guest carries a synthetic address in the reserved `.invalid` TLD
  (RFC 2606), which can never receive mail nor collide with a real one. The
  flag, not the domain, is what the code reads: access without a card, and
  "Guardar mi cuenta" in the panel.
* `guest_claims`: "Guardar mi cuenta". The guest asks for an email, Auth.js
  sends the usual magic link, and the account that link signs in adopts the
  guest's data. Only the sha256 of the claim token is stored; the row expires
  with the link and cascades with the guest.
* `demo_seed_embeddings`: Lucía's record is seeded as real chunks so the agent
  can retrieve it, and retrieval needs vectors. The texts are the same for
  every guest, so their vectors are computed once per text and reused; keyed
  by the sha256 of the text so a change to the fixture simply misses.
* `chat_sessions.surface` and `chat_messages.evidence_citations`: the agent's
  turns are now stored (they were held only in the browser), in the same
  tables as the chat, so the history lists them. `surface` tells the agent's
  thread apart for "seguir donde lo dejé", and the evidence cards ride along
  so a restored answer still has its sources.

Reversible: downgrade drops what upgrade added.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0025_guest_accounts"
down_revision: Union[str, None] = "0024_chat_session_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN is_guest BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE guest_claims (
            token_hash VARCHAR(64) PRIMARY KEY,
            guest_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email VARCHAR NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_guest_claims_guest ON guest_claims (guest_id)")
    op.execute(
        """
        CREATE TABLE demo_seed_embeddings (
            content_sha256 VARCHAR(64) PRIMARY KEY,
            embedding vector(1024) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE chat_sessions ADD COLUMN surface VARCHAR(16) NOT NULL DEFAULT 'chat'"
    )
    op.execute(
        "ALTER TABLE chat_sessions ADD CONSTRAINT ck_chat_sessions_surface "
        "CHECK (surface IN ('chat', 'agent'))"
    )
    op.execute("ALTER TABLE chat_messages ADD COLUMN evidence_citations JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages DROP COLUMN evidence_citations")
    op.execute("ALTER TABLE chat_sessions DROP CONSTRAINT ck_chat_sessions_surface")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN surface")
    op.execute("DROP TABLE demo_seed_embeddings")
    op.execute("DROP TABLE guest_claims")
    op.execute("ALTER TABLE users DROP COLUMN is_guest")
