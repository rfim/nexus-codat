"""NEXUS Insights MCP server: agents discover certified metrics, read lineage and query as the caller.

    python -m nexus.mcp_server            # stdio, for an MCP client such as Claude Code or Claude Desktop

Every tool is read-only. `query_metric` compiles through the semantic layer and always applies the
caller's tenant filter, so an agent sees exactly what its user may see. Uncertified metrics, row-level
personal data and writes are refused by design: there is no tool for them.
"""
import json
import os

from mcp.server.mcpserver import MCPServer

from nexus import semantic

mcp = MCPServer("nexus-insights", instructions=(
    "Answer questions about SMB financial Insights using certified metrics only. "
    "Call list_metrics first, cite the metric, its version and freshness, and never give financial advice."))
_warehouse: semantic.Warehouse | None = None
LINEAGE = semantic.ROOT / "assets" / "data" / "lineage.json"


def _wh() -> semantic.Warehouse:
    global _warehouse
    if _warehouse is None:
        _warehouse = semantic.Warehouse()
    return _warehouse


def caller() -> str:
    """The authenticated principal. Over HTTP this comes from the token; over stdio, from the environment."""
    return os.environ.get("NEXUS_CALLER", "analyst@northbank.example")


def _refusal(e: semantic.Refused) -> dict:
    return {"refused": True, "reason": e.reason, "message": e.message}


@mcp.tool()
def list_metrics(domain: str | None = None) -> list[dict]:
    """Certified metrics an agent may quote, with owner, grain and freshness."""
    return [{"name": m["name"], "label": m["label"], "product": m["product"], "kind": m["kind"],
             "dimensions": m["dimensions"], "owner": m["owner"], "freshness_hours": m["freshness_hours"]}
            for m in semantic.catalogue().values() if m.get("certified")
            and (domain is None or domain in m["product"])]


@mcp.tool()
def describe_metric(name: str) -> dict:
    """Definition, allowed dimensions and known caveats of one certified metric."""
    try:
        m = semantic.require_certified(name)
    except semantic.Refused as e:
        return _refusal(e)
    return {k: m.get(k) for k in ("name", "label", "definition", "kind", "unit", "dimensions",
                                  "requires", "owner", "caveats", "product")}


@mcp.tool()
def get_lineage(name: str) -> dict:
    """Upstream sources, the contract checks that guard the metric, and their latest results."""
    try:
        m = semantic.require_certified(name)
    except semantic.Refused as e:
        return _refusal(e)
    return json.loads(LINEAGE.read_text())[m["product"]]


@mcp.tool()
def query_metric(name: str, group_by: list[str] | None = None, company_id: str | None = None,
                 month_from: str | None = None, month_to: str | None = None) -> dict:
    """Compile a certified metric through the semantic layer and run it AS THE CALLER, with a citation.

    Months are 'YYYY-MM'. The caller's tenant filter is always applied.
    """
    try:
        customer = semantic.customer_for(caller())
        months = (month_from, month_to or month_from) if month_from else None
        sql = semantic.compile_sql(name, group_by or [], customer, company_id, months)
    except semantic.Refused as e:
        return _refusal(e)
    m = semantic.catalogue()[name]
    rows = _wh().run(sql)
    lineage = json.loads(LINEAGE.read_text())[m["product"]]
    return {"rows": rows, "sql": sql, "caller": caller(), "customer": customer,
            "citation": {"metric": name, "product": f"gold.{m['product']}", "version": lineage["version"],
                         "owner": m["owner"], "freshness_hours": m["freshness_hours"],
                         "checks": f"{lineage['checks_passed']}/{lineage['checks_total']} contract checks pass"},
            "caveats": m.get("caveats", [])}


if __name__ == "__main__":
    mcp.run()
