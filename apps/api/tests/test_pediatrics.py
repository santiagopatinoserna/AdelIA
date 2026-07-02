from adelia.agent.pediatrics import growth_percentile, due_vaccines


def test_percentile_midpoint_is_around_50():
    # value equal to the P50 row for that age/sex → ~50th percentile
    p = growth_percentile(metric="weight", value=5.6, age_months=2, sex="M")
    assert p is not None and 40 <= p <= 60


def test_percentile_out_of_table_returns_none():
    assert growth_percentile(metric="weight", value=5.0, age_months=999, sex="M") is None


def test_due_vaccines_returns_list():
    v = due_vaccines(age_months=2)
    assert isinstance(v, list) and all("name" in x and "due_month" in x for x in v)
