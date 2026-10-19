"""The MCP tools and the agent evals, run against the exported gold products (no Spark needed)."""
import asyncio
import os

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
    """Independent of the semantic layer: straight SQL against gold (DuckDB), or the rows themselves."""
    try:
        con = semantic.Warehouse().con
        return round(float(con.execute(sql).fetchone()[0]), 2)
    except ImportError:
        import re
        t, col = re.search(r"sum\((\w+)\) FROM gold\.(\w+)", sql).group(2, 1)
        eq = dict(re.findall(r"(\w+) = '([^']*)'", sql))
        mo = re.search(r"month = DATE '([\d-]+)'", sql)
        rows = semantic.MiniWarehouse().tables[t]
        return round(sum(r[col] for r in rows if all(str(r[k]) == v for k, v in eq.items())
                         and (not mo or r["month"] == mo[1])), 2)


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


def test_tools_are_described_and_typed_for_the_agent():
    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert all(t.description for t in tools.values())
    assert tools["query_metric"].input_schema["required"] == ["name"]


def test_describe_and_lineage_refuse_uncertified_metrics():
    for fn in (mcp_server.describe_metric, mcp_server.get_lineage):
        assert fn("gross_margin")["reason"] == "not_certified"


def test_list_metrics_never_offers_an_uncertified_metric():
    names = {m["name"] for m in mcp_server.list_metrics()}
    assert "gross_margin" not in names and {"revenue", "net_operating_cash_flow", "dso_days"} <= names


def test_an_unknown_caller_gets_nothing():
    os.environ["NEXUS_CALLER"] = "intruder@example.com"
    out = mcp_server.query_metric("revenue", ["company_id"])
    assert out["refused"] and out["reason"] == "unknown_principal"


@pytest.mark.parametrize("who, allowed", [("analyst@northbank.example", {f"C-{i}" for i in range(101, 109)}),
                                          ("analyst@brightpay.example", {f"C-{i}" for i in range(107, 112)})])
def test_each_customer_sees_exactly_its_consented_companies(who, allowed):
    os.environ["NEXUS_CALLER"] = who
    seen = {r["company_id"] for r in mcp_server.query_metric("revenue", ["company_id"])["rows"]}
    assert seen == allowed
