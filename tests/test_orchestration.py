"""The Dagster definitions: the graph, the checks on every product, the schedule, and the last run's record."""
import json

import pytest

dg = pytest.importorskip("dagster")
from nexus import contracts  # noqa: E402
from nexus.orchestration import definitions  # noqa: E402
from nexus.paths import ROOT  # noqa: E402

EDGES = {"bronze": ["landing_feeds"], "silver_tables": ["bronze"], "gold_fact": ["silver_tables"],
         "insights_as_issued": ["gold_fact"], "late_corrections": ["insights_as_issued"], "insights": ["late_corrections"],
         "incident_report": ["insights"], "site_data": ["incident_report"], "landing_feeds": []}


def test_the_asset_graph_is_the_pipeline():
    g = definitions.defs.resolve_asset_graph()
    got = {k.to_user_string(): sorted(p.to_user_string() for p in g.get(k).parent_keys) for k in g.get_all_asset_keys()}
    assert got == EDGES


def test_every_product_has_a_contract_check_and_a_gx_check():
    keys = {c.name for a in definitions.ALL for c in a.check_keys}
    for c in contracts.load_products():
        assert {f"contract_{c['product']}", f"gx_{c['product']}"} <= keys
    assert {"replay_changes_nothing", "quarantine_keeps_its_reasons", "rerun_is_idempotent"} <= keys


def test_the_daily_schedule_runs_at_six_london_time():
    s = definitions.daily
    assert (s.cron_schedule, s.execution_timezone, s.job_name) == ("0 6 * * *", "Europe/London", "nexus_insights")


def test_the_agent_asset_declares_mcp_and_anthropic():
    a = next(a for a in definitions.ALL if a.key.to_user_string() == "incident_report")
    assert {"mcp", "anthropic"} <= set(a.specs_by_key[a.key].kinds)


ORCH = ROOT / "assets" / "data" / "orchestration.json"


@pytest.mark.skipif(not ORCH.exists(), reason="needs a Dagster run")
def test_the_last_dagster_run_succeeded_and_only_the_planted_break_failed():
    run = json.loads(ORCH.read_text())
    assert run["success"]
    failed = sorted(c["check"] for c in run["checks"] if not c["passed"])
    assert failed == ["contract_insights_cash_flow_monthly"]
    assert all(c["passed"] for c in run["checks"] if c["check"].startswith("gx_"))
