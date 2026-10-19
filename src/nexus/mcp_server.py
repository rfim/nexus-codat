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
_warehouse = None
LINEAGE = semantic.ROOT / "assets" / "data" / "lineage.json"
OPS = {"oncall@nexus.example"}   # the on-call identity: run metadata and diagnostics, never customer-level queries
DIAGNOSTICS = ("bank_lines_vs_balance", "same_day_same_amount", "lines_by_category")


def _run_state() -> dict:
    """The latest run's check results and precomputed diagnostics, written by the orchestrator."""
    path = os.environ.get("NEXUS_RUN_STATE", str(semantic.ROOT / "assets" / "data" / "run_state.json"))
    return json.loads(open(path).read())


def _ops_only() -> dict | None:
    if caller() not in OPS:
        return {"refused": True, "reason": "not_on_call", "message": f"{caller()} can't read run diagnostics."}
    return None


def _wh():
    global _warehouse
    if _warehouse is None:
        _warehouse = semantic.warehouse()
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


# ---- on-call tools: read-only, for the on-call identity only ----

@mcp.tool()
def list_failing_checks() -> dict:
    """Contract (SQL) and Great Expectations checks that failed on the latest run, with row counts."""
    if denied := _ops_only():
        return denied
    st = _run_state()
    return {"run_id": st["run_id"], "failing": [{k: f[k] for k in ("product", "check", "kind", "failing_rows")}
                                               for f in st["failing"]],
            "gx_failing": [g for g in st["gx"] if not g["success"]], "checks_total": st["checks_total"]}


@mcp.tool()
def get_check_evidence(product: str, check: str) -> dict:
    """The failing rows (a sample), the compiled SQL, the product's owner and its upstream tables."""
    if denied := _ops_only():
        return denied
    st = _run_state()
    hit = next((f for f in st["failing"] if f["product"] == product and f["check"] == check), None)
    if hit is None:
        return {"error": f"no failing check '{check}' on {product} in run {st['run_id']}"}
    lineage = json.loads(LINEAGE.read_text())[product]
    return hit | {"upstream": lineage["upstream"], "contract": lineage["contract"]}


@mcp.tool()
def run_diagnostic(name: str, company_id: str) -> dict:
    """A named, read-only diagnostic for one company: bank_lines_vs_balance, same_day_same_amount, lines_by_category."""
    if denied := _ops_only():
        return denied
    if name not in DIAGNOSTICS:
        return {"error": f"unknown diagnostic '{name}'; available: {', '.join(DIAGNOSTICS)}"}
    d = _run_state()["diagnostics"].get(company_id)
    if d is None:
        return {"error": f"no diagnostics were computed for {company_id}: only companies in a failing check have them"}
    return {"diagnostic": name, "company_id": company_id, "result": d[name]}


@mcp.tool()
def recent_changes() -> dict:
    """Recent commits that touched contracts or pipeline code, to rule a code change in or out."""
    if denied := _ops_only():
        return denied
    return {"changes": _run_state().get("recent_changes", [])}


if __name__ == "__main__":
    mcp.run()
