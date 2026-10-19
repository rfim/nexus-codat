"""Lineage for the code editor: the table graph, and what each repo file reads and writes in it.

Built from the repo itself: the feeds and bronze tables come from contracts/sources.yml, the products from
contracts/products/, the gold edges from the table() calls in each gold.py builder, and a test or example
inherits the lineage of the modules it imports. Writes assets/data/code_lineage.json; run by manifest.py.
"""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REF = re.compile(r"""table\(\s*["'](bronze|silver|gold)["']\s*,\s*["'](\w+)["']\s*\)|\{(bronze|silver|gold)\.(\w+)\}""")

SILVER_FROM = {  # silver table -> bronze tables it is conformed from (src/nexus/silver.py)
    "invoice": ["ledgerone_invoice", "bookwise_invoice", "orbiterp_invoice"],
    "invoice_quarantine": ["ledgerone_invoice", "bookwise_invoice", "orbiterp_invoice"],
    "account_mapping": ["account"], "bank_transaction": ["bank_transaction"], "bank_balance": ["bank_balance"],
    "commerce_payout": ["commerce_payout"], "company": ["company"], "company_entitlement": ["company_entitlement"],
}
SERVE = [("serve.semantic", "semantic layer", "semantic/metrics.yml"), ("serve.contracts", "contract checks (SQL)", "contracts/products/"),
         ("serve.gx", "Great Expectations", "src/nexus/quality_gx.py"), ("serve.mcp", "MCP server", "src/nexus/mcp_server.py"),
         ("serve.agent", "on-call agent · Claude", "src/nexus/oncall_agent.py"), ("serve.site", "site data", "src/nexus/export.py")]


def refs(text: str) -> list[str]:
    return sorted({f"{m[0] or m[2]}.{m[1] or m[3]}" for m in REF.findall(text)})


def graph() -> dict:
    sources = yaml.safe_load((ROOT / "contracts/sources.yml").read_text())
    products = sorted(p.stem for p in (ROOT / "contracts/products").glob("*.yml"))
    nodes, edges = [], []
    add = lambda i, layer, label, **kw: nodes.append({"id": i, "layer": layer, "label": label, **kw})
    for s in sources:
        add(f"landing.{s['feed']}", "landing", s["feed"], source=s["source"].get("topic"))
        add(f"bronze.{s['target']['table']}", "bronze", s["target"]["table"])
        edges.append([f"landing.{s['feed']}", f"bronze.{s['target']['table']}"])
    for t, srcs in SILVER_FROM.items():
        add(f"silver.{t}", "silver", t)
        edges += [[f"bronze.{b}", f"silver.{t}"] for b in srcs]
    # gold: each builder in gold.py reads what its table() calls name and writes the table it publishes
    gold = (ROOT / "src/nexus/gold.py").read_text()
    for body in re.split(r"\ndef ", gold)[1:]:
        out = re.search(r"""_publish\(spark,\s*"(\w+)"|fact_name = table\("gold", "(\w+)"\)""", body)
        if not out:
            continue
        name = out.group(1) or out.group(2)
        add(f"gold.{name}", "gold", name, product=name in products)
        shared = ["silver.company_entitlement"] if "_shared()" in body else []  # the consent join
        edges += [[r, f"gold.{name}"] for r in sorted(set(refs(body)) | set(shared)) if r != f"gold.{name}"]
    for i, label, src in SERVE:
        add(i, "serve", label, source=src)
    metrics = yaml.safe_load((ROOT / "semantic/metrics.yml").read_text())["metrics"]
    used = sorted({m["product"] for m in (metrics.values() if isinstance(metrics, dict) else metrics) if m.get("product")})
    edges += [[f"gold.{p}", "serve.semantic"] for p in used]
    # a contract also reads what it reconciles against (e.g. cash flow against silver.bank_balance)
    for p in products:
        edges += [[r, "serve.contracts"] for r in refs((ROOT / f"contracts/products/{p}.yml").read_text())]
    edges += [[f"gold.{p}", "serve.contracts"] for p in products] + [[f"gold.{p}", "serve.gx"] for p in products]
    edges += [["serve.semantic", "serve.mcp"], ["serve.contracts", "serve.mcp"], ["serve.mcp", "serve.agent"],
              ["serve.contracts", "serve.site"], ["serve.gx", "serve.site"], ["serve.agent", "serve.site"]]
    edges += [[f"gold.{p}", "serve.site"] for p in products]
    return {"nodes": nodes, "edges": edges, "products": products}


def files(g: dict) -> dict:
    ids = [n["id"] for n in g["nodes"]]
    layer = lambda l: [i for i in ids if i.startswith(l + ".")]
    prods = [f"gold.{p}" for p in g["products"]]
    mod = {  # what each module does in the graph: (role, reads, writes)
        "generate": ("writes the synthetic platform feeds", [], layer("landing")),
        "bronze": ("lands every feed with an ordered, replay-safe MERGE", layer("landing"), layer("bronze")),
        "silver": ("conforms bronze to the canonical model; quarantines what fails", layer("bronze"), layer("silver")),
        "gold": ("builds the fact and the consent-scoped Insights products",
                 refs((ROOT / "src/nexus/gold.py").read_text()), layer("gold")),
        "pipeline": ("runs land → conform → publish → prove in order", layer("landing"), layer("bronze") + layer("silver") + layer("gold")),
        "contracts": ("compiles each product contract to SQL checks", prods + ["silver.company_entitlement"], ["serve.contracts"]),
        "quality_gx": ("turns each contract into a Great Expectations suite", prods, ["serve.gx"]),
        "semantic": ("certified metrics compiled to SQL with the tenant filter", prods + ["silver.company_entitlement"], ["serve.semantic"]),
        "mcp_server": ("the MCP tools: metrics, lineage, checks, diagnostics", ["serve.semantic", "serve.contracts"], ["serve.mcp"]),
        "agent": ("routes an analyst's question to MCP tool calls", ["serve.mcp"], []),
        "oncall_agent": ("investigates a failed check over MCP and files an incident", ["serve.mcp"], ["serve.agent"]),
        "export": ("exports products, checks and history for the site", layer("bronze") + layer("silver") + layer("gold"), ["serve.site"]),
        "paths": ("names every table: nexus_<layer>.<name>, or the Unity Catalog name", [], []),
        "silver_columns": ("the canonical invoice columns", [], ["silver.invoice"]),
        "spark": ("the Spark session with Delta", [], []),
        "assets": ("the Dagster assets: every step of the graph, with checks", [], ids),
        "definitions": ("the Dagster job, schedule and freshness check", ids, []),
        "run": ("materialises the Dagster graph and records the run", [], ids),
        "resources": ("the Spark resource for Dagster", [], []),
    }
    out = {}
    for p in sorted(ROOT.glob("src/nexus/**/*.py")):
        if p.stem in mod:
            role, r, w = mod[p.stem]
            out[p.relative_to(ROOT).as_posix()] = {"role": role, "reads": r, "writes": w}
    sources = yaml.safe_load((ROOT / "contracts/sources.yml").read_text())
    out["contracts/sources.yml"] = {"role": "defines every feed and its bronze table", "reads": [],
                                    "writes": layer("landing") + layer("bronze") + ["silver.invoice"]}
    out["contracts/quality.yml"] = {"role": "the quality gate on the canonical invoice", "reads": ["silver.invoice"],
                                    "writes": ["silver.invoice_quarantine"]}
    for p in g["products"]:
        out[f"contracts/products/{p}.yml"] = {"role": f"the contract for {p}",
                                              "reads": [f"gold.{p}", *refs((ROOT / f"contracts/products/{p}.yml").read_text())],
                                              "writes": ["serve.contracts", "serve.gx"]}
    out["semantic/metrics.yml"] = {"role": "the certified metrics", "reads": prods, "writes": ["serve.semantic"]}
    out["evals/questions.yml"] = {"role": "questions the analyst agent must answer or refuse", "reads": ["serve.mcp"], "writes": []}
    # tests and examples inherit the lineage of the modules they import
    for p in sorted([*ROOT.glob("tests/*.py"), *ROOT.glob("examples/*.py")]):
        rel, text = p.relative_to(ROOT).as_posix(), p.read_text()
        names = set(re.findall(r"from nexus(?:\.orchestration)? import ([\w, ]+)", text))
        names = {n.strip().split(" as ")[0] for line in names for n in line.split(",")}
        names |= set(re.findall(r"from nexus\.(?:orchestration\.)?(\w+) import", text))
        names &= set(mod) - {"spark", "paths", "resources"}
        if p.stem.startswith("test_") and p.stem[5:] in mod:
            names.add(p.stem[5:])
        if not names:
            continue
        r = sorted({x for n in names for x in mod[n][1]} | set(refs(text)))
        w = sorted({x for n in names for x in mod[n][2]})
        kind = "tests" if rel.startswith("tests/") else "runs"
        out[rel] = {"role": f"{kind} {', '.join(sorted(names))}", "reads": r, "writes": w}
    for f in out.values():
        f["reads"] = [i for i in dict.fromkeys(f["reads"]) if i in ids]
        f["writes"] = [i for i in dict.fromkeys(f["writes"]) if i in ids]
    return out


def build() -> dict:
    g = graph()
    return {**g, "files": files(g)}


if __name__ == "__main__":
    data = build()
    (ROOT / "assets/data/code_lineage.json").write_text(json.dumps(data, indent=1))
    print(len(data["nodes"]), "nodes,", len(data["edges"]), "edges,", len(data["files"]), "files")
