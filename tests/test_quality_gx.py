"""Great Expectations suites come from the contracts, pass on the published data, and catch each kind of bad row."""
import json

import pytest

gx = pytest.importorskip("great_expectations")
pd = pytest.importorskip("pandas")

from nexus import contracts, quality_gx  # noqa: E402
from nexus.paths import ROOT  # noqa: E402

PRODUCTS = contracts.load_products()


def _frame(product):
    return pd.DataFrame(json.loads((ROOT / "assets" / "data" / "products" / f"{product}.json").read_text()))


@pytest.mark.parametrize("c", PRODUCTS, ids=[c["product"] for c in PRODUCTS])
def test_every_contract_test_becomes_an_expectation(c):
    suite = quality_gx.suite_for(c)
    n_tests = sum(len(col.get("tests", [])) for col in c.get("columns", []))
    types = [e.expectation_type for e in suite.expectations]
    assert len(types) == n_tests + 2 + len(c["grain"])     # + grain uniqueness, row count, a column-exists per grain column
    assert "expect_compound_columns_to_be_unique" in types


@pytest.mark.parametrize("c", PRODUCTS, ids=[c["product"] for c in PRODUCTS])
def test_published_products_pass_their_suites(c):
    res = quality_gx.Validator().validate(c, _frame(c["product"]))
    assert res["success"], [e for e in res["expectations"] if not e["success"]]


def test_each_kind_of_bad_row_is_caught():
    c = next(c for c in PRODUCTS if c["product"] == "insights_revenue_monthly")
    df = _frame(c["product"])
    bad = pd.concat([df, df.iloc[[0]].assign(currency="XX"), df.iloc[[1]].assign(revenue=None), df.iloc[[2]]])
    res = quality_gx.Validator().validate(c, bad)
    failed = {e["type"] for e in res["expectations"] if not e["success"]}
    assert {"expect_column_values_to_be_in_set", "expect_column_values_to_not_be_null",
            "expect_compound_columns_to_be_unique"} <= failed


def test_unknown_contract_tests_fail_loudly():
    with pytest.raises(ValueError):
        quality_gx.suite_for(dict(PRODUCTS[0], columns=[{"name": "x", "tests": ["is_lovely"]}]))
