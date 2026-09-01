"""Indexes for the three access paths the product actually walks.

Revision ID: 0019_access_path_indexes
Revises: 0018_funnel_counters

Audit 4 ("`chunks` no tiene índice por `user_id`"): the retrieval query behind
every chat answer filters `chunks.user_id` and orders by vector distance, and
that column had no index at all. With `hnsw.ef_search = 40` and
`iterative_scan = off` the vector scan stops after ~40 candidates taken from
EVERYONE's rows and then discards the ones that are not hers, so past a few
dozen accounts the answer quietly gets built from less of her record than
exists. It does not show today because `chunks` holds 0 rows in production,
which is exactly why it is worth fixing before it does.

The audit named one index; the same review of the real access paths turns up
two more shaped by queries that already run on every page load:

  * documents: `WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at
    DESC LIMIT ?` (routers/documents.list_documents, the dashboard's first
    query). `ix_documents_user_id` from 0001 gets the rows but not the order,
    so the planner sorts the account's whole history to return ten lines.
  * entities: `WHERE user_id = ? AND (profile_id = ? OR profile_id IS NULL)
    AND deleted_at IS NULL` (services/scope.Scope.where, on the briefing and
    the structured-query path). `ix_entities_user_type_date` leads with
    user_id and then jumps to entity_type, so it cannot serve the profile
    half of the filter.

All three are plain btree CREATE INDEX, not CONCURRENTLY: the tables are
small today, the API runs `alembic upgrade head` inside its boot transaction
(apps/api/Dockerfile), and CONCURRENTLY cannot run in a transaction. Revisit
when a table is big enough for the write lock to matter.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019_access_path_indexes"
down_revision: Union[str, None] = "0018_funnel_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    op.create_index(
        "ix_documents_user_created",
        "documents",
        ["user_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_entities_user_profile",
        "entities",
        ["user_id", "profile_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entities_user_profile", table_name="entities")
    op.drop_index("ix_documents_user_created", table_name="documents")
    op.drop_index("ix_chunks_user_id", table_name="chunks")
