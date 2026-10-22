"""Evidence tier: what other mothers say, apart from what the studies say.

Revision ID: 0022_evidence_tier
Revises: 0021_hybrid_retrieval_fts

A mother wants an action plan and to feel accompanied; much of daily life
with a baby (the mess of weaning, the bath a toddler suddenly fears) has no
study behind it (Kenza, 2026-10-22). The product adds a layer of what other
parents report in public blogs and forums, cited by URL. It shares the table,
the embedding and the card with the clinical corpus, so one word on the row
has to say which it is: `tier`.

'evidence' is the default and the backfill, so every row loaded before this
revision, and every evidence_*.json file, keeps meaning what it meant. The
check constraint on `source_type` gains 'experience' for the same rows: a blog
post is not a guideline, a paper, a protocol or a reference, and labelling it
as one would be the lie the tier exists to prevent.

Retrieval filters on `tier` in SQL, but the column gets no index: the table
holds a few hundred rows and the planner reads it whole either way.
Reversible: `downgrade` drops exactly what `upgrade` added, and fails on
purpose if an 'experience' source_type row still exists, rather than
relabel it.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0022_evidence_tier"
down_revision: Union[str, None] = "0021_hybrid_retrieval_fts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE evidence_sources "
        "ADD COLUMN tier VARCHAR(16) NOT NULL DEFAULT 'evidence'"
    )
    op.execute(
        "ALTER TABLE evidence_sources ADD CONSTRAINT ck_evidence_sources_tier "
        "CHECK (tier IN ('evidence', 'experience'))"
    )
    op.execute("ALTER TABLE evidence_sources DROP CONSTRAINT ck_evidence_sources_type")
    op.execute(
        "ALTER TABLE evidence_sources ADD CONSTRAINT ck_evidence_sources_type "
        "CHECK (source_type IN ('guideline', 'paper', 'protocol', 'reference', 'experience'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE evidence_sources DROP CONSTRAINT ck_evidence_sources_type")
    op.execute(
        "ALTER TABLE evidence_sources ADD CONSTRAINT ck_evidence_sources_type "
        "CHECK (source_type IN ('guideline', 'paper', 'protocol', 'reference'))"
    )
    op.execute("ALTER TABLE evidence_sources DROP CONSTRAINT IF EXISTS ck_evidence_sources_tier")
    op.execute("ALTER TABLE evidence_sources DROP COLUMN IF EXISTS tier")
