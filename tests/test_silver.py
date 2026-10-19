"""Silver on Spark: three schemas become one invoice, and bad rows are quarantined with their reasons."""
import json
import tempfile
from datetime import date
from pathlib import Path

from pyspark.sql import functions as F

from nexus import contracts, generate, silver
from nexus.spark import table


def _land(spark, invoices):
    """Render each invoice in its platform's own schema and land it the way bronze does: JSON in, Delta out."""
    for p in generate.PLATFORMS:
        rows = [generate._render(i, seq=n + 1, modified="2026-08-01T18:00:00Z")[1]
                for n, i in enumerate(invoices) if i["platform"] == p]
        f = Path(tempfile.mkdtemp()) / "page.json"
        f.write_text("\n".join(json.dumps(r) for r in rows))
        (spark.read.json(str(f)).withColumn("_ingested_at", F.current_timestamp())
         .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("bronze", f"{p}_invoice")))


def _inv(platform, n, **kw):
    base = {"company_id": "C-900", "platform": platform, "n": n, "issue_date": date(2026, 8, 3), "due_date": date(2026, 9, 2),
            "subtotal": 100.0, "tax": 20.0, "total": 120.0, "paid_date": None, "status": "open", "account_id": "4000",
            "currency": "GBP", "doc_type": "invoice"}
    return base | kw


def test_three_systems_one_canonical_invoice(spark):
    _land(spark, [_inv(p, 1) for p in generate.PLATFORMS] + [_inv("bookwise", 2, doc_type="credit_note", total=24.0, subtotal=20.0, tax=4.0)])
    valid, quarantined = silver.split_by_contract(spark, contracts.load_sources())
    assert (valid, quarantined) == (4, 0)
    got = {(r.source_platform, r.doc_type): (r.status, float(r.subtotal), float(r.total), str(r.due_date))
           for r in spark.table(table("silver", "invoice")).collect()}
    for p in generate.PLATFORMS:
        assert got[(p, "invoice")] == ("open", 100.0, 120.0, "2026-09-02")
    assert got[("bookwise", "credit_note")][1] == -20.0          # credit notes are negative documents


def test_bad_rows_are_quarantined_with_every_failed_rule(spark):
    _land(spark, [_inv(p, 1) for p in generate.PLATFORMS] +
          [_inv("ledgerone", 2, currency="XX", due_date=date(2026, 7, 1))])
    valid, quarantined = silver.split_by_contract(spark, contracts.load_sources())
    assert (valid, quarantined) == (3, 1)
    rules = spark.table(table("silver", "invoice_quarantine")).first()._failed_rules
    assert sorted(rules) == ["currency_iso", "due_after_issue"]
