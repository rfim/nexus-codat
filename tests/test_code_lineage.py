"""The editor's Lineage tab: built from the repo, consistent with the pipeline's own lineage, and current."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import code_lineage  # noqa: E402

G = code_lineage.build()
IDS = {n["id"] for n in G["nodes"]}


def closure(node, edges, seen=None):
    seen = set() if seen is None else seen
    for a, b in edges:
        if b == node and a not in seen:
            seen.add(a)
            closure(a, edges, seen)
    return seen


def test_published_file_is_current():
    assert json.loads((ROOT / "assets/data/code_lineage.json").read_text()) == G


def test_every_edge_joins_two_known_tables():
    assert all(a in IDS and b in IDS for a, b in G["edges"])


def test_every_feed_lands_in_bronze():
    for n in G["nodes"]:
        if n["layer"] == "landing":
            assert any(a == n["id"] and b.startswith("bronze.") for a, b in G["edges"]), n["id"]


def test_upstream_matches_the_exported_lineage():
    """What export.py says feeds each product is reachable in the editor's graph, through the product or its contract."""
    exported = json.loads((ROOT / "assets/data/lineage.json").read_text())
    for p, v in exported.items():
        reach = closure(f"gold.{p}", G["edges"]) | closure("serve.contracts", G["edges"])
        assert set(v["upstream"]) <= reach, (p, set(v["upstream"]) - reach)


def test_gold_edges_come_from_gold_py():
    assert ["silver.invoice", "gold.fct_invoice"] in G["edges"]
    assert ["gold.fct_invoice", "gold.insights_revenue_monthly"] in G["edges"]
    assert ["silver.commerce_payout", "gold.insights_commerce_monthly"] in G["edges"]
    assert ["silver.company_entitlement", "gold.insights_cash_flow_monthly"] in G["edges"]  # the consent join


def test_every_module_and_contract_has_lineage():
    files = G["files"]
    for p in (ROOT / "src/nexus").glob("*.py"):
        if p.stem not in {"__init__"}:
            assert f"src/nexus/{p.name}" in files, p.name
    for p in (ROOT / "contracts/products").glob("*.yml"):
        assert f"contracts/products/{p.name}" in files
    assert all(set(f["reads"]) | set(f["writes"]) <= IDS for f in files.values())


def test_what_the_main_modules_write():
    f = G["files"]
    assert set(f["src/nexus/bronze.py"]["writes"]) == {i for i in IDS if i.startswith("bronze.")}
    assert "gold.insights_cash_flow_monthly" in f["src/nexus/gold.py"]["writes"]
    assert f["src/nexus/oncall_agent.py"] == {**f["src/nexus/oncall_agent.py"], "reads": ["serve.mcp"], "writes": ["serve.agent"]}
    assert "silver.bank_balance" in f["contracts/products/insights_cash_flow_monthly.yml"]["reads"]


def test_tests_inherit_their_module():
    f = G["files"]
    assert f["tests/test_gold.py"]["writes"] == sorted(i for i in IDS if i.startswith("gold."))
    assert "serve.mcp" in f["examples/04_mcp_tools_as_two_customers.py"]["writes"]
