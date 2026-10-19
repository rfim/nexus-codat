"""End to end: land -> bronze -> silver -> gold -> contracts, then a late batch of backdated corrections.

The same entry point a Databricks job calls. Every step writes Delta, so the run leaves a real
transaction log behind: the replay, the MERGEs and the late restatement are all in the history.
"""
import json
import time

from nexus import bronze, contracts, gold, silver
from nexus.generate import generate
from nexus.spark import TARGET, get_spark, table


class Steps:
    """Records each task's duration, like an orchestrator run."""

    def __init__(self):
        self.tasks, self.t0 = [], time.time()

    def run(self, key: str, label: str, fn, *args):
        start = time.time()
        out = fn(*args)
        self.tasks.append({"key": key, "label": label, "start_s": round(start - self.t0, 1),
                           "duration_s": round(time.time() - start, 1)})
        return out


def _transform(spark, sources):
    ref = silver.build_reference(spark)
    valid, quarantined = silver.split_by_contract(spark, sources)
    scd2 = silver.build_account_mapping_scd2(spark)
    bank = silver.build_banking(spark)
    return {"invoice": valid, "invoice_quarantine": quarantined, "account_mapping": scd2} | ref | bank


def _publish(spark):
    rows = gold.build_fct_invoice(spark)
    for build in gold.PRODUCTS:
        build(spark)
    return rows


def _check_all(spark):
    return [{"product": c["product"], "owner": c["owner"],
             "results": (res := contracts.run_checks(spark, c)),
             "passed": sum(r["status"] == "pass" for r in res), "total": len(res)}
            for c in contracts.load_products()]


def _version(spark, layer, name) -> int:
    return spark.sql(f"DESCRIBE HISTORY {table(layer, name)}").agg({"version": "max"}).first()[0]


def _summary(checks):
    return [{k: c[k] for k in ("product", "owner", "passed", "total")} |
            {"failing": [r["check"] for r in c["results"] if r["status"] == "fail"]} for c in checks]


def run() -> dict:
    steps = Steps()
    spark = get_spark()
    log = {"feeds": steps.run("generate", "Generate synthetic SMB feeds", generate)}

    sources = contracts.load_sources()
    ingest_all = lambda: {s["feed"]: bronze.ingest(spark, s) for s in sources}  # noqa: E731
    log["bronze"] = steps.run("ingest", "Ingest every feed to bronze (MERGE)", ingest_all)
    # replay every feed: idempotence means nothing changes
    log["bronze_after_replay"] = steps.run("replay", "Replay every feed (should change nothing)", ingest_all)

    log["silver"] = steps.run("silver", "Canonical invoice, quality split, SCD2, banking", _transform, spark, sources)
    log["silver"]["quarantine_reasons"] = {r["rule"]: r["n"] for r in spark.sql(
        f"SELECT explode(_failed_rules) AS rule, count(*) AS n FROM {table('silver', 'invoice_quarantine')} "
        f"GROUP BY 1").collect()}

    first = steps.run("gold", "Invoice fact (incremental MERGE) and Insights products", _publish, spark)
    steps.run("rerun", "Re-run the fact inside the lookback window", gold.build_fct_invoice, spark)
    log["gold_fact"] = {"rows": first, "rows_after_rerun": spark.table(table("gold", "fct_invoice")).count()}

    issued = steps.run("check_issued", "Contract checks on the first publish", _check_all, spark)
    log["as_issued"] = {"revenue_version": _version(spark, "gold", "insights_revenue_monthly"),
                        "contracts": _summary(issued)}

    # a day later: backdated credit notes and late voids, merged into the same bronze tables
    log["late_batch"] = steps.run("late", "Late corrections to bronze (MERGE)", lambda: {
        s["feed"]: bronze.ingest(spark, s, s["feed"] + "_late") for s in sources if "canonical" in s})
    steps.run("restate", "Re-run silver and gold with the corrections",
              lambda: (_transform(spark, sources), _publish(spark)))

    compiled = TARGET / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    for c in contracts.load_products():
        (compiled / f"{c['product']}_expectations.py").write_text(contracts.compile_expectations(c))
        (compiled / f"{c['product']}_governance.sql").write_text(contracts.compile_governance(c))
    log["contracts"] = steps.run("check", "Contract checks on the restated products", _check_all, spark)
    log["current"] = {"revenue_version": _version(spark, "gold", "insights_revenue_monthly"),
                      "fct_invoice": spark.table(table("gold", "fct_invoice")).count()}
    log["tasks"] = steps.tasks
    log["seconds"] = round(time.time() - steps.t0, 1)
    (TARGET / "run_log.json").write_text(json.dumps(log, indent=2, default=str))
    return log


def summarise(out: dict) -> None:
    print(json.dumps({k: v for k, v in out.items() if k not in ("contracts", "tasks")}, indent=2, default=str))
    for c in out["contracts"]:
        print(f"{c['product']:<30} {c['passed']}/{c['total']} checks passed")
        for r in c["results"]:
            if r["status"] == "fail":
                print(f"      FAIL {r['check']}: {r['failing_rows']} row(s) {r['sample'][:1]}")


if __name__ == "__main__":
    summarise(run())
