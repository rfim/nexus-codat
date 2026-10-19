"""The planner that stands in for the LLM: routing, parsing and refusals."""
import pytest

from nexus import agent


@pytest.mark.parametrize("q, month", [
    ("revenue in august 2026", "2026-08"), ("revenue for 2026-07", "2026-07"), ("cash flow in sep", "2026-09"),
    ("revenue in may", "2026-05"), ("revenue by month", None), ("gross margin for c-104", None)])
def test_month_parsing(q, month):
    assert agent._month(q) == month


@pytest.mark.parametrize("q, reason", [
    ("List the counterparty bank details for C-104", "personal_data"),
    ("What's the email for C-101?", "personal_data"),
    ("Should we lend to C-107?", "advice"),
    ("Can you approve this loan?", "advice"),
    ("What's the weather?", "unknown_metric")])
def test_refusals_happen_before_any_tool_call(q, reason):
    p = agent.plan(q)
    assert p.get("refuse") == reason and "tool" not in p


def test_longest_synonym_wins():
    assert agent.plan("Online sales for C-101")["args"]["name"] == "commerce_net_sales"
    assert agent.plan("Sales for C-101")["args"]["name"] == "revenue"


@pytest.mark.parametrize("q, tool", [
    ("How do you define revenue?", "describe_metric"), ("What is DSO", "describe_metric"),
    ("Where does the cash flow number come from?", "get_lineage"),
    ("Revenue for C-104 in August", "query_metric")])
def test_routing_to_the_right_tool(q, tool):
    assert agent.plan(q)["tool"] == tool


def test_arguments_are_extracted():
    a = agent.plan("Show revenue by month for c-108 per company")["args"]
    assert a == {"name": "revenue", "group_by": ["month", "company_id"], "company_id": "C-108"}
