"""The semantic layer as code: load the metric catalogue, compile a request to SQL, run it as the caller.

Compiles to plain SQL that runs on Databricks SQL and on DuckDB, so the MCP server, the tests and the
browser demo all execute the same statement against the same exported gold products.
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "semantic" / "metrics.yml"
PRODUCTS = ROOT / "assets" / "data" / "products"
PRINCIPALS = {  # identity -> customer. In production: the identity provider and the entitlement table
    "analyst@northbank.example": "northbank",
    "analyst@brightpay.example": "brightpay",
}


class Refused(Exception):
    """A request the semantic layer will not answer, with a machine-readable reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason, self.message = reason, message


def catalogue() -> dict[str, dict]:
    return {m["name"]: m for m in yaml.safe_load(CATALOGUE.read_text())["metrics"]}


def require_certified(name: str) -> dict:
    m = catalogue().get(name)
    if m is None:
        raise Refused("unknown_metric", f"'{name}' is not a metric in the catalogue.")
    if not m.get("certified"):
        raise Refused("not_certified", f"'{m['label']}' is not certified yet: {m['definition']}")
    return m


def customer_for(principal: str) -> str:
    try:
        return PRINCIPALS[principal]
    except KeyError:
        raise Refused("unknown_principal", f"{principal} is not entitled to any customer's data.") from None


def compile_sql(name: str, group_by: list[str], customer: str, company_id: str | None = None,
                months: tuple[str, str] | None = None) -> str:
    """One certified metric -> one SQL statement, always scoped to the caller's customer."""
    m = require_certified(name)
    group_by = list(dict.fromkeys(group_by))
    bad = [d for d in group_by if d not in m["dimensions"]]
    if bad:
        raise Refused("bad_dimension", f"{m['label']} can't be split by {', '.join(bad)}; "
                                       f"allowed: {', '.join(m['dimensions'])}.")
    for need in m.get("requires", []):
        if need not in group_by and not (need == "company_id" and company_id):
            if m["kind"] == "point_in_time":
                raise Refused("non_additive", f"{m['label']} is {m['kind'].replace('_', ' ')}: "
                                              f"ask for it by {' and '.join(m['requires'])}.")
            group_by.append(need)
    where = [f"customer_id = '{customer}'"]  # the tenant filter: never optional
    if company_id:
        where.append(f"company_id = '{company_id}'")
    if months:
        where.append(f"month BETWEEN DATE '{months[0]}-01' AND DATE '{months[1]}-01'")
    dims = ", ".join(group_by)
    select = f"{dims + ', ' if dims else ''}{m['expr']} AS {m['name']}"
    sql = f"SELECT {select}\nFROM gold.{m['product']}\nWHERE {' AND '.join(where)}"
    if dims:
        sql += f"\nGROUP BY {dims}\nORDER BY {dims}"
    return sql


class Warehouse:
    """DuckDB over the exported gold products: the same rows the site shows."""

    def __init__(self, products: Path = PRODUCTS):
        import duckdb
        self.con = duckdb.connect()
        self.con.execute("CREATE SCHEMA gold")
        for p in sorted(products.glob("*.json")):
            rows = json.loads(p.read_text())
            self.con.execute(f"CREATE TABLE gold.{p.stem} AS SELECT * FROM read_json_auto('{p}')") if rows else None
        for t in ("insights_revenue_monthly", "insights_cash_flow_monthly", "insights_dso_monthly",
              "insights_commerce_monthly"):
            self.con.execute(f"ALTER TABLE gold.{t} ALTER month TYPE DATE")

    def run(self, sql: str) -> list[dict]:
        cur = self.con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, (v.isoformat() if hasattr(v, "isoformat") else
                                (round(float(v), 4) if v is not None and not isinstance(v, (str, int)) else v)
                                for v in row))) for row in cur.fetchall()]
