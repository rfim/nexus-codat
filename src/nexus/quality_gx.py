"""Great Expectations suites, generated from the product contracts and run on every load.

The contract is the source of truth: each column test becomes a GX expectation, the grain becomes a
compound-uniqueness expectation, and every product must have rows. The SQL checks in contracts.py keep
what GX can't express on one table (reconciliation to source, consent); GX owns the column rules.
"""
import json
import logging
import os

import great_expectations as gx

from nexus import contracts
from nexus.paths import ROOT

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")
logging.getLogger("great_expectations").setLevel(logging.ERROR)
OUT = ROOT / "assets" / "data" / "gx"


_CTX = None


def context():
    """One ephemeral GX context per process: suites and validations need an active one."""
    global _CTX
    if _CTX is None:
        _CTX = gx.get_context(mode="ephemeral")
    return _CTX


def suite_for(c: dict) -> gx.ExpectationSuite:
    """One contract -> one ExpectationSuite. Unknown tests fail loudly, like the SQL compiler."""
    context()
    suite = gx.ExpectationSuite(name=f"{c['product']}__contract")
    E = gx.expectations
    for col in c.get("columns", []):
        for test in col.get("tests", []):
            name, arg = (test, None) if isinstance(test, str) else next(iter(test.items()))
            if name == "not_null":
                suite.add_expectation(E.ExpectColumnValuesToNotBeNull(column=col["name"]))
            elif name == "accepted_values":
                suite.add_expectation(E.ExpectColumnValuesToBeInSet(column=col["name"], value_set=list(arg)))
            elif name == "range":
                suite.add_expectation(E.ExpectColumnValuesToBeBetween(
                    column=col["name"], min_value=arg.get("min"), max_value=arg.get("max")))
            else:
                raise ValueError(f"unknown test {name} in {c['_path']}")
    suite.add_expectation(E.ExpectCompoundColumnsToBeUnique(column_list=list(c["grain"])))
    suite.add_expectation(E.ExpectTableRowCountToBeBetween(min_value=1))
    for column in c["grain"]:
        suite.add_expectation(E.ExpectColumnToExist(column=column))
    return suite


class Validator:
    """An ephemeral GX context with one pandas datasource; one batch per product per run."""

    _n = 0

    def __init__(self):
        Validator._n += 1
        self.ctx = context()
        self.ds = self.ctx.data_sources.add_pandas(f"nexus_gold_{Validator._n}")

    def validate(self, c: dict, df) -> dict:
        asset = self.ds.add_dataframe_asset(c["product"])
        batch = asset.add_batch_definition_whole_dataframe("load").get_batch(batch_parameters={"dataframe": df})
        res = batch.validate(suite_for(c))
        return {
            "product": c["product"], "suite": f"{c['product']}__contract", "success": bool(res.success),
            "evaluated": res.statistics["evaluated_expectations"], "passed": res.statistics["successful_expectations"],
            "expectations": [{
                "type": r.expectation_config.type,
                "kwargs": {k: v for k, v in r.expectation_config.kwargs.items() if k != "batch_id"},
                "success": bool(r.success),
                "unexpected_count": r.result.get("unexpected_count"),
                "partial_unexpected": [str(x) for x in (r.result.get("partial_unexpected_list") or [])[:5]],
                "observed_value": r.result.get("observed_value"),
            } for r in res.results],
        }


def validate_all(frames: dict) -> list[dict]:
    """frames: product -> pandas DataFrame. Writes one JSON result per product for the site."""
    v, out = Validator(), []
    OUT.mkdir(parents=True, exist_ok=True)
    for c in contracts.load_products():
        result = v.validate(c, frames[c["product"]])
        (OUT / f"{c['product']}.json").write_text(json.dumps(result, indent=1, default=str))
        out.append(result)
    return out
