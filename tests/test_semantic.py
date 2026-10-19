import pytest

from nexus import semantic


def test_compiled_sql_always_carries_the_tenant_filter():
    sql = semantic.compile_sql("revenue", ["month"], "northbank")
    assert "customer_id = 'northbank'" in sql and "GROUP BY month" in sql


@pytest.mark.parametrize("customer", ["northbank", "brightpay"])
def test_tenant_filter_comes_first_and_cannot_be_dropped(customer):
    sql = semantic.compile_sql("net_operating_cash_flow", [], customer, company_id="C-107")
    assert sql.split("WHERE ")[1].startswith(f"customer_id = '{customer}'")


def test_point_in_time_metrics_cannot_be_summed_across_companies():
    with pytest.raises(semantic.Refused) as e:
        semantic.compile_sql("dso_days", [], "northbank")
    assert e.value.reason == "non_additive"


def test_point_in_time_metric_is_allowed_by_company_and_month():
    sql = semantic.compile_sql("dso_days", ["month"], "northbank", company_id="C-102")
    assert "max(dso_days)" in sql


def test_derived_growth_adds_its_required_dimensions():
    sql = semantic.compile_sql("revenue_growth_mom", [], "northbank", company_id="C-104")
    assert "GROUP BY company_id, month" in sql


def test_uncertified_metrics_are_refused():
    with pytest.raises(semantic.Refused) as e:
        semantic.require_certified("gross_margin")
    assert e.value.reason == "not_certified"


def test_unknown_metrics_dimensions_and_principals_are_refused():
    for call, reason in [(lambda: semantic.require_certified("ebitda"), "unknown_metric"),
                         (lambda: semantic.compile_sql("revenue", ["industry"], "northbank"), "bad_dimension"),
                         (lambda: semantic.customer_for("someone@else.example"), "unknown_principal")]:
        with pytest.raises(semantic.Refused) as e:
            call()
        assert e.value.reason == reason


def test_month_filter_is_inclusive():
    sql = semantic.compile_sql("revenue", ["month"], "brightpay", months=("2026-07", "2026-08"))
    assert "BETWEEN DATE '2026-07-01' AND DATE '2026-08-01'" in sql


def test_every_certified_metric_names_a_product_owner_and_dimensions():
    for m in semantic.catalogue().values():
        if m["certified"]:
            assert m["product"] and m["owner"] and m["dimensions"] and m["expr"], m["name"]
            assert m["kind"] in ("additive", "derived", "point_in_time")


def test_catalogue_names_are_unique_and_synonyms_do_not_collide():
    cat = semantic.catalogue()
    seen = {}
    for m in cat.values():
        for s in m.get("synonyms", []):
            assert s not in seen, f"'{s}' used by {seen.get(s)} and {m['name']}"
            seen[s] = m["name"]
