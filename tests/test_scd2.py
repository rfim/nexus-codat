from nexus.silver import build_account_mapping_scd2
from nexus.spark import table


def test_a_remap_closes_the_old_version_without_rewriting_it(spark):
    rows = [("C-103", "4100", "Services", "revenue", "2026-05-20T09:00:00Z"),
            ("C-103", "4100", "Services (grant-funded)", "other_income", "2026-09-01T08:00:00Z")]
    spark.createDataFrame(rows, "company_id STRING, account_id STRING, account_name STRING, account_type STRING, "
                                "updated_at STRING").write.format("delta").mode("overwrite").saveAsTable(
        table("bronze", "account"))
    build_account_mapping_scd2(spark)
    got = spark.sql(f"SELECT account_type, CAST(valid_from AS STRING) f, CAST(valid_to AS STRING) t, is_current "
                    f"FROM {table('silver', 'account_mapping')} ORDER BY valid_from").collect()
    assert [tuple(r) for r in got] == [("revenue", "2026-05-20", "2026-09-01", False),
                                       ("other_income", "2026-09-01", "9999-12-31", True)]
