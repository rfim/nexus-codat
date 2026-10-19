"""Turn pytest's JUnit XML into assets/data/tests.json, the report the site shows."""
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone

SPARK = {"test_bronze", "test_scd2", "test_silver", "test_gold"}
LOCAL = {"test_quality_gx", "test_oncall_agent", "test_orchestration"}
ABOUT = {
    "test_generate": "Synthetic feeds carry every planted problem",
    "test_bronze": "Replay-safe MERGE on Delta (Spark)",
    "test_silver": "Three schemas → one canonical invoice; quarantine (Spark)",
    "test_scd2": "Account remaps kept as history (Spark)",
    "test_gold": "As-of joins, consent scope, idempotent re-runs (Spark)",
    "test_contracts": "Contracts compile into checks, expectations and governance",
    "test_semantic": "Semantic layer: tenant filter, refusals, metric kinds",
    "test_mini_warehouse": "Browser evaluator returns exactly DuckDB's rows",
    "test_agent": "Planner routing, parsing and refusals",
    "test_mcp": "MCP tools, consent per customer, and the agent evals",
    "test_data": "Published data keeps its promises",
    "test_site": "Pages link to real files; nothing secret in the repo",
    "test_quality_gx": "Great Expectations suites from the contracts",
    "test_oncall_agent": "On-call agent: Claude's tool loop over the real MCP server; offline rules",
    "test_orchestration": "Dagster graph, checks on every product, schedule, last run",
}


def main(xml_path: str, out: str) -> None:
    root = ET.parse(xml_path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    files = defaultdict(list)
    for tc in suite.iter("testcase"):
        mod = tc.get("classname", "").split(".")[-1]
        outcome = "failed" if tc.find("failure") is not None or tc.find("error") is not None else \
                  "skipped" if tc.find("skipped") is not None else "passed"
        files[mod].append({"name": tc.get("name"), "outcome": outcome, "seconds": round(float(tc.get("time", 0)), 3)})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "total": sum(len(v) for v in files.values()),
              **{k: sum(t["outcome"] == k for v in files.values() for t in v) for k in ("passed", "failed", "skipped")},
              "seconds": round(float(suite.get("time", 0)), 1),
              "suites": [{"file": f"tests/{m}.py", "about": ABOUT.get(m, ""), "spark": m in SPARK, "local": m in LOCAL, "tests": t}
                         for m, t in sorted(files.items(), key=lambda kv: list(ABOUT).index(kv[0]) if kv[0] in ABOUT else 99)]}
    with open(out, "w") as fh:
        json.dump(report, fh, indent=1)
    print(f"{report['passed']} passed, {report['failed']} failed, {report['skipped']} skipped → {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
