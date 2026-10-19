"""One YAML contract in, SQL checks, an expectation set and Unity Catalog governance out."""
from nexus import contracts

c = next(c for c in contracts.load_products() if c["product"] == "insights_cash_flow_monthly")
print(c["definition"])
for chk in contracts.compile_checks(c):
    print(f"\n-- {chk['check']}  [{chk['kind']}]\n{chk['sql']}")
print("\n" + contracts.compile_governance(c))
