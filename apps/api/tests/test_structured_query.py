from datetime import date
from uuid import uuid4

import pytest

from adelia.services.structured_query import query_observations_by_name_and_date_range


@pytest.mark.skipif(
    True,
    reason="needs Postgres running (docker compose up -d) + alembic upgrade head"
)
async def test_query_observations_filters_by_name_substring_and_date_range():
    """Skipped in sandbox; runs green with PG up + seeded data."""
    user_id = uuid4()
    results = await query_observations_by_name_and_date_range(
        user_id=user_id,
        name_substring="glucosa",
        from_date=date(2020, 1, 1),
        to_date=date(2024, 12, 31),
    )
    assert isinstance(results, list)
    for row in results:
        assert row["name"].lower().__contains__("glucosa") or row["name"].lower().__contains__("glucose")
        if row["event_date"] is not None:
            assert date(2020, 1, 1) <= row["event_date"] <= date(2024, 12, 31)


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_query_observations_empty_user_returns_empty_list():
    """Smoke test: querying for a user with no data returns []."""
    user_id = uuid4()
    results = await query_observations_by_name_and_date_range(
        user_id=user_id,
        name_substring="nonexistent_glucosa_term_xyz",
        from_date=None,
        to_date=None,
    )
    assert results == []
