"""`dagster dev -m nexus.orchestration.definitions` opens the asset graph, checks and schedule in the UI."""
import dagster as dg

from nexus.orchestration import assets
from nexus.orchestration.resources import SparkResource

ALL = dg.load_assets_from_modules([assets])
nexus_job = dg.define_asset_job("nexus_insights", selection=dg.AssetSelection.all(),
                                description="Land → conform → publish → check (SQL + GX) → diagnose → export")
daily = dg.ScheduleDefinition(job=nexus_job, cron_schedule="0 6 * * *", execution_timezone="Europe/London",
                              name="nexus_daily_0600")


@dg.asset_check(asset=assets.insights, description="Freshness: the Insights products were refreshed in the last 26 hours.")
def insights_are_fresh(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    rec = context.instance.get_latest_materialization_event(assets.insights.key)
    age_h = None if rec is None else (__import__("time").time() - rec.timestamp) / 3600
    return dg.AssetCheckResult(passed=age_h is not None and age_h < 26, metadata={"age_hours": round(age_h or -1, 2)})


defs = dg.Definitions(assets=ALL, asset_checks=[insights_are_fresh], jobs=[nexus_job], schedules=[daily],
                      resources={"spark": SparkResource()})
