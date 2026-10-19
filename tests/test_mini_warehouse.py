"""The browser's evaluator must return exactly what DuckDB returns, for every compiled query shape."""
import itertools

import pytest

from nexus import semantic

duckdb = pytest.importorskip("duckdb")
CASES = []
for name, m in semantic.catalogue().items():
    if not m.get("certified"):
        continue
    dims = [d for d in m["dimensions"] if d != "currency"]
    for k in range(len(dims) + 1):
        for group in itertools.combinations(dims, k):
            for customer in ("northbank", "brightpay"):
                for company in (None, "C-107", "C-104"):
                    for months in (None, ("2026-07", "2026-08")):
                        if months and "month" not in m["dimensions"]:
                            continue
                        CASES.append((name, list(group), customer, company, months))


@pytest.fixture(scope="module")
def engines():
    return semantic.Warehouse(), semantic.MiniWarehouse()


def _close(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.keys() == y.keys()
        for k in x:
            if isinstance(x[k], float) or isinstance(y[k], float):
                assert x[k] is not None and y[k] is not None and abs(x[k] - y[k]) < 0.01, (k, x, y)
            else:
                assert x[k] == y[k], (k, x, y)


@pytest.mark.parametrize("name, group, customer, company, months", CASES)
def test_same_rows_as_duckdb(engines, name, group, customer, company, months):
    try:
        sql = semantic.compile_sql(name, group, customer, company, months)
    except semantic.Refused:
        pytest.skip("refused by design")
    duck, mini = engines
    _close(duck.run(sql), mini.run(sql))


def test_it_refuses_anything_that_is_not_compiled_sql():
    with pytest.raises(ValueError):
        semantic.MiniWarehouse().run("DROP TABLE gold.insights_revenue_monthly")
