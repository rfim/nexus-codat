"""Materialise the whole graph in-process (what scripts/build.sh and CI run), then record the run for the site."""
import json
import sys
from datetime import datetime, timezone

import dagster as dg

from nexus.orchestration import definitions
from nexus.paths import ROOT


def main() -> int:
    started = datetime.now(timezone.utc)
    instance = dg.DagsterInstance.ephemeral()
    result = dg.materialize(definitions.ALL, resources={"spark": definitions.SparkResource()},
                            selection=dg.AssetSelection.all(), instance=instance)
    return record(result, instance, started)


def record(result, instance, started) -> int:
    graph = definitions.defs.resolve_asset_graph()
    nodes = []
    for key in graph.get_all_asset_keys():
        node = graph.get(key)
        nodes.append({"key": key.to_user_string(), "group": node.group_name, "kinds": sorted(node.kinds),
                      "deps": sorted(d.to_user_string() for d in node.parent_keys), "description": node.description})
    starts, steps = {}, {}
    for entry in instance.all_logs(result.run_id):          # event log entries carry the timestamps
        e = entry.dagster_event
        if e is None or not e.step_key:
            continue
        if e.event_type_value == "STEP_START":
            starts[e.step_key] = entry.timestamp
        elif e.event_type_value == "STEP_SUCCESS" and e.step_key in starts:
            steps[e.step_key] = round(entry.timestamp - starts[e.step_key], 1)
    checks = []
    for ev in result.get_asset_check_evaluations():
        checks.append({"asset": ev.asset_key.to_user_string(), "check": ev.check_name, "passed": ev.passed,
                       "severity": ev.severity.value, "metadata": {k: str(v.value) for k, v in ev.metadata.items()}})
    meta = {}
    for m in result.get_asset_materialization_events():
        mat = m.event_specific_data.materialization
        meta[mat.asset_key.to_user_string()] = {k: (v.value if not hasattr(v.value, "md") else None)
                                                for k, v in mat.metadata.items() if k != "report"}
    out = {"run_id": result.run_id, "success": result.success, "started_at": started.isoformat(timespec="seconds"),
           "dagster": dg.__version__, "job": definitions.nexus_job.name,
           "schedule": {"name": definitions.daily.name, "cron": definitions.daily.cron_schedule,
                        "timezone": definitions.daily.execution_timezone},
           "assets": sorted(nodes, key=lambda n: list(steps).index(n["key"]) if n["key"] in steps else 99),
           "step_seconds": steps, "checks": checks, "metadata": json.loads(json.dumps(meta, default=str))}
    (ROOT / "assets" / "data" / "orchestration.json").write_text(json.dumps(out, indent=1))
    print(f"dagster run {result.run_id}: success={result.success}, {len(nodes)} assets, "
          f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
