"""Gold: the incremental invoice fact, then one certified Insights product per question.

Every product is keyed by (customer_id, company_id) through the active consent: a company is only
ever published to a customer it is shared with, and a revoked consent drops it from every product.
"""
from delta.tables import DeltaTable
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from nexus.spark import table

LOOKBACK = "INTERVAL 72 HOURS"  # p99.5 of observed late-arrival delay at Lifepal; measured per source here
RUN_DATE = "DATE'2026-09-30'"


def build_fct_invoice(spark: SparkSession) -> int:
    fact_name = table("gold", "fct_invoice")
    src = spark.table(table("silver", "invoice"))
    if spark.catalog.tableExists(fact_name):
        hwm = spark.table(fact_name).agg(F.max("_ingested_at")).first()[0]
        src = src.filter(F.col("_ingested_at") > F.lit(hwm) - F.expr(LOOKBACK))
    acc = spark.table(table("silver", "account_mapping"))
    # point in time: the account mapping in force on the issue date
    fact = (src.alias("i").join(acc.alias("a"),
                                (F.col("a.company_id") == F.col("i.company_id"))
                                & (F.col("a.account_id") == F.col("i.account_id"))
                                & (F.col("i.issue_date") >= F.col("a.valid_from"))
                                & (F.col("i.issue_date") < F.col("a.valid_to")), "left")
            .select(F.xxhash64("i.company_id", "i.source_platform", "i.source_invoice_id").alias("invoice_sk"),
                    "i.company_id", "i.source_platform", "i.source_invoice_id", "i.doc_type", "i.status",
                    "i.issue_date", "i.due_date", "i.paid_date", "i.subtotal", "i.tax", "i.total", "i.amount_due",
                    "i.currency", "i.account_id", "a.account_sk", "a.account_type", "i.sync_seq", "i._ingested_at"))
    if not spark.catalog.tableExists(fact_name):
        fact.write.format("delta").saveAsTable(fact_name)
    else:
        (DeltaTable.forName(spark, fact_name).alias("t")
         .merge(fact.alias("u"), "t.invoice_sk = u.invoice_sk")
         .whenMatchedUpdateAll(condition="u.sync_seq >= t.sync_seq")
         .whenNotMatchedInsertAll().execute())
    return spark.table(fact_name).count()


def _publish(spark: SparkSession, name: str, sql: str) -> None:
    df = spark.sql(sql)
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold", name))


def _shared() -> str:
    return (f"(SELECT customer_id, company_id FROM {table('silver', 'company_entitlement')} "
            f"WHERE revoked_at IS NULL) e")


def build_revenue(spark):
    _publish(spark, "insights_revenue_monthly", f"""
        SELECT e.customer_id, f.company_id, f.currency, trunc(f.issue_date, 'MM') AS month,
               CAST(sum(f.subtotal) AS DECIMAL(18,2)) AS revenue,
               count_if(f.doc_type = 'invoice') AS invoices,
               count_if(f.doc_type = 'credit_note') AS credit_notes
        FROM {table('gold', 'fct_invoice')} f JOIN {_shared()} USING (company_id)
        WHERE f.status IN ('open', 'paid') AND f.account_type = 'revenue'
        GROUP BY ALL""")


def build_cash_flow(spark):
    _publish(spark, "insights_cash_flow_monthly", f"""
        SELECT e.customer_id, t.company_id, t.currency, trunc(t.booked_date, 'MM') AS month,
               CAST(sum(CASE WHEN t.amount > 0 AND t.category NOT IN ('own_transfer', 'loan_drawdown')
                             THEN t.amount ELSE 0 END) AS DECIMAL(18,2)) AS operating_inflows,
               CAST(-sum(CASE WHEN t.amount < 0 AND t.category NOT IN ('own_transfer', 'loan_drawdown')
                              THEN t.amount ELSE 0 END) AS DECIMAL(18,2)) AS operating_outflows,
               CAST(sum(CASE WHEN t.category NOT IN ('own_transfer', 'loan_drawdown')
                             THEN t.amount ELSE 0 END) AS DECIMAL(18,2)) AS net_operating_cash_flow,
               CAST(sum(t.amount) AS DECIMAL(18,2)) AS net_movement_all
        FROM {table('silver', 'bank_transaction')} t JOIN {_shared()} USING (company_id)
        GROUP BY ALL""")


def build_dso(spark):
    _publish(spark, "insights_dso_monthly", f"""
        WITH months AS (SELECT explode(sequence(DATE'2026-06-01', DATE'2026-09-01', INTERVAL 1 MONTH)) AS month),
        inv AS (SELECT * FROM {table('gold', 'fct_invoice')}
                WHERE doc_type = 'invoice' AND status IN ('open', 'paid')),
        m AS (
          SELECT i.company_id, m.month,
                 sum(CASE WHEN i.issue_date <= last_day(m.month)
                           AND (i.paid_date IS NULL OR i.paid_date > last_day(m.month)) THEN i.total END) AS receivables,
                 sum(CASE WHEN i.issue_date > last_day(m.month) - INTERVAL 90 DAYS
                           AND i.issue_date <= last_day(m.month) THEN i.total END) AS billed_90d
          FROM inv i CROSS JOIN months m GROUP BY ALL)
        SELECT e.customer_id, m.company_id, m.month,
               CAST(coalesce(receivables, 0) AS DECIMAL(18,2)) AS receivables,
               CAST(coalesce(billed_90d, 0) AS DECIMAL(18,2)) AS billed_90d,
               CAST(round(coalesce(receivables, 0) / nullif(billed_90d, 0) * 90, 1) AS DECIMAL(6,1)) AS dso_days
        FROM m JOIN {_shared()} USING (company_id)""")


def build_completeness(spark):
    _publish(spark, "insights_data_completeness", f"""
        WITH q AS (SELECT company_id, count(*) AS quarantined FROM {table('silver', 'invoice_quarantine')} GROUP BY 1),
        i AS (SELECT company_id, count(*) AS invoices, max(issue_date) AS last_invoice FROM {table('gold', 'fct_invoice')} GROUP BY 1),
        b AS (SELECT company_id, count(DISTINCT booked_date) AS bank_days, max(booked_date) AS last_bank
              FROM {table('silver', 'bank_transaction')} GROUP BY 1)
        SELECT e.customer_id, c.company_id, c.platform AS source_platform, i.invoices,
               coalesce(q.quarantined, 0) AS quarantined, b.bank_days, i.last_invoice, b.last_bank,
               datediff({RUN_DATE}, least(i.last_invoice, b.last_bank)) AS days_since_data,
               CAST(round(least(1.0, b.bank_days / 70.0) * (1 - coalesce(q.quarantined, 0) / (i.invoices + coalesce(q.quarantined, 0))), 3)
                    AS DECIMAL(5,3)) AS completeness_score
        FROM {table('silver', 'company')} c JOIN {_shared()} USING (company_id)
        LEFT JOIN i USING (company_id) LEFT JOIN b USING (company_id) LEFT JOIN q USING (company_id)""")


def build_commerce(spark):
    # every payout should land in the bank within three days: the match rate is the commerce trust signal
    _publish(spark, "insights_commerce_monthly", f"""
        WITH matched AS (
          SELECT p.company_id, p.payout_id, max(b.txn_id IS NOT NULL) AS in_bank
          FROM {table('silver', 'commerce_payout')} p
          LEFT JOIN {table('silver', 'bank_transaction')} b
            ON b.company_id = p.company_id AND b.category = 'commerce_payout' AND b.amount = p.payout_amount
           AND b.booked_date BETWEEN p.arrival_date AND p.arrival_date + INTERVAL 3 DAYS
          GROUP BY ALL)
        SELECT e.customer_id, p.company_id, p.currency, trunc(p.sales_date, 'MM') AS month,
               CAST(sum(p.gross_sales) AS DECIMAL(18,2)) AS gross_sales,
               CAST(sum(p.refunds) AS DECIMAL(18,2)) AS refunds,
               CAST(sum(p.fees) AS DECIMAL(18,2)) AS fees,
               CAST(sum(p.gross_sales - p.refunds) AS DECIMAL(18,2)) AS net_sales,
               CAST(sum(p.payout_amount) AS DECIMAL(18,2)) AS payouts,
               CAST(round(avg(CASE WHEN m.in_bank THEN 1.0 ELSE 0.0 END), 3) AS DECIMAL(5,3)) AS payouts_in_bank_ratio
        FROM {table('silver', 'commerce_payout')} p JOIN matched m USING (company_id, payout_id)
        JOIN {_shared()} USING (company_id)
        GROUP BY ALL""")


PRODUCTS = [build_revenue, build_cash_flow, build_dso, build_completeness, build_commerce]
