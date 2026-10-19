from nexus import contracts


def test_every_product_contract_compiles_with_a_tenant_check():
    for c in contracts.load_products():
        kinds = {k["kind"] for k in contracts.compile_checks(c)}
        assert {"grain", "freshness", "tenant"} <= kinds, c["product"]
        gov = contracts.compile_governance(c)
        assert "SET ROW FILTER" in gov and "GRANT SELECT" in gov


def test_cash_flow_reconciles_to_the_bank_balance():
    c = next(c for c in contracts.load_products() if c["product"] == "insights_cash_flow_monthly")
    rec = next(k for k in contracts.compile_checks(c) if k["kind"] == "reconcile")
    assert "bank_balance" in rec["sql"] and "0.01" in rec["sql"]
