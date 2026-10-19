"""NEXUS as Dagster assets. Data lives in Delta tables; each asset returns the facts of its step (row counts,
versions, check results), which Dagster passes to the next asset and records as metadata.

    landing_feeds → bronze → silver → gold_fact → insights_as_issued → late_corrections → insights
                                                                              → incident_report → site_data
"""
import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone

import dagster as dg

from nexus import bronze as bronze_layer
from nexus import contracts, gold, oncall_agent, quality_gx, silver
from nexus.generate import generate
from nexus.orchestration.resources import SparkResource
from nexus.paths import ROOT, TARGET, table

PRODUCTS = [c["product"] for c in contracts.load_products()]
DATA = ROOT / "assets" / "data"


def _timed(label: str, key: str, fn):
    t0 = time.time()
    out = fn()
    return out, {"key": key, "label": label, "duration_s": round(time.time() - t0, 1)}


def _version(spark, layer: str, name: str) -> int:
    return spark.sql(f"DESCRIBE HISTORY {table(layer, name)}").agg({"version": "max"}).first()[0]


def _transform(spark, sources):
    ref = silver.build_reference(spark)
    valid, quarantined = silver.split_by_contract(spark, sources)
    return {"invoice": valid, "invoice_quarantine": quarantined,
            "account_mapping": silver.build_account_mapping_scd2(spark)} | ref | silver.build_banking(spark)


def _publish(spark) -> int:
    rows = gold.build_fct_invoice(spark)
    for build in gold.PRODUCTS:
        build(spark)
    return rows


def _contract_results(spark) -> list[dict]:
    return [{"product": c["product"], "owner": c["owner"], "results": (res := contracts.run_checks(spark, c)),
             "passed": sum(r["status"] == "pass" for r in res), "total": len(res)} for c in contracts.load_products()]


@dg.asset(group_name="ingest", kinds={"python"}, description="Synthetic SMB feeds: two accounting platforms, an ERP, "
          "a bank feed and commerce payouts, with every planted problem.")
def landing_feeds(context: dg.AssetExecutionContext) -> dict:
    feeds, task = _timed("Generate synthetic SMB feeds", "generate", generate)
    context.add_output_metadata({"records": sum(v for v in feeds.values() if isinstance(v, int)),
                                 "planted_break": dg.MetadataValue.json(feeds["planted_break"])})
    return {"feeds": feeds, "tasks": [task]}


@dg.asset(group_name="ingest", kinds={"spark", "delta"}, description="Every feed landed by ordered MERGE.",
          check_specs=[dg.AssetCheckSpec("replay_changes_nothing", asset="bronze",
                                         description="Re-ingesting every feed leaves every bronze table unchanged.")])
def bronze(context: dg.AssetExecutionContext, spark: SparkResource, landing_feeds: dict):
    s, sources = spark.session(), contracts.load_sources()
    counts, t1 = _timed("Ingest every feed to bronze (MERGE)", "ingest", lambda: {x["feed"]: bronze_ingest(s, x) for x in sources})
    replay, t2 = _timed("Replay every feed (should change nothing)", "replay", lambda: {x["feed"]: bronze_ingest(s, x) for x in sources})
    yield dg.Output({"bronze": counts, "bronze_after_replay": replay, "tasks": landing_feeds["tasks"] + [t1, t2],
                     "feeds": landing_feeds["feeds"]},
                    metadata={"rows": sum(counts.values()), "tables": dg.MetadataValue.json(counts)})
    yield dg.AssetCheckResult(check_name="replay_changes_nothing", passed=counts == replay,
                              metadata={"rows_before": sum(counts.values()), "rows_after_replay": sum(replay.values())})


def bronze_ingest(spark, source, feed=None):
    return bronze_layer.ingest(spark, source, feed)


@dg.asset(group_name="conform", kinds={"spark", "delta"}, description="One canonical invoice, the quality split, "
          "SCD2 account mappings, conformed banking and commerce.",
          check_specs=[dg.AssetCheckSpec("quarantine_keeps_its_reasons", asset="silver_tables")])
def silver_tables(context: dg.AssetExecutionContext, spark: SparkResource, bronze: dict):
    s = spark.session()
    out, task = _timed("Canonical invoice, quality split, SCD2, banking", "silver", lambda: _transform(s, contracts.load_sources()))
    reasons = {r["rule"]: r["n"] for r in s.sql(f"SELECT explode(_failed_rules) AS rule, count(*) AS n "
                                                 f"FROM {table('silver', 'invoice_quarantine')} GROUP BY 1").collect()}
    yield dg.Output(bronze | {"silver": out | {"quarantine_reasons": reasons}, "tasks": bronze["tasks"] + [task]},
                    metadata={"canonical_invoices": out["invoice"], "quarantined": out["invoice_quarantine"],
                              "quarantine_reasons": dg.MetadataValue.json(reasons)})
    yield dg.AssetCheckResult(check_name="quarantine_keeps_its_reasons", passed=sum(reasons.values()) >= out["invoice_quarantine"],
                              metadata=reasons)


@dg.asset(group_name="publish", kinds={"spark", "delta"}, description="The incremental invoice fact (MERGE, 72h lookback).",
          check_specs=[dg.AssetCheckSpec("rerun_is_idempotent", asset="gold_fact")])
def gold_fact(context: dg.AssetExecutionContext, spark: SparkResource, silver_tables: dict):
    s = spark.session()
    rows, t1 = _timed("Invoice fact (incremental MERGE) and Insights products", "gold", lambda: _publish(s))
    again, t2 = _timed("Re-run the fact inside the lookback window", "rerun", lambda: gold.build_fct_invoice(s))
    yield dg.Output(silver_tables | {"gold_fact": {"rows": rows, "rows_after_rerun": again},
                                     "tasks": silver_tables["tasks"] + [t1, t2]}, metadata={"rows": rows})
    yield dg.AssetCheckResult(check_name="rerun_is_idempotent", passed=rows == again, metadata={"rows": rows, "after_rerun": again})


@dg.asset(group_name="publish", kinds={"spark", "delta"}, description="The Insights products as first issued (Delta v0).")
def insights_as_issued(context: dg.AssetExecutionContext, spark: SparkResource, gold_fact: dict) -> dict:
    s = spark.session()
    res, task = _timed("Contract checks on the first publish", "check_issued", lambda: _contract_results(s))
    v = _version(s, "gold", "insights_revenue_monthly")
    context.add_output_metadata({"revenue_version": v, "checks": f"{sum(c['passed'] for c in res)}/{sum(c['total'] for c in res)}"})
    return gold_fact | {"as_issued": {"revenue_version": v, "contracts": [
        {k: c[k] for k in ("product", "owner", "passed", "total")} |
        {"failing": [r["check"] for r in c["results"] if r["status"] == "fail"]} for c in res]},
        "tasks": gold_fact["tasks"] + [task]}


@dg.asset(group_name="ingest", kinds={"spark", "delta"}, description="Backdated credit notes and late voids, merged into bronze.")
def late_corrections(context: dg.AssetExecutionContext, spark: SparkResource, insights_as_issued: dict) -> dict:
    s = spark.session()
    late, task = _timed("Late corrections to bronze (MERGE)", "late", lambda: {
        x["feed"]: bronze_ingest(s, x, x["feed"] + "_late") for x in contracts.load_sources() if "canonical" in x})
    context.add_output_metadata({"documents": insights_as_issued["feeds"]["late_total"]})
    return insights_as_issued | {"late_batch": late, "tasks": insights_as_issued["tasks"] + [task]}


def _diagnostics(s, companies) -> dict:
    out = {}
    for cid in companies:
        tx = table("silver", "bank_transaction")
        total = float(s.sql(f"SELECT sum(amount) FROM {tx} WHERE company_id = '{cid}'").first()[0])
        moved = float(s.sql(f"SELECT sum(balance_movement) FROM {table('silver', 'bank_balance')} WHERE company_id = '{cid}'").first()[0])
        pairs = [r.asDict() for r in s.sql(f"""
            SELECT CAST(booked_date AS STRING) AS booked_date, CAST(amount AS DOUBLE) AS amount, description, count(*) AS n,
                   sort_array(collect_list(txn_id)) AS txn_ids
            FROM {tx} WHERE company_id = '{cid}' GROUP BY account_id, booked_date, amount, description
            HAVING count(*) > 1 ORDER BY booked_date""").collect()]
        cats = {r["category"]: r["n"] for r in s.sql(f"SELECT category, count(*) AS n FROM {tx} WHERE company_id = '{cid}' "
                                                      f"GROUP BY 1 ORDER BY 1").collect()}
        out[cid] = {"bank_lines_vs_balance": {"lines_total": round(total, 2), "balance_movement": round(moved, 2),
                                              "difference": round(total - moved, 2)},
                    "same_day_same_amount": pairs, "lines_by_category": cats}
    return out


def _recent_changes() -> list[dict]:
    try:
        log = subprocess.run(["git", "-C", str(ROOT), "log", "-8", "--name-only", "--format=@@%h|%cs|%s"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for chunk in log.split("@@")[1:]:
        head, *files = [x for x in chunk.strip().splitlines() if x]
        sha, day, subject = head.split("|", 2)
        files = [f for f in files if f.startswith(("contracts/", "src/nexus/"))]
        if files:
            out.append({"commit": sha, "date": day, "subject": subject, "files": ", ".join(files[:8]),
                        "touches_banking": any("bank" in f or f.endswith(("silver.py", "gold.py")) for f in files)
                        and "bank" in subject.lower()})
    return out


INSIGHT_CHECKS = [spec for p in PRODUCTS for spec in (
    dg.AssetCheckSpec(f"contract_{p}", asset="insights", description=f"SQL checks compiled from contracts/products/{p}.yml"),
    dg.AssetCheckSpec(f"gx_{p}", asset="insights", description=f"Great Expectations suite generated from {p}.yml"))]


@dg.asset(group_name="publish", kinds={"spark", "delta", "great_expectations"}, check_specs=INSIGHT_CHECKS,
          description="The Insights products, restated with the late corrections, checked by SQL contracts and GX.")
def insights(context: dg.AssetExecutionContext, spark: SparkResource, late_corrections: dict):
    s = spark.session()
    _, t1 = _timed("Re-run silver and gold with the corrections", "restate", lambda: (_transform(s, contracts.load_sources()), _publish(s)))
    res, t2 = _timed("Contract checks on the restated products", "check", lambda: _contract_results(s))
    frames = {p: s.table(table("gold", p)).toPandas() for p in PRODUCTS}
    gx_res, t3 = _timed("Great Expectations suites on every product", "gx", lambda: quality_gx.validate_all(frames))
    failing = [{"product": c["product"], "check": r["check"], "kind": r["kind"], "failing_rows": r["failing_rows"],
                "sample": json.loads(json.dumps(r["sample"], default=float)), "sql": r["sql"], "owner": c["owner"]}
               for c in res for r in c["results"] if r["status"] == "fail"]
    companies = sorted({x["company_id"] for f in failing for x in f["sample"] if "company_id" in x})
    state = {"run_id": context.run_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "failing": failing,
             "checks_total": sum(c["total"] for c in res) + sum(g["evaluated"] for g in gx_res),
             "gx": [{k: g[k] for k in ("product", "success", "passed", "evaluated")} for g in gx_res],
             "diagnostics": _diagnostics(s, companies), "recent_changes": _recent_changes()}
    (DATA / "run_state.json").write_text(json.dumps(state, indent=1, default=str))
    yield dg.Output(late_corrections | {"contracts": res, "gx": gx_res, "tasks": late_corrections["tasks"] + [t1, t2, t3],
                                        "current": {"revenue_version": _version(s, "gold", "insights_revenue_monthly"),
                                                    "fct_invoice": s.table(table("gold", "fct_invoice")).count()}},
                    metadata={"revenue_version": _version(s, "gold", "insights_revenue_monthly"),
                              "failing_checks": len(failing), "gx_suites_passing": sum(g["success"] for g in gx_res)})
    by_gx = {g["product"]: g for g in gx_res}
    for c in res:
        fails = [r for r in c["results"] if r["status"] == "fail"]
        yield dg.AssetCheckResult(check_name=f"contract_{c['product']}", passed=not fails,
                                  severity=dg.AssetCheckSeverity.ERROR,   # a contract breach is an error; severity applies on failure
                                  metadata={"passed": f"{c['passed']}/{c['total']}", "failing": dg.MetadataValue.json([f["check"] for f in fails])})
        g = by_gx[c["product"]]
        yield dg.AssetCheckResult(check_name=f"gx_{c['product']}", passed=g["success"],
                                  metadata={"expectations": f"{g['passed']}/{g['evaluated']}"})


@dg.asset(group_name="operate", kinds={"python", "mcp", "anthropic"},
          description="The on-call agent: Claude over the nexus-insights MCP server (or offline rules without credentials) "
                      "diagnoses failing checks and proposes a fix as a pull request.")
def incident_report(context: dg.AssetExecutionContext, insights: dict) -> dict:
    inc, task = _timed("On-call agent diagnoses failing checks over MCP", "agent", lambda: asyncio.run(oncall_agent.run()))
    (DATA / "incident.json").write_text(json.dumps(inc, indent=1, default=str))
    (DATA / "incident.md").write_text(oncall_agent.to_markdown(inc))
    context.add_output_metadata({"written_by": inc["model"], "title": inc["report"]["title"],
                                 "confidence": inc["report"]["confidence"], "mcp_tool_calls": sum(t["kind"] == "tool" for t in inc["transcript"]),
                                 "report": dg.MetadataValue.md(oncall_agent.to_markdown(inc))})
    return insights | {"incident": {k: inc[k] for k in ("model", "seconds")} | {"title": inc["report"]["title"]},
                       "tasks": insights["tasks"] + [task]}


@dg.asset(group_name="operate", kinds={"python"}, description="Everything the site shows, exported from this run.")
def site_data(context: dg.AssetExecutionContext, incident_report: dict) -> dict:
    from nexus.export import export
    t0 = time.time()
    log = dict(incident_report, seconds=round(sum(t["duration_s"] for t in incident_report["tasks"]), 1))
    log["tasks"] = [t | {"start_s": round(sum(x["duration_s"] for x in log["tasks"][:i]), 1)} for i, t in enumerate(log["tasks"])]
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / "run_log.json").write_text(json.dumps({k: v for k, v in log.items() if k != "gx"}, indent=1, default=str))
    export(log)
    context.add_output_metadata({"seconds": round(time.time() - t0, 1)})
    return {"exported": True}
