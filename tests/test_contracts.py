import json

import pytest
import yaml

from nexus import contracts
from nexus.paths import ROOT

PRODUCTS = contracts.load_products()
IDS = [c["product"] for c in PRODUCTS]


@pytest.mark.parametrize("c", PRODUCTS, ids=IDS)
def test_every_product_contract_compiles_with_grain_freshness_and_tenant_checks(c):
    kinds = {k["kind"] for k in contracts.compile_checks(c)}
    assert {"grain", "freshness", "tenant"} <= kinds


@pytest.mark.parametrize("c", PRODUCTS, ids=IDS)
def test_governance_sets_owner_grants_and_the_row_filter(c):
    gov = contracts.compile_governance(c)
    assert f"SET OWNER TO `{c['owner']}`" in gov
    assert "SET ROW FILTER nexus.governance.tenant_filter ON (customer_id, company_id)" in gov
    assert all(f"TO `{g}`" in gov for g in c["access"]["read"])


@pytest.mark.parametrize("c", PRODUCTS, ids=IDS)
def test_generated_expectations_are_valid_python(c):
    compile(contracts.compile_expectations(c), c["_path"], "exec")


@pytest.mark.parametrize("c", PRODUCTS, ids=IDS)
def test_contract_columns_and_grain_exist_in_the_published_product(c):
    rows = json.loads((ROOT / "assets" / "data" / "products" / f"{c['product']}.json").read_text())
    cols = set(rows[0])
    assert set(c["grain"]) <= cols
    assert {col["name"] for col in c.get("columns", [])} <= cols


@pytest.mark.parametrize("c", PRODUCTS, ids=IDS)
def test_every_contract_names_a_person_who_signs_off_and_one_who_builds(c):
    assert c["owner"].endswith("@example.com") and c["engineer"] and c["definition"].strip()
    assert c["change"]["breaking"] == "owner_approval"


def test_cash_flow_reconciles_to_the_bank_balance():
    c = next(c for c in PRODUCTS if c["product"] == "insights_cash_flow_monthly")
    rec = next(k for k in contracts.compile_checks(c) if k["kind"] == "reconcile")
    assert "bank_balance" in rec["sql"] and "0.01" in rec["sql"]


def test_unknown_column_tests_are_rejected():
    bad = dict(PRODUCTS[0], columns=[{"name": "x", "tests": ["is_lovely"]}])
    with pytest.raises(ValueError):
        contracts.compile_checks(bad)


def test_every_accounting_and_erp_source_maps_onto_the_whole_canonical_invoice():
    from nexus.silver_columns import CANONICAL
    for s in contracts.load_sources():
        if "canonical" in s:
            assert set(s["canonical"]) == set(CANONICAL), s["feed"]
            assert s["target"]["ordering_key"] in s["target"]["merge_keys"] + ["sync_seq", "SyncSeq"]


def test_every_source_declares_an_owner_merge_keys_and_a_data_class():
    for s in contracts.load_sources():
        assert s["owner"] and s["target"]["merge_keys"] and s["governance"]["data_class"], s["feed"]


def test_the_quality_rules_are_plain_sql_predicates():
    rules = yaml.safe_load((ROOT / "contracts" / "quality.yml").read_text())["invoice_quality"]["rules"]
    assert set(rules) == {"ids_present", "status_known", "currency_iso", "due_after_issue", "not_far_future"}
    assert all(";" not in r for r in rules.values())
