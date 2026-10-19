"""Synthetic SMB feeds, as two fictional accounting platforms and a fictional mid-market ERP and a bank feed would send them.

Twelve companies, two Codat-style customers (a lender and a payments platform) and three
accounting platforms that describe the same invoice three different ways. The feeds carry the
problems the pipeline exists to handle:
  * replayed sync pages (the same records sent twice),
  * malformed rows (unknown status, bad currency, due before issue),
  * a chart-of-accounts remap part-way through the period (SCD2),
  * a late batch of backdated credit notes that restates last month's revenue,
  * a revoked consent: one company stops being visible to one customer,
  * one planted break: a bank line re-sent under a new id, which the cash-flow contract catches.
No real company, customer or platform data is used.
"""
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

from nexus.spark import ROOT

LANDING = ROOT / "landing"
RUN_DATE = date(2026, 9, 30)
START = date(2026, 6, 1)
SEED = 7

PLATFORMS = ("ledgerone", "bookwise", "orbiterp")
COMMERCE = {"C-101", "C-105", "C-107", "C-112"}  # sell online too, through a fictional commerce platform "ShopLane"
INDUSTRIES = ("Coffee roaster", "Joinery", "Design studio", "Bike repair", "Florist", "IT support",
              "Bakery", "Dental lab", "Print shop", "Catering", "Physio clinic", "Garden centre")
CUSTOMERS = {"northbank": "Northbank Lending (fictional lender)",
             "brightpay": "Brightpay (fictional payments platform)"}

# the bank line re-sent under a new id: the cash-flow contract must catch it
PLANTED = {"company_id": "C-107", "booked_date": "2026-08-14", "amount": 1250.00}


def _write(feed: str, rows: list[dict], part: str = "part-0") -> int:
    d = LANDING / feed
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{part}.json").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return len(rows)


def _days(a: date, b: date):
    while a <= b:
        yield a
        a += timedelta(days=1)


def _companies(rng):
    out = []
    for i, industry in enumerate(INDUSTRIES):
        out.append({"company_id": f"C-{101 + i}", "company_name": f"{industry} Ltd (synthetic)",
                    "industry": industry, "platform": PLATFORMS[i % 3],
                    "currency": "EUR" if i == 9 else "GBP", "connected_at": "2026-05-20T09:00:00Z",
                    "sync_seq": 1})
    return out


def _entitlements(companies):
    rows = []
    for i, c in enumerate(companies):
        # the lender sees the first eight, the payments platform the last six: C-107 and C-108 are shared
        if i < 8:
            rows.append({"customer_id": "northbank", "company_id": c["company_id"], "purpose": "lending_assessment",
                         "granted_at": "2026-05-20T09:00:00Z", "revoked_at": None})
        if i >= 6:
            rows.append({"customer_id": "brightpay", "company_id": c["company_id"], "purpose": "merchant_insights",
                         "granted_at": "2026-05-20T09:00:00Z",
                         # C-112 disconnects from Brightpay in September
                         "revoked_at": "2026-09-12T16:40:00Z" if c["company_id"] == "C-112" else None})
    return rows


def _accounts(companies):
    """Chart of accounts per company. Each platform names and types them differently."""
    rows, remaps = [], []
    for c in companies:
        for acc_id, name, kind in (("4000", "Sales", "revenue"), ("4100", "Services", "revenue"),
                                   ("4900", "Other income", "other_income"), ("5000", "Cost of sales", "direct_cost")):
            rows.append({"company_id": c["company_id"], "account_id": acc_id, "account_name": name,
                         "account_type": kind, "is_active": True, "updated_at": "2026-05-20T09:00:00Z"})
    # C-103 reclassifies "Services" as other income from 1 September: March-August must not change
    remaps.append({"company_id": "C-103", "account_id": "4100", "account_name": "Services (grant-funded)",
                   "account_type": "other_income", "is_active": True, "updated_at": "2026-09-01T08:00:00Z"})
    return rows, remaps


def _invoices(rng, companies):
    """Canonical invoices first; each platform then renders them in its own schema."""
    canon = []
    for c in companies:
        n = 0
        size = rng.choice((180, 320, 650, 1400))
        for day in _days(START, RUN_DATE):
            if day.weekday() >= 5 or rng.random() > 0.38:
                continue
            n += 1
            subtotal = round(rng.uniform(0.4, 1.8) * size, 2)
            tax = round(subtotal * 0.2, 2)
            days_to_pay = rng.choice((7, 14, 21, 30, 30, 45, 60))
            paid_on = day + timedelta(days=days_to_pay + rng.randint(-3, 12))
            status = "paid" if paid_on <= RUN_DATE else "open"
            if rng.random() < 0.03:
                status = "void"
            canon.append({"company_id": c["company_id"], "platform": c["platform"], "n": n,
                          "issue_date": day, "due_date": day + timedelta(days=days_to_pay),
                          "subtotal": subtotal, "tax": tax, "total": round(subtotal + tax, 2),
                          "paid_date": paid_on if status == "paid" else None, "status": status,
                          "account_id": rng.choice(("4000", "4000", "4100")), "currency": c["currency"],
                          "doc_type": "invoice"})
    return canon


LEDGERONE_STATUS = {"draft": "DRAFT", "open": "AUTHORISED", "paid": "PAID", "void": "VOIDED"}
BOOKWISE_STATUS = {"draft": "open", "open": "open", "paid": "closed", "void": "void"}
ORBITERP_STATUS = {"draft": 0, "open": 1, "paid": 3, "void": 4}


def _render(inv: dict, seq: int, modified: str) -> tuple[str, dict]:
    """One canonical invoice in the platform's own schema."""
    p = inv["platform"]
    amount_due = 0.0 if inv["status"] in ("paid", "void") else inv["total"]
    if inv["doc_type"] == "credit_note":
        amount_due = 0.0
    if p == "ledgerone":
        return p, {"CompanyId": inv["company_id"],
                   "InvoiceID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{inv['company_id']}/{inv['n']}/{inv['doc_type']}")),
                   "Type": "ACCRECCREDIT" if inv["doc_type"] == "credit_note" else "ACCREC",
                   "Status": LEDGERONE_STATUS[inv["status"]], "Date": str(inv["issue_date"]),
                   "DueDate": str(inv["due_date"]), "SubTotal": inv["subtotal"], "TotalTax": inv["tax"],
                   "Total": inv["total"], "AmountDue": amount_due, "CurrencyCode": inv["currency"],
                   "AccountCode": inv["account_id"],
                   "FullyPaidOnDate": str(inv["paid_date"]) if inv["paid_date"] else None,
                   "UpdatedDateUTC": modified, "SyncSeq": seq}
    if p == "bookwise":
        sign = -1 if inv["doc_type"] == "credit_note" else 1
        return p, {"company": inv["company_id"], "id": int(inv["company_id"][2:]) * 100000 + inv["n"] * 10 +
                   (1 if inv["doc_type"] == "credit_note" else 0),
                   "doc": "credit_memo" if inv["doc_type"] == "credit_note" else "invoice",
                   "state": BOOKWISE_STATUS[inv["status"]], "txn_date": str(inv["issue_date"]),
                   "due": str(inv["due_date"]), "net": sign * inv["subtotal"], "vat": sign * inv["tax"],
                   "balance": amount_due, "currency_ref": inv["currency"], "income_account": inv["account_id"],
                   "paid_on": str(inv["paid_date"]) if inv["paid_date"] else None,
                   "last_updated": modified, "sync_seq": seq}
    # an ERP posts to a subsidiary's receivables ledger, with document series instead of one invoice id
    return p, {"company": inv["company_id"], "subsidiary": "UK01", "ledger": "AR-TRADE", "series": "CN" if inv["doc_type"] == "credit_note" else "INV",
               "doc_number": inv["n"], "status_code": ORBITERP_STATUS[inv["status"]],
               "created": f"{inv['issue_date']}T10:00:00Z", "terms_days": (inv["due_date"] - inv["issue_date"]).days,
               "lines_total": inv["subtotal"], "tax_total": inv["tax"], "paid_total": 0.0 if amount_due else inv["total"],
               "gl": inv["account_id"], "paid_at": f"{inv['paid_date']}T12:00:00Z" if inv["paid_date"] else None,
               "sync_seq": seq}  # OrbitERP sends no modified time: the sync sequence orders versions


def _commerce(rng, companies):
    """Daily commerce payouts (gross sales - refunds - fees), paid to the bank two days later."""
    rows = []
    for c in (c for c in companies if c["company_id"] in COMMERCE):
        for day in _days(START, RUN_DATE - timedelta(days=2)):
            gross = round(rng.uniform(80, 900) * (1.4 if day.weekday() >= 5 else 1), 2)
            refunds = round(gross * rng.choice((0, 0, 0, 0.03, 0.08)), 2)
            fees = round((gross - refunds) * 0.029 + 0.2, 2)
            rows.append({"merchant_id": c["company_id"], "payout_id": f"po_{c['company_id'][2:]}{day:%m%d}",
                         "sales_date": str(day), "arrival_date": str(day + timedelta(days=2)),
                         "gross_sales": gross, "refunds": refunds, "fees": fees,
                         "payout_amount": round(gross - refunds - fees, 2), "currency": c["currency"]})
    return rows


def _bank(rng, companies, invoices, payouts):
    rows, balances = [], []
    for c in companies:
        cid, acct = c["company_id"], f"{c['company_id']}-CUR"
        txns = []
        for inv in invoices:
            if inv["company_id"] == cid and inv["paid_date"] and inv["doc_type"] == "invoice":
                txns.append((inv["paid_date"], inv["total"], "Customer payment", "receipt"))
        for day in _days(START, RUN_DATE):
            if day.weekday() < 5 and rng.random() < 0.45:
                txns.append((day, -round(rng.uniform(60, 900), 2), rng.choice(
                    ("Supplier payment", "Card purchase", "Payroll", "HMRC VAT", "Rent")), "payment"))
            if day.day == 1:
                # moving money between the company's own accounts is not operating cash flow
                txns.append((day, -1500.00, "Transfer to savings", "own_transfer"))
        for po in (p for p in payouts if p["merchant_id"] == cid):
            txns.append((date.fromisoformat(po["arrival_date"]), po["payout_amount"], "ShopLane payout", "commerce_payout"))
        txns.append((date(2026, 7, 3), 10000.00, "Loan drawdown", "loan_drawdown"))
        if cid == PLANTED["company_id"]:
            txns.append((date.fromisoformat(PLANTED["booked_date"]), PLANTED["amount"], "Customer payment", "receipt"))
        opening = round(rng.uniform(4000, 20000), 2)
        balance, seq = opening, 0
        for i, (day, amt, desc, kind) in enumerate(sorted(t for t in txns if t[0] <= RUN_DATE)):
            seq += 1
            rows.append({"company_id": cid, "account_id": acct, "txn_id": f"{cid}-T{i:05d}",
                         "booked_date": str(day), "amount": amt, "currency": c["currency"],
                         "description": desc, "category": kind,
                         "counterparty_iban": f"GB{rng.randint(10, 99)}SYNT{rng.randint(10**13, 10**14 - 1)}",
                         "sync_seq": seq})
            balance = round(balance + amt, 2)
        balances.append({"company_id": cid, "account_id": acct, "opening_balance": opening,
                         "opening_date": str(START), "closing_balance": balance, "closing_date": str(RUN_DATE)})
    return rows, balances


def generate() -> dict:
    rng = random.Random(SEED)
    if LANDING.exists():
        for p in sorted(LANDING.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    companies = _companies(rng)
    accounts, remaps = _accounts(companies)
    invoices = _invoices(rng, companies)
    payouts = _commerce(rng, companies)
    bank, balances = _bank(rng, companies, invoices, payouts)

    by_platform = {p: [] for p in PLATFORMS}
    for i, inv in enumerate(invoices):
        p, row = _render(inv, seq=i + 1, modified=f"{inv['issue_date']}T18:00:00Z")
        by_platform[p].append(row)

    # malformed rows the source contract must quarantine
    bad = by_platform["ledgerone"][:3]
    bad = [dict(bad[0], InvoiceID="bad-status", Status="SUBMITTED"),
           dict(bad[1], InvoiceID="bad-currency", CurrencyCode="XX"),
           dict(bad[2], InvoiceID="bad-dates", DueDate="2026-05-01")]
    bad_bw = dict(by_platform["bookwise"][0], id=999999999, state="pending")

    counts = {"companies": _write("companies", companies),
              "entitlements": _write("entitlements", _entitlements(companies)),
              "accounts": _write("accounts", accounts)}
    _write("accounts", remaps, "part-1-remap")
    counts["accounts_remapped"] = len(remaps)
    for p in PLATFORMS:
        rows = by_platform[p] + (bad if p == "ledgerone" else [bad_bw] if p == "bookwise" else [])
        counts[f"{p}_invoices"] = _write(f"{p}_invoices", rows)
        # the platform re-sends its last sync page: the same 60 records again
        _write(f"{p}_invoices", rows[-60:], "part-1-replayed-page")
        counts[f"{p}_invoices_replayed"] = 60

    # the planted break: one bank line re-sent under a new id (a duplicate the key cannot catch)
    orig = next(r for r in bank if r["company_id"] == PLANTED["company_id"]
                and r["booked_date"] == PLANTED["booked_date"] and r["amount"] == PLANTED["amount"])
    dup = dict(orig, txn_id=orig["txn_id"] + "-R", sync_seq=orig["sync_seq"] + 10000)
    counts["bank_transactions"] = _write("bank_transactions", bank + [dup])
    counts["bank_balances"] = _write("bank_balances", balances)
    counts["commerce_payouts"] = _write("commerce_payouts", payouts)

    # a day later: backdated credit notes for August, and a few invoices voided after the fact
    late = []
    for inv in [i for i in invoices if i["issue_date"].month == 8 and i["status"] == "paid"][::5][:24]:
        cn = dict(inv, doc_type="credit_note", status="paid", subtotal=round(inv["subtotal"] * 0.25, 2),
                  tax=round(inv["tax"] * 0.25, 2), total=round(inv["total"] * 0.25, 2),
                  issue_date=inv["issue_date"] + timedelta(days=3), paid_date=inv["issue_date"] + timedelta(days=3))
        late.append(_render(cn, seq=900000 + len(late), modified="2026-10-01T07:30:00Z"))
    for inv in [i for i in invoices if i["issue_date"].month == 8 and i["status"] == "open"][:16]:
        late.append(_render(dict(inv, status="void"), seq=950000 + len(late), modified="2026-10-01T07:31:00Z"))
    for p in PLATFORMS:
        rows = [r for pl, r in late if pl == p]
        _write(f"{p}_invoices_late", rows)
        counts[f"{p}_invoices_late"] = len(rows)
    counts["late_total"] = len(late)
    counts["planted_break"] = PLANTED
    return counts


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2, default=str))
