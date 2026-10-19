"""The MCP tools and the agent evals, run against the exported gold products (no Spark needed)."""
import asyncio
import os

import duckdb
import pytest
import yaml

from nexus import agent, mcp_server, semantic

EVALS = yaml.safe_load((semantic.ROOT / "evals" / "questions.yml").read_text())


def test_the_server_exposes_exactly_the_four_read_only_tools():
    names = sorted(t.name for t in asyncio.run(mcp_server.mcp.list_tools()))
    assert names == ["describe_metric", "get_lineage", "list_metrics", "query_metric"]


def test_query_runs_as_the_caller_and_cites_its_source():
    os.environ["NEXUS_CALLER"] = "analyst@brightpay.example"
    out = mcp_server.query_metric("revenue", ["company_id"])
    assert out["customer"] == "brightpay" and "customer_id = 'brightpay'" in out["sql"]
    assert {r["company_id"] for r in out["rows"]} <= {"C-107", "C-108", "C-109", "C-110", "C-111"}
    assert out["citation"]["product"] == "gold.insights_revenue_monthly"


def _expected(sql: str) -> float:
    con = semantic.Warehouse().con
    return round(float(con.execute(sql).fetchone()[0]), 2)


@pytest.mark.parametrize("case", EVALS, ids=[c["id"] for c in EVALS])
def test_eval(case):
    out = agent.ask(case["ask"], case["as"])
    exp, res = case["expect"], out["result"]
    if exp.get("refuses"):
        assert res.get("refused") and res["reason"] == exp["reason"]
        return
    assert out["plan"]["tool"] == exp["tool"]
    if "metric" in exp:
        assert out["plan"]["args"]["name"] == exp["metric"]
    if "rows" in exp:
        assert len(res["rows"]) == exp["rows"]
    if exp.get("no_data"):
        assert all(r[exp["metric"]] is None for r in res["rows"])
    if "equals_sql" in exp:
        got = round(float(res["rows"][0][exp["metric"]]), 2)
        assert abs(got - _expected(exp["equals_sql"])) <= exp.get("tolerance", 0.01)
        assert res["citation"]["metric"] == exp["metric"]
    for word in exp.get("mentions", []):
        assert word in str(res).lower()
