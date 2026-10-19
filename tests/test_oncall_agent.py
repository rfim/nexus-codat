"""The on-call agent: real MCP server over stdio, Claude's tool loop (with a fake client), and offline rules."""
import asyncio
import json
import os
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("mcp.client.stdio")
from nexus import mcp_server, oncall_agent  # noqa: E402
from nexus.paths import ROOT  # noqa: E402

STATE = ROOT / "assets" / "data" / "run_state.json"
pytestmark = pytest.mark.skipif(not STATE.exists(), reason="needs a run_state.json from the orchestrator")


def test_on_call_tools_refuse_analysts():
    os.environ["NEXUS_CALLER"] = "analyst@northbank.example"
    for out in (mcp_server.list_failing_checks(), mcp_server.recent_changes(),
                mcp_server.run_diagnostic("bank_lines_vs_balance", "C-107")):
        assert out["reason"] == "not_on_call"


def test_diagnostics_are_a_fixed_menu():
    os.environ["NEXUS_CALLER"] = oncall_agent.ON_CALL
    assert "error" in mcp_server.run_diagnostic("DROP TABLE x", "C-107")
    assert "error" in mcp_server.run_diagnostic("bank_lines_vs_balance", "C-101")   # not in a failing check


def test_offline_agent_finds_the_resent_bank_line_over_mcp(monkeypatch):
    monkeypatch.setenv("NEXUS_AGENT", "offline")
    inc = asyncio.run(oncall_agent.run(str(STATE)))
    r = inc["report"]
    assert inc["model"] == "offline-rules" and inc["mcp_server"].startswith("nexus-insights")
    assert {"list_failing_checks", "get_check_evidence", "run_diagnostic", "query_metric"} <= set(inc["tools"])
    assert "re-sent" in r["root_cause"] and "C-107" in r["root_cause"] and "-R" in r["root_cause"]
    assert r["hypotheses"][0]["verdict"] == "supported" and r["confidence"] >= 0.9
    assert all(e["source_tool"] for e in r["evidence"])
    assert "contracts/quality.yml" in r["proposed_fix"]["files"]


def _validate(report, schema):
    """A small JSON-schema check for the strict report tool (required keys, enums, no extras)."""
    if schema["type"] == "object":
        assert set(report) == set(schema["required"]) or set(report) <= set(schema["properties"])
        assert set(schema["required"]) <= set(report)
        for k, v in report.items():
            _validate(v, schema["properties"][k])
    elif schema["type"] == "array":
        for x in report:
            _validate(x, schema["items"])
    elif "enum" in schema:
        assert report in schema["enum"]


def test_offline_report_matches_the_strict_report_schema(monkeypatch):
    monkeypatch.setenv("NEXUS_AGENT", "offline")
    _validate(asyncio.run(oncall_agent.run(str(STATE)))["report"], oncall_agent.REPORT_TOOL["input_schema"])


class FakeClaude:
    """Plays back a scripted investigation and records every request, so the loop is tested without the API."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kw):
        self.requests.append(dict(kw, messages=list(kw["messages"])))   # the loop keeps appending to its list
        return self.script.pop(0)


def _turn(*calls, stop="tool_use"):
    return NS(stop_reason=stop, stop_details=None,
              content=[NS(type="text", text="Looking.")] + [NS(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(calls)])


def test_claude_loop_runs_its_tool_calls_through_the_real_mcp_server():
    state = json.loads(STATE.read_text())
    f = state["failing"][0]
    report = {"title": "t", "severity": "medium", "affected": ["x"], "root_cause": "dup", "evidence": [],
              "hypotheses": [], "proposed_fix": {"summary": "s", "files": [], "test": "t"}, "customer_impact": "c", "confidence": 0.8}
    fake = FakeClaude([
        _turn(("list_failing_checks", {})),
        _turn(("get_check_evidence", {"product": f["product"], "check": f["check"]}),
              ("run_diagnostic", {"name": "same_day_same_amount", "company_id": "C-107"})),
        _turn(("submit_incident_report", report)),
    ])
    inc = asyncio.run(oncall_agent.run(str(STATE), client=fake))
    assert inc["report"] == report and inc["model"] == oncall_agent.MODEL == "claude-opus-5-5"
    first = fake.requests[0]
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "high"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    names = [t["name"] for t in first["tools"]]
    assert "submit_incident_report" in names and "run_diagnostic" in names
    assert next(t for t in first["tools"] if t["name"] == "submit_incident_report")["strict"] is True
    # tool results went back in one user message per turn, and came from the real server
    second = fake.requests[2]["messages"]
    results = second[-1]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert "1250" in results[0]["content"] and "-R" in results[1]["content"]
    tools_called = [t["tool"] for t in inc["transcript"] if t["kind"] == "tool"]
    assert tools_called == ["list_failing_checks", "get_check_evidence", "run_diagnostic"]


def test_a_refusal_is_raised_not_swallowed():
    fake = FakeClaude([NS(stop_reason="refusal", stop_details=NS(category="cyber"), content=[])])
    with pytest.raises(RuntimeError, match="refused"):
        asyncio.run(oncall_agent.run(str(STATE), client=fake))
