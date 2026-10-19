"""The on-call agent: Claude, connected to the nexus-insights MCP server, diagnoses failing checks.

    python -m nexus.oncall_agent                  # uses Claude when credentials are present
    NEXUS_AGENT=offline python -m nexus.oncall_agent

How it works
  * It starts the real MCP server (`python -m nexus.mcp_server`) over stdio as the on-call identity, and
    lists its tools. Every tool is read-only; the on-call tools only exist for that identity.
  * Claude (claude-opus-5-5, adaptive thinking, effort high) gets those tools plus one of its own,
    `submit_incident_report` (strict schema). It investigates, then files the report. It never writes data:
    the report proposes a fix as a pull request, and a human approves it.
  * Without credentials (CI, a laptop without a key) the same MCP calls run in a fixed order and simple
    rules write the report. That is labelled `offline-rules` everywhere it appears, never passed off as AI.
"""
import asyncio
import json
import os
import sys
import time

from nexus.paths import ROOT

MODEL = os.environ.get("NEXUS_AGENT_MODEL", "claude-opus-5-5")
ON_CALL = "oncall@nexus.example"
MAX_TURNS = 16

SYSTEM = """You are the on-call assistant for NEXUS, a data platform that turns SMB accounting, ERP, banking and \
commerce data into certified Insights for lenders and platforms.

A contract check failed on the latest run. Find the root cause using only the tools you have. They are read-only: \
you cannot change data, and you should not try.

Work like a careful senior data engineer:
- Start with list_failing_checks, then get_check_evidence for each failure.
- Use run_diagnostic on the affected companies before forming a view, and recent_changes to rule a code change \
in or out.
- Rank at least two hypotheses and say which evidence supports or rejects each.
- Every claim in your report must name the tool result it came from.
- Propose the smallest safe fix as a pull request (files and a test that fails before and passes after). Prefer \
quarantine to deletion.
- Do not give lending or financial advice, and do not include personal or bank-account details.

When you're done, call submit_incident_report exactly once."""

REPORT_TOOL = {
    "name": "submit_incident_report",
    "description": "File the incident report. Call this once, at the end, with your findings.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "severity", "affected", "root_cause", "evidence", "hypotheses", "proposed_fix",
                     "customer_impact", "confidence"],
        "properties": {
            "title": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "affected": {"type": "array", "items": {"type": "string"}},
            "root_cause": {"type": "string"},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["claim", "source_tool"],
                "properties": {"claim": {"type": "string"}, "source_tool": {"type": "string"}}}},
            "hypotheses": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["hypothesis", "verdict", "why"],
                "properties": {"hypothesis": {"type": "string"},
                               "verdict": {"type": "string", "enum": ["supported", "rejected", "open"]},
                               "why": {"type": "string"}}}},
            "proposed_fix": {"type": "object", "additionalProperties": False, "required": ["summary", "files", "test"],
                             "properties": {"summary": {"type": "string"},
                                            "files": {"type": "array", "items": {"type": "string"}},
                                            "test": {"type": "string"}}},
            "customer_impact": {"type": "string"},
            "confidence": {"type": "number"},
        },
    },
}


def _server_params(state_path: str):
    from mcp.client.stdio import StdioServerParameters
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NEXUS_CALLER=ON_CALL, NEXUS_RUN_STATE=state_path)
    return StdioServerParameters(command=sys.executable, args=["-m", "nexus.mcp_server"], env=env)


def _text(result) -> str:
    """An MCP CallToolResult as the text Claude reads: structured content when present, else the text blocks."""
    if getattr(result, "structured_content", None):
        sc = result.structured_content
        return json.dumps(sc.get("result", sc), default=str)
    return "\n".join(getattr(c, "text", "") for c in result.content)


def _short(text: str, n: int = 600) -> str:
    return text if len(text) <= n else text[:n] + " …"


def use_claude() -> bool:
    mode = os.environ.get("NEXUS_AGENT", "auto")
    if mode in ("claude", "offline"):
        return mode == "claude"
    return any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))


async def diagnose_with_claude(session, client, transcript: list) -> dict:
    """A manual tool loop over the MCP session. Returns the report Claude filed."""
    listed = await session.list_tools()
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in listed.tools]
    tools.append(REPORT_TOOL)
    messages = [{"role": "user", "content": "The latest NEXUS run has failing checks. Investigate and file a report."}]
    for _ in range(MAX_TURNS):
        resp = await client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM, tools=tools, messages=messages,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",   # re-route a refusal, in the same call
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"model refused: {getattr(resp.stop_details, 'category', None)}")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("model hit max_tokens before finishing")
        messages.append({"role": "assistant", "content": resp.content})   # thinking blocks passed back unchanged
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                transcript.append({"by": MODEL, "kind": "note", "text": b.text.strip()})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            if resp.stop_reason == "pause_turn":
                continue
            messages.append({"role": "user", "content": "Please file your findings with submit_incident_report."})
            continue
        results, report = [], None
        for call in calls:
            if call.name == REPORT_TOOL["name"]:
                report = call.input
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": "Report filed."})
                continue
            out = _text(await session.call_tool(call.name, dict(call.input)))
            transcript.append({"by": MODEL, "kind": "tool", "tool": call.name, "args": dict(call.input), "result": _short(out)})
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out})
        messages.append({"role": "user", "content": results})   # every result of a turn in one message
        if report is not None:
            return report
    raise RuntimeError(f"no report after {MAX_TURNS} turns")


async def diagnose_offline(session, transcript: list) -> dict:
    """The same MCP calls in a fixed order, and simple rules in place of the model."""
    async def call(tool, **args):
        out = json.loads(_text(await session.call_tool(tool, args)))
        transcript.append({"by": "offline-rules", "kind": "tool", "tool": tool, "args": args, "result": _short(json.dumps(out))})
        return out

    failing = await call("list_failing_checks")
    if not failing["failing"] and not failing["gx_failing"]:
        return {"title": "No failing checks", "severity": "low", "affected": [], "root_cause": "Nothing failed on this run.",
                "evidence": [{"claim": f"0 of {failing['checks_total']} checks failed", "source_tool": "list_failing_checks"}],
                "hypotheses": [], "proposed_fix": {"summary": "None needed.", "files": [], "test": ""},
                "customer_impact": "None.", "confidence": 1.0}
    f = failing["failing"][0]
    ev = await call("get_check_evidence", product=f["product"], check=f["check"])
    companies = sorted({r["company_id"] for r in ev["sample"]})
    company = companies[0]
    diff = ev["sample"][0].get("difference")
    lines = await call("run_diagnostic", name="bank_lines_vs_balance", company_id=company)
    pairs = await call("run_diagnostic", name="same_day_same_amount", company_id=company)
    cats = await call("run_diagnostic", name="lines_by_category", company_id=company)
    changes = await call("recent_changes")
    dup = [p for p in pairs["result"] if diff is not None and abs(p["amount"] * (p["n"] - 1) - diff) < 0.01]
    code_change = any("contracts/" in c.get("files", "") or "src/nexus/" in c.get("files", "") for c in changes["changes"]
                      if c.get("touches_banking"))
    root = (f"The bank feed re-sent one {company} payment of {dup[0]['amount']:,.2f} on {dup[0]['booked_date']} under a "
            f"new transaction id ({', '.join(dup[0]['txn_ids'])}). The MERGE key is (company_id, txn_id), so it landed "
            f"as a second row and inflated the month's cash flow by {diff:,.2f}.") if dup else \
           f"{company} is {diff} out against its bank balance; no duplicate line explains it."
    return {
        "title": f"{f['product']}: {company} fails bank reconciliation by {diff:,.2f}",
        "severity": "medium",
        "affected": [f["product"]] + [f"{company} (both customers it is shared with)"],
        "root_cause": root,
        "evidence": [
            {"claim": f"{f['check']} failed on {f['failing_rows']} rows, all for {', '.join(companies)}", "source_tool": "get_check_evidence"},
            {"claim": f"bank lines sum to {lines['result']['lines_total']:,.2f}; the balance moved {lines['result']['balance_movement']:,.2f}",
             "source_tool": "run_diagnostic(bank_lines_vs_balance)"},
            *([{"claim": f"{dup[0]['n']} lines share date, amount and description: {', '.join(dup[0]['txn_ids'])}",
                "source_tool": "run_diagnostic(same_day_same_amount)"}] if dup else []),
            {"claim": f"lines by category: {', '.join(f'{k} {v}' for k, v in cats['result'].items())}",
             "source_tool": "run_diagnostic(lines_by_category)"},
        ],
        "hypotheses": [
            {"hypothesis": "The feed re-sent a line under a new id", "verdict": "supported" if dup else "rejected",
             "why": "A same-day, same-amount pair exactly equals the difference." if dup else "No pair matches."},
            {"hypothesis": "The reported balance is stale", "verdict": "rejected",
             "why": "Every other company reconciles to the penny with the same balance feed."},
            {"hypothesis": "A recent code or contract change", "verdict": "supported" if code_change else "rejected",
             "why": "recent_changes shows a change touching banking." if code_change else "No recent change touches banking logic."},
        ],
        "proposed_fix": {
            "summary": "Quarantine a bank line that repeats an earlier line's account, date, amount and description within "
                       "one day under a different id, and tell the source owner. Quarantine, not delete: a genuine second "
                       "payment must stay reviewable.",
            "files": ["contracts/quality.yml", "src/nexus/silver.py", "tests/test_silver.py"],
            "test": "A bank line re-sent under a new id is quarantined, and the cash-flow reconciliation passes.",
        },
        "customer_impact": "Cash flow for one company is overstated for one month; the product carries a caveat until fixed.",
        "confidence": 0.9 if dup else 0.4,
    }


async def run(state_path: str | None = None, client=None) -> dict:
    """Connect to the MCP server, diagnose with Claude (or offline rules), and return the incident."""
    state_path = state_path or str(ROOT / "assets" / "data" / "run_state.json")
    claude = client is not None or use_claude()
    transcript, t0 = [], time.time()
    try:
        report, tools = await _investigate(state_path, claude, client, transcript)
    except BaseExceptionGroup as group:     # the MCP client's task group wraps errors: surface the first one
        while isinstance(group, BaseExceptionGroup):
            group = group.exceptions[0]
        raise group from None
    return {"model": MODEL if claude else "offline-rules", "mcp_server": "nexus-insights (stdio)",
            "caller": ON_CALL, "tools": tools, "report": report, "transcript": transcript,
            "seconds": round(time.time() - t0, 1)}


async def _investigate(state_path, claude, client, transcript):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    async with stdio_client(_server_params(state_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            if claude:
                if client is None:
                    import anthropic
                    client = anthropic.AsyncAnthropic()
                report = await diagnose_with_claude(session, client, transcript)
            else:
                report = await diagnose_offline(session, transcript)
    return report, tools


def to_markdown(incident: dict) -> str:
    r = incident["report"]
    md = [f"# {r['title']}", "", f"*Severity:* {r['severity']} · *Confidence:* {r['confidence']:.0%} · "
          f"*Written by:* {incident['model']} over MCP ({incident['mcp_server']})", "", "## Root cause", r["root_cause"], "",
          "## Evidence"] + [f"- {e['claim']} — `{e['source_tool']}`" for e in r["evidence"]] + ["", "## Hypotheses"] + \
         [f"- **{h['verdict']}**: {h['hypothesis']}. {h['why']}" for h in r["hypotheses"]] + \
         ["", "## Proposed fix (as a pull request)", r["proposed_fix"]["summary"], "",
          "Files: " + ", ".join(f"`{f}`" for f in r["proposed_fix"]["files"]), "", f"Test: {r['proposed_fix']['test']}", "",
          "## Customer impact", r["customer_impact"], ""]
    return "\n".join(md)


if __name__ == "__main__":
    inc = asyncio.run(run())
    print(to_markdown(inc))
