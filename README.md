# NEXUS for Codat

An independent Senior Data Engineer portfolio by R. Firman Insan Muhammad (Vim), for Codat's Data & Insights team.

**Live site:** https://rfim.github.io/nexus-codat/ · **Enable MCP:** https://rfim.github.io/nexus-codat/mcp.html · **The run:** https://rfim.github.io/nexus-codat/run.html · **On call:** https://rfim.github.io/nexus-codat/oncall.html

**Fireside deck:** [assets/Nexus_Codat_VIM.pdf](assets/Nexus_Codat_VIM.pdf) · **One page:** [assets/VIM_Codat_one_page.pdf](assets/VIM_Codat_one_page.pdf) · **Companion note:** [assets/VIM_Codat_companion_note.pdf](assets/VIM_Codat_companion_note.pdf)

The repository runs the methods I used at Lifepal on SMB data shaped like Codat's: accounting and ERP systems, bank feeds and commerce payouts. Every metric is agreed once as a YAML contract, every sync lands replay-safe in Delta, every product is scoped by consent, and a semantic layer with an MCP server lets AI agents query certified Insights as the caller. The numbers on the site come from a real run of the PySpark code here, on synthetic data.

## What's here

| Path | What it does |
|---|---|
| `src/nexus/generate.py` | Synthetic feeds: 12 SMBs, two fictional customers (a lender and a payments platform), two accounting platforms and a mid-market ERP with different invoice schemas, a bank feed and commerce payouts. Includes replayed sync pages, malformed rows, a chart-of-accounts remap, backdated credit notes, a revoked consent and one planted bank break. |
| `contracts/sources.yml` | Source contracts. Each accounting or ERP source carries its `canonical` mapping onto one invoice model. |
| `src/nexus/bronze.py` | Lands each feed as Delta through an ordered MERGE. Replaying a feed changes nothing. |
| `src/nexus/silver.py` | The canonical invoice, the quality split (quarantine with the failed rule attached), SCD2 account mappings, conformed banking and commerce. |
| `src/nexus/gold.py` | An incremental invoice fact with a lookback and a point-in-time mapping join, then five Insights products, each keyed by (customer, company) through active consent. |
| `contracts/products/` | Product contracts, compiled by `src/nexus/contracts.py` into SQL checks (columns, grain, freshness, consent, reconciliation), expectations and Unity Catalog governance. |
| `semantic/metrics.yml`, `src/nexus/semantic.py` | The semantic layer: each metric defined once, compiled to SQL with the consent filter always applied; point-in-time metrics can't be summed. |
| `src/nexus/mcp_server.py` | The MCP server (`mcp` 2.x): `list_metrics`, `describe_metric`, `get_lineage`, `query_metric`. Read-only, runs as the caller, cites its source. |
| `src/nexus/agent.py`, `evals/questions.yml` | A rule-based planner that stands in for the LLM, and the eval set that runs in CI: values, tool choice, citations, consent and refusals. |
| `examples/` | Five short scripts (generate, compile a contract, the semantic layer, the MCP tools as two customers, the evals) that run locally and in the browser. |
| `tests/` | 375 tests across every layer: generator, Spark bronze/silver/gold, contracts, semantic layer, the browser evaluator against DuckDB, planner, MCP tools and evals, the published data, and the site. `scripts/test_report.py` turns the run into `assets/data/tests.json`. |
| `index.html`, `mcp.html`, `run.html`, `oncall.html` | The site. `mcp.html` animates the MCP exchange step by step (with Lifepal and lesson-for-Codat tabs). `run.html` ends with a code editor that opens every file in the repo and runs the pure-Python parts in your browser (Pyodide), plus the test report and a button to run the tests in the browser. |
| `assets/vendor/`, `assets/pyshims/` | Pyodide, CodeMirror and js-yaml, served from the repo; and the small stand-ins (yaml, pytest, MCPServer) that let the same Python run unchanged in the browser. |

## The last run

- 2,335 records landed in bronze; replaying every feed changed 0 rows
- Two accounting platforms and an ERP mapped onto 433 canonical invoices; 4 malformed rows quarantined with the failed rule attached
- C-103's account remap from 1 September left June to August revenue unchanged (SCD2 + as-of join)
- 31 backdated credit notes and late voids restated 13 company-months of revenue as Delta version 1; version 0 stays queryable
- Contracts: 36 of 37 checks pass. The failure is the planted one: a 1,250.00 bank payment re-sent under a new id at C-107, caught by the cash-flow reconciliation

## Run it

Python 3.12+ and Java 17+:

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m pytest -q        # 375 tests: Spark, contracts, semantic layer, MCP, evals, data, site
./scripts/build.sh                        # the Spark run; rewrites assets/data/
python -m http.server 8000                # then open http://localhost:8000/
```

Use the MCP server from Claude Code (or any MCP client):

```bash
claude mcp add nexus-insights --env PYTHONPATH=src --env NEXUS_CALLER=analyst@northbank.example -- python -m nexus.mcp_server
```

Locally, tables live in a Spark catalog named `nexus_<layer>`. On Databricks, set `NEXUS_CATALOG=nexus` and the same code writes to `nexus.<layer>.<table>` under Unity Catalog (`databricks.yml`).

## What's real

- **Real:** the Lifepal outcomes (from my CV and production work) and all the code here, which runs end to end.
- **Synthetic:** every company, customer, system and transaction. Integration names on the site (Xero, QuickBooks Online, Sage, NetSuite, Dynamics 365 Business Central, FreeAgent, Plaid, TrueLayer, Shopify, Stripe, Square, Amazon Seller) are as listed on codat.io; the demo's systems are fictional and don't imitate their APIs.
- **Depth:** Airflow is my production orchestrator; Dagster and Temporal I know at working level.

This is an independent application. It is not affiliated with or endorsed by Codat.
