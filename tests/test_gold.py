"""Gold on Spark: the as-of join keeps history, consent scopes every product, and re-runs change nothing."""
from datetime import date, datetime
from decimal import Decimal as D

from nexus import gold
from nexus.spark import table

INV = ("company_id STRING, source_platform STRING, source_invoice_id STRING, doc_type STRING, status STRING, "
       "issue_date DATE, due_date DATE, paid_date DATE, subtotal DECIMAL(18,2), tax DECIMAL(18,2), total DECIMAL(18,2), "
       "amount_due DECIMAL(18,2), currency STRING, account_id STRING, sync_seq BIGINT, _ingested_at TIMESTAMP")


def _setup(spark):
    t = datetime(2026, 10, 1, 7)
    rows = [("C-1", "bookwise", "a", "invoice", "paid", date(2026, 8, 10), None, None, D(100), D(20), D(120), D(0), "GBP", "4100", 1, t),
            ("C-1", "bookwise", "b", "invoice", "paid", date(2026, 9, 10), None, None, D(50), D(10), D(60), D(0), "GBP", "4100", 2, t),
            ("C-2", "bookwise", "c", "invoice", "open", date(2026, 8, 10), None, None, D(70), D(14), D(84), D(84), "GBP", "4000", 3, t)]
    spark.createDataFrame(rows, INV).write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver", "invoice"))
    spark.createDataFrame([("C-1", "4100", "Services", "revenue", date(2026, 5, 1), date(2026, 9, 1), False, 1),
                           ("C-1", "4100", "Services", "other_income", date(2026, 9, 1), date(9999, 12, 31), True, 2),
                           ("C-2", "4000", "Sales", "revenue", date(2026, 5, 1), date(9999, 12, 31), True, 3)],
                          "company_id STRING, account_id STRING, account_name STRING, account_type STRING, valid_from DATE, "
                          "valid_to DATE, is_current BOOLEAN, account_sk BIGINT") \
        .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver", "account_mapping"))
    spark.createDataFrame([("lender", "C-1", "x", t, None), ("lender", "C-2", "x", t, t)],
                          "customer_id STRING, company_id STRING, purpose STRING, granted_at TIMESTAMP, revoked_at TIMESTAMP") \
        .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver", "company_entitlement"))
    spark.sql(f"DROP TABLE IF EXISTS {table('gold', 'fct_invoice')}")


def test_as_of_join_and_consent_scope_revenue(spark):
    _setup(spark)
    gold.build_fct_invoice(spark)
    gold.build_revenue(spark)
    got = {(r.company_id, str(r.month)): float(r.revenue) for r in spark.table(table("gold", "insights_revenue_monthly")).collect()}
    assert got == {("C-1", "2026-08-01"): 100.0}   # September is other income; C-2's consent is revoked


def test_rerunning_the_incremental_fact_changes_nothing(spark):
    _setup(spark)
    first = gold.build_fct_invoice(spark)
    assert gold.build_fct_invoice(spark) == first == 3
