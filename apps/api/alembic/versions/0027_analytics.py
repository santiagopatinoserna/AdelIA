"""Consented visitor journeys: consent proofs, sessions, events.

Revision ID: 0027_analytics
Revises: 0026_usage_counters

Written as 0026_analytics on 2026-11-07 and renumbered behind main's
0026_usage_counters when it was integrated on 2026-11-08, so there is one head.

Decision of Santiago (2026-11-07): "guarda lo de quien nos visita, dónde hacen
clic, todo". The full journey of each visitor who accepts the banner, kept in
our own database and nowhere else, because AdelIA is a health product and a
third-party script would send its visitors to someone else's servers.

Three tables, none with a column that could hold a person or her words:

* `analytics_consents`: the proof of each answer to the banner (choice,
  version of the text, date) under a random id the browser keeps. Append-only.
* `analytics_sessions`: one row per visit of a visitor who accepted, keyed by
  random ids drawn in the browser, with where she came from (domain and UTM,
  never a URL), device class, screen, language and country.
* `analytics_events`: the steps of that visit, from a closed vocabulary
  (pageview, click, scroll, step). No free text column.

`funnel_counters` (0018) stays: it counts every visitor, consenting or not,
without storing anything, and the demo's daily budget reads it.

Retention lives in code (services/analytics.purge_expired), at boot and daily.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027_analytics"
down_revision: Union[str, None] = "0026_usage_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analytics_consents (
            id BIGSERIAL PRIMARY KEY,
            consent_id UUID NOT NULL,
            choice VARCHAR(12) NOT NULL,
            version VARCHAR(16) NOT NULL,
            source VARCHAR(12) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_analytics_consents_choice
                CHECK (choice IN ('accepted', 'rejected', 'withdrawn'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_analytics_consents_consent_created "
        "ON analytics_consents (consent_id, created_at)"
    )
    op.execute("CREATE INDEX ix_analytics_consents_created ON analytics_consents (created_at)")
    op.execute(
        """
        CREATE TABLE analytics_sessions (
            session_id UUID PRIMARY KEY,
            visitor_id UUID NOT NULL,
            consent_id UUID NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL,
            landing_path VARCHAR(160),
            referrer_domain VARCHAR(100),
            utm_source VARCHAR(100),
            utm_medium VARCHAR(100),
            utm_campaign VARCHAR(100),
            utm_content VARCHAR(100),
            utm_term VARCHAR(100),
            device VARCHAR(8),
            screen_w INTEGER,
            screen_h INTEGER,
            lang VARCHAR(16),
            locale VARCHAR(5),
            country VARCHAR(2)
        )
        """
    )
    op.execute("CREATE INDEX ix_analytics_sessions_visitor_id ON analytics_sessions (visitor_id)")
    op.execute("CREATE INDEX ix_analytics_sessions_started_at ON analytics_sessions (started_at)")
    op.execute(
        "CREATE INDEX ix_analytics_sessions_last_seen_at ON analytics_sessions (last_seen_at)"
    )
    op.execute(
        """
        CREATE TABLE analytics_events (
            id BIGSERIAL PRIMARY KEY,
            session_id UUID NOT NULL
                REFERENCES analytics_sessions(session_id) ON DELETE CASCADE,
            occurred_at TIMESTAMPTZ NOT NULL,
            type VARCHAR(12) NOT NULL,
            path VARCHAR(160) NOT NULL,
            element VARCHAR(80),
            depth INTEGER,
            step VARCHAR(24),
            CONSTRAINT ck_analytics_events_type
                CHECK (type IN ('pageview', 'click', 'scroll', 'step'))
        )
        """
    )
    op.execute("CREATE INDEX ix_analytics_events_occurred_at ON analytics_events (occurred_at)")
    op.execute(
        "CREATE INDEX ix_analytics_events_session_time "
        "ON analytics_events (session_id, occurred_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE analytics_events")
    op.execute("DROP TABLE analytics_sessions")
    op.execute("DROP TABLE analytics_consents")
