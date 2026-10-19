import pytest

from nexus import semantic


def test_compiled_sql_always_carries_the_tenant_filter():
    sql = semantic.compile_sql("revenue", ["month"], "northbank")
    assert "customer_id = 'northbank'" in sql and "GROUP BY month" in sql


def test_point_in_time_metrics_cannot_be_summed_across_companies():
    with pytest.raises(semantic.Refused) as e:
        semantic.compile_sql("dso_days", [], "northbank")
    assert e.value.reason == "non_additive"


def test_uncertified_metrics_are_refused():
    with pytest.raises(semantic.Refused) as e:
        semantic.require_certified("gross_margin")
    assert e.value.reason == "not_certified"
