"""The four MCP tools, called directly, as the lender and as the payments platform."""
import os

from nexus import mcp_server

print([m["name"] for m in mcp_server.list_metrics()])
print(mcp_server.describe_metric("net_operating_cash_flow")["definition"])

for who in ("analyst@northbank.example", "analyst@brightpay.example"):
    os.environ["NEXUS_CALLER"] = who
    out = mcp_server.query_metric("revenue", ["company_id"], month_from="2026-08")
    print(f"\n{who} sees {len(out['rows'])} companies:", [r["company_id"] for r in out["rows"]])
    print("  citation:", out["citation"])

print("\nuncertified:", mcp_server.query_metric("gross_margin"))
