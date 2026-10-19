"""Silver: one canonical invoice across platforms, the quality split, SCD2 account mappings, conformed banking."""
from functools import reduce

import yaml
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from nexus.spark import ROOT, table

from nexus.silver_columns import CANONICAL


def _write(df: DataFrame, layer: str, name: str) -> int:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table(layer, name))
    return df.count()


def canonical_invoices(spark: SparkSession, sources: list[dict]) -> DataFrame:
    """Each platform's bronze rendered through its contract's `canonical` mapping, then unioned."""
    parts = []
    for s in (s for s in sources if "canonical" in s):
        exprs = [F.expr(str(s["canonical"][c])).alias(c) for c in CANONICAL]
        parts.append(spark.table(table("bronze", s["target"]["table"])).select(
            F.lit(s["platform"]).alias("source_platform"), *exprs, "_ingested_at"))
    df = reduce(DataFrame.unionByName, parts)
    return (df.withColumn("subtotal", F.col("subtotal").cast("decimal(18,2)"))
              .withColumn("tax", F.col("tax").cast("decimal(18,2)"))
              .withColumn("total", (F.col("subtotal") + F.col("tax")).cast("decimal(18,2)"))
              .withColumn("amount_due", F.col("amount_due").cast("decimal(18,2)"))
              .withColumn("sync_seq", F.col("sync_seq").cast("long")))


def split_by_contract(spark: SparkSession, sources: list[dict]) -> tuple[int, int]:
    """Clean rows continue; failures are kept with the failing rules attached, where someone owns them."""
    rules = yaml.safe_load((ROOT / "contracts" / "quality.yml").read_text())["invoice_quality"]["rules"]
    df = canonical_invoices(spark, sources)
    failed = F.array_compact(F.array(*[F.when(~F.coalesce(F.expr(r), F.lit(False)), F.lit(n))
                                       for n, r in rules.items()]))
    tagged = df.withColumn("_failed_rules", failed)
    valid = tagged.filter(F.size("_failed_rules") == 0).drop("_failed_rules")
    quarantine = tagged.filter(F.size("_failed_rules") > 0).withColumn("_quarantined_at", F.current_timestamp())
    return _write(valid, "silver", "invoice"), _write(quarantine, "silver", "invoice_quarantine")


def build_account_mapping_scd2(spark: SparkSession) -> int:
    """Every version of each account, with validity windows: a remap in September can't rewrite August."""
    acc = spark.table(table("bronze", "account"))
    w = "PARTITION BY company_id, account_id ORDER BY updated_at"
    scd2 = acc.selectExpr(
        "company_id", "account_id", "account_name", "account_type",
        "to_date(updated_at) AS valid_from",
        f"coalesce(lead(to_date(updated_at)) OVER ({w}), DATE'9999-12-31') AS valid_to",
        f"lead(updated_at) OVER ({w}) IS NULL AS is_current",
        "xxhash64(company_id, account_id, updated_at) AS account_sk")
    return _write(scd2, "silver", "account_mapping")


def build_banking(spark: SparkSession) -> dict:
    tx = spark.table(table("bronze", "bank_transaction")).selectExpr(
        "company_id", "account_id", "txn_id", "to_date(booked_date) AS booked_date",
        "CAST(amount AS DECIMAL(18,2)) AS amount", "currency", "description", "category",
        "counterparty_iban", "sync_seq", "_ingested_at")
    # what the bank says the balance moved by: the reference the cash-flow contract reconciles to
    bal = spark.table(table("bronze", "bank_balance")).selectExpr(
        "company_id", "account_id", "CAST(opening_balance AS DECIMAL(18,2)) AS opening_balance",
        "CAST(closing_balance AS DECIMAL(18,2)) AS closing_balance",
        "CAST(closing_balance - opening_balance AS DECIMAL(18,2)) AS balance_movement")
    po = spark.table(table("bronze", "commerce_payout")).selectExpr(
        "merchant_id AS company_id", "payout_id", "to_date(sales_date) AS sales_date",
        "to_date(arrival_date) AS arrival_date", "CAST(gross_sales AS DECIMAL(18,2)) AS gross_sales",
        "CAST(refunds AS DECIMAL(18,2)) AS refunds", "CAST(fees AS DECIMAL(18,2)) AS fees",
        "CAST(payout_amount AS DECIMAL(18,2)) AS payout_amount", "currency")
    return {"commerce_payout": _write(po, "silver", "commerce_payout"),
            "bank_transaction": _write(tx, "silver", "bank_transaction"),
            "bank_balance": _write(bal, "silver", "bank_balance")}


def build_reference(spark: SparkSession) -> dict:
    co = spark.table(table("bronze", "company")).drop("_ingested_at", "_source_file")
    ent = spark.table(table("bronze", "company_entitlement")).selectExpr(
        "customer_id", "company_id", "purpose", "to_timestamp(granted_at) AS granted_at",
        "to_timestamp(revoked_at) AS revoked_at")
    return {"company": _write(co, "silver", "company"), "company_entitlement": _write(ent, "silver", "company_entitlement")}
