"""Full-text search columns and GIN indexes for hybrid retrieval.

Revision ID: 0021_hybrid_retrieval_fts
Revises: 0020_users_token_version

Retrieval was pure cosine distance with one calibrated cut-off
(settings.evidence_max_distance, docs/CALIBRACION_UMBRAL_EVIDENCIA.md). A
single distance has a known failure in both directions: a question that shares
vocabulary with the corpus but not meaning slips in just under the line, and
one phrased unlike the corpus falls just outside it. The audit calibrated the
number and made the refusal a code path; the non-vector cross-check it listed
as the follow-up needs a tsvector to search, which is what this adds. Postgres
already holds the text, so there is no new service and no new dependency.

How the language is chosen, per table, because the two tables differ:

evidence_chunks. The language belongs to the SOURCE (`evidence_sources.language`,
set once per source by enrichment/evidence_loader.py from the seed file, 'es'
for 117 of the 127 sources in the seed files and 'en' for the rest). A generated column
cannot read another table, so the language is denormalised onto the chunk as
`evidence_chunks.language` (backfilled below from the source, and written by
the loader from now on), and `tsv` is generated from it: Spanish chunks are
stemmed as Spanish, French as French, English as English, anything else under
`simple` (no stemming, no stopwords) rather than a wrong guess. The expression
is a pure function of the row's own columns, which is what makes it legal in a
GENERATED column and indexable, and means it can never drift from `content`.
`language` is expected to hold the bare ISO 639-1 code every seed file uses
('es', 'en', 'fr'); a regional code such as 'es-ES' falls to `simple`.

chunks (the user's own documents). Nothing records a language: neither `chunks`
nor `documents` has the column, OCR does not report one, and `users.
preferred_locale` is the parent's language, not necessarily the report's (a
Spanish-speaking mother uploads an English lab sheet). Inventing a per-row
value would be false precision, so `tsv` is the union of the three
configurations: the text is indexed as Spanish AND English AND French. A query
parsed under one configuration then finds the same word in that configuration's
slice of the vector whatever language the document was in, because index and
query go through the same stemmer. The cost is a tsvector about three times
larger, on a table that holds 0 rows in production.

Both columns are STORED generated columns, so adding them rewrites the table
under an ACCESS EXCLUSIVE lock, and the indexes are plain CREATE INDEX rather
than CONCURRENTLY, for the reason 0019 gives: the tables are small, the API
runs `alembic upgrade head` inside its boot transaction (apps/api/Dockerfile),
and CONCURRENTLY cannot run in one. Revisit when a table is big enough for the
lock to matter.

Reversible: `downgrade` drops exactly what `upgrade` added, indexes first.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0021_hybrid_retrieval_fts"
down_revision: Union[str, None] = "0020_users_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # evidence_chunks: language first (the generated column reads it), backfilled
    # from the owning source before `tsv` exists so every row is built right.
    op.execute(
        "ALTER TABLE evidence_chunks "
        "ADD COLUMN language VARCHAR(8) NOT NULL DEFAULT 'en'"
    )
    op.execute(
        "UPDATE evidence_chunks ec SET language = COALESCE(es.language, 'en') "
        "FROM evidence_sources es WHERE es.id = ec.source_id"
    )
    op.execute(
        """
        ALTER TABLE evidence_chunks
        ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
            CASE language
                WHEN 'es' THEN to_tsvector('spanish'::regconfig, content)
                WHEN 'fr' THEN to_tsvector('french'::regconfig, content)
                WHEN 'en' THEN to_tsvector('english'::regconfig, content)
                ELSE to_tsvector('simple'::regconfig, content)
            END
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_evidence_chunks_tsv ON evidence_chunks USING gin (tsv)")

    # chunks: no language to read, so index the text under all three.
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('spanish'::regconfig, content)
            || to_tsvector('english'::regconfig, content)
            || to_tsvector('french'::regconfig, content)
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
    op.execute("DROP INDEX IF EXISTS ix_evidence_chunks_tsv")
    op.execute("ALTER TABLE evidence_chunks DROP COLUMN IF EXISTS tsv")
    op.execute("ALTER TABLE evidence_chunks DROP COLUMN IF EXISTS language")
