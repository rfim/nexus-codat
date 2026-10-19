"""A small rule-based router that stands in for the LLM: question -> MCP tool calls -> cited answer.

It exists so the evals and the browser demo are deterministic. A real agent replaces `plan()` with a
model; the tools, the tenant filter, the refusals and the evals stay exactly the same.
"""
import re

from nexus import mcp_server, semantic

MONTHS = {m: i + 1 for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"))}
PERSONAL = ("iban", "bank details", "account number", "sort code", "email", "phone", "address", "counterparty")
ADVICE = ("should i lend", "should we lend", "approve", "recommend", "is it safe to lend", "credit decision")


def _month(q: str) -> str | None:
    if m := re.search(r"(20\d\d)-(\d\d)", q):
        return f"{m.group(1)}-{m.group(2)}"
    for name, n in MONTHS.items():
        if re.search(rf"\b({name}|{name[:3]})\b", q):
            year = re.search(r"20\d\d", q)
            return f"{year.group(0) if year else '2026'}-{n:02d}"
    return None


def plan(question: str) -> dict:
    """Map a question to one tool call, or to a refusal."""
    q = question.lower()
    if any(w in q for w in PERSONAL):
        return {"refuse": "personal_data", "message": "I can't share row-level personal or bank details. "
                "I can answer with certified, aggregated metrics."}
    if any(w in q for w in ADVICE):
        return {"refuse": "advice", "message": "I can show the data behind a decision, but I don't make lending "
                "decisions or give financial advice."}
    cat = semantic.catalogue()
    hits = [m for m in cat.values() if any(s in q for s in m.get("synonyms", []))]
    hits.sort(key=lambda m: -max(len(s) for s in m["synonyms"] if s in q))
    if not hits:
        return {"refuse": "unknown_metric", "message": "That isn't a metric in the catalogue. "
                "Try revenue, growth, cash flow, DSO or data completeness."}
    metric = hits[0]
    if "define" in q or "definition" in q or "how do you calculate" in q or "what is" in q and "for" not in q:
        return {"tool": "describe_metric", "args": {"name": metric["name"]}}
    if "where does" in q or "lineage" in q or "come from" in q:
        return {"tool": "get_lineage", "args": {"name": metric["name"]}}
    args = {"name": metric["name"], "group_by": []}
    if c := re.search(r"\bc-\d{3}\b", q):
        args["company_id"] = c.group(0).upper()
    if "by month" in q or "trend" in q or "each month" in q or "monthly" in q:
        args["group_by"].append("month")
    if "by company" in q or "each company" in q or "which compan" in q or "per company" in q:
        args["group_by"].append("company_id")
    if month := _month(q):
        args["month_from"] = month
    return {"tool": "query_metric", "args": args}


def ask(question: str, principal: str) -> dict:
    """Run the plan through the real MCP tool functions, as `principal`."""
    import os
    os.environ["NEXUS_CALLER"] = principal
    p = plan(question)
    if "refuse" in p:
        return {"question": question, "plan": p, "result": {"refused": True, "reason": p["refuse"],
                                                           "message": p["message"]}}
    result = getattr(mcp_server, p["tool"])(**p["args"])
    return {"question": question, "plan": p, "result": result}
