"""The synthetic feeds carry exactly the problems the pipeline exists to handle."""
import json

from nexus import generate as g


def _rows(feed, part="part-0"):
    return [json.loads(line) for line in (g.LANDING / feed / f"{part}.json").read_text().splitlines()]


def test_generation_is_deterministic():
    first = g.generate()
    a = (g.LANDING / "bookwise_invoices" / "part-0.json").read_text()
    second = g.generate()
    assert first == second
    assert a == (g.LANDING / "bookwise_invoices" / "part-0.json").read_text()


def test_every_accounting_and_erp_system_resends_its_last_page():
    g.generate()
    for p in g.PLATFORMS:
        page = _rows(f"{p}_invoices", "part-1-replayed-page")
        assert len(page) == 60 and page == _rows(f"{p}_invoices")[-60:]


def test_the_three_systems_use_three_different_schemas():
    g.generate()
    keys = {p: set(_rows(f"{p}_invoices")[0]) for p in g.PLATFORMS}
    assert not keys["ledgerone"] & keys["bookwise"]
    assert {"subsidiary", "ledger", "series", "doc_number"} <= keys["orbiterp"]   # ERP-shaped
    assert "UpdatedDateUTC" in keys["ledgerone"] and "last_updated" in keys["bookwise"]


def test_malformed_rows_are_planted_for_the_quality_gate():
    g.generate()
    ids = {r["InvoiceID"] for r in _rows("ledgerone_invoices")}
    assert {"bad-status", "bad-currency", "bad-dates"} <= ids
    assert any(r["state"] == "pending" for r in _rows("bookwise_invoices"))


def test_the_planted_bank_break_is_one_exact_duplicate_under_a_new_id():
    g.generate()
    bank = _rows("bank_transactions")
    hits = [r for r in bank if r["company_id"] == "C-107" and r["booked_date"] == "2026-08-14" and r["amount"] == 1250.0]
    assert len(hits) == 2
    a, b = sorted(hits, key=lambda r: r["sync_seq"])
    assert b["txn_id"] == a["txn_id"] + "-R"
    assert {k: v for k, v in a.items() if k not in ("txn_id", "sync_seq")} == \
           {k: v for k, v in b.items() if k not in ("txn_id", "sync_seq")}


def test_bank_balances_explain_every_line_except_the_duplicate():
    g.generate()
    bank, bal = _rows("bank_transactions"), {r["company_id"]: r for r in _rows("bank_balances")}
    for cid, b in bal.items():
        moved = round(sum(r["amount"] for r in bank if r["company_id"] == cid and not r["txn_id"].endswith("-R")), 2)
        assert abs(moved - (b["closing_balance"] - b["opening_balance"])) < 0.01, cid


def test_consent_one_revocation_and_two_shared_companies():
    g.generate()
    ent = _rows("entitlements")
    revoked = [(e["customer_id"], e["company_id"]) for e in ent if e["revoked_at"]]
    assert revoked == [("brightpay", "C-112")]
    by_co = {}
    for e in ent:
        by_co.setdefault(e["company_id"], set()).add(e["customer_id"])
    assert sorted(c for c, s in by_co.items() if len(s) == 2) == ["C-107", "C-108"]


def test_one_account_is_remapped_on_1_september():
    g.generate()
    remap = _rows("accounts", "part-1-remap")
    assert remap == [r for r in remap if r["company_id"] == "C-103" and r["account_id"] == "4100"]
    assert remap[0]["account_type"] == "other_income" and remap[0]["updated_at"].startswith("2026-09-01")


def test_late_batch_is_backdated_and_newer():
    g.generate()
    late = [r for p in g.PLATFORMS for r in _rows(f"{p}_invoices_late")]
    first = {p: max(r.get("SyncSeq", r.get("sync_seq")) for r in _rows(f"{p}_invoices")) for p in g.PLATFORMS}
    assert late and min(r.get("SyncSeq", r.get("sync_seq")) for r in late) > max(first.values())


def test_commerce_payouts_arrive_two_days_after_sales():
    g.generate()
    for po in _rows("commerce_payouts"):
        assert po["merchant_id"] in g.COMMERCE
        assert abs(po["payout_amount"] - (po["gross_sales"] - po["refunds"] - po["fees"])) < 0.011
