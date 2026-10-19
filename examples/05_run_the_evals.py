"""The agent's eval set: each question, the tool it chose, and whether the answer passed."""
import yaml

from nexus import agent, semantic

cases = yaml.safe_load((semantic.ROOT / "evals" / "questions.yml").read_text())
ok = 0
for c in cases:
    out = agent.ask(c["ask"], c["as"])
    exp, res = c["expect"], out["result"]
    passed = bool(res.get("refused")) and res.get("reason") == exp.get("reason") if exp.get("refuses") \
        else out["plan"].get("tool") == exp["tool"]
    ok += passed
    print(f"{'PASS' if passed else 'FAIL'}  {c['id']:<12} {out['plan'].get('tool') or 'refused':<16} {c['ask']}")
print(f"\n{ok}/{len(cases)} passed (the full checks, values included, run in tests/test_mcp.py)")
