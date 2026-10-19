"""The Spark session as a Dagster resource. On Databricks the active session is reused."""
import dagster as dg


class SparkResource(dg.ConfigurableResource):
    app_name: str = "nexus-dagster"

    def session(self):
        from nexus.spark import get_spark
        return get_spark(self.app_name)
