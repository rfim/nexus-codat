from nexus.bronze import upsert_bronze
from nexus.spark import table

CFG = {"table": table("bronze", "t_idempotence"), "merge_keys": ["company_id", "invoice_id"], "ordering_key": "sync_seq"}


def test_replayed_page_is_a_no_op_and_newest_version_wins(spark):
    spark.sql(f"DROP TABLE IF EXISTS {CFG['table']}")
    page = spark.createDataFrame([("C-1", "A", 10, "open"), ("C-1", "B", 20, "open"), ("C-1", "A", 10, "open")],
                                 "company_id STRING, invoice_id STRING, sync_seq INT, status STRING")
    upsert_bronze(spark, page, CFG)
    upsert_bronze(spark, page, CFG)                      # the platform re-sends the same page
    assert spark.table(CFG["table"]).count() == 2

    later = spark.createDataFrame([("C-1", "A", 11, "void"), ("C-1", "B", 19, "draft")],
                                  "company_id STRING, invoice_id STRING, sync_seq INT, status STRING")
    upsert_bronze(spark, later, CFG)
    got = {r.invoice_id: r.status for r in spark.table(CFG["table"]).collect()}
    assert got == {"A": "void", "B": "open"}             # stale seq 19 never overwrites seq 20
