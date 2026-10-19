"""The data the site publishes is the data the run produced, and it keeps its promises."""
import json

import pytest

from nexus.paths import ROOT

DATA = ROOT / "assets" / "data"
SITE = json.loads((DATA / "site.json").read_text())
PRODUCTS = {p.stem: json.loads(p.read_text()) for p in (DATA / "products").glob("*.json")}
ACTIVE = {(e["customer_id"], e["company_id"]) for e in SITE["evidence"]["entitlements"] if not e["revoked_at"]}


@pytest.mark.parametrize("name", sorted(PRODUCTS))
def test_every_published_row_has_active_consent(name):
    assert all((r["customer_id"], r["company_id"]) in ACTIVE for r in PRODUCTS[name])


def test_the_revoked_company_is_gone_from_every_product():
    assert not any(r["company_id"] == "C-112" and r["customer_id"] == "brightpay" for rows in PRODUCTS.values() for r in rows)


def test_replaying_every_feed_changed_nothing():
    assert SITE["run"]["bronze"] == SITE["run"]["bronze_after_replay"]


def test_rerunning_the_incremental_fact_changed_nothing():
    assert SITE["run"]["gold_fact"]["rows"] == SITE["run"]["gold_fact"]["rows_after_rerun"]


def test_quarantine_reasons_add_up():
    s = SITE["run"]["silver"]
    assert sum(s["quarantine_reasons"].values()) >= s["invoice_quarantine"] > 0
    assert all(q["_failed_rules"] for q in SITE["evidence"]["quarantine"])


def test_only_the_planted_break_fails():
    fails = [(c["product"], r["check"]) for c in SITE["contracts"] for r in c["results"] if r["status"] == "fail"]
    assert fails == [("insights_cash_flow_monthly", "reconcile net_movement_all to source within 0.01")]
    sample = next(r for c in SITE["contracts"] for r in c["results"] if r["status"] == "fail")["sample"]
    assert {s["company_id"] for s in sample} == {"C-107"} and all(abs(s["difference"] - 1250) < 0.01 for s in sample)


def test_the_restatement_is_v1_and_only_moves_august():
    assert SITE["run"]["as_issued"]["revenue_version"] == 0 and SITE["run"]["current"]["revenue_version"] == 1
    assert SITE["evidence"]["restatement"] and all(r["month"] == "2026-08-01" for r in SITE["evidence"]["restatement"])


def test_the_scd2_remap_keeps_august_as_revenue():
    v = SITE["evidence"]["scd2_c103"]
    assert [x["account_type"] for x in v] == ["revenue", "other_income"]
    assert v[0]["valid_to"] == v[1]["valid_from"] == "2026-09-01" and v[1]["is_current"]


def test_every_commerce_payout_was_found_in_the_bank():
    assert all(r["payouts_in_bank_ratio"] == 1.0 for r in PRODUCTS["insights_commerce_monthly"])


def test_dso_stays_within_its_contract_range():
    assert all(r["dso_days"] is None or 0 <= r["dso_days"] <= 365 for r in PRODUCTS["insights_dso_monthly"])


def test_lineage_matches_the_contract_results():
    lineage = json.loads((DATA / "lineage.json").read_text())
    for c in SITE["contracts"]:
        assert (lineage[c["product"]]["checks_passed"], lineage[c["product"]]["checks_total"]) == (c["passed"], c["total"])


def test_the_browser_catalogue_is_the_semantic_layer():
    import yaml
    yml = yaml.safe_load((ROOT / "semantic" / "metrics.yml").read_text())["metrics"]
    assert json.loads((DATA / "catalogue.json").read_text()) == yml
