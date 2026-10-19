"""Data contracts: the YAML a product owner signs, compiled into checks, expectations and grants.

One file in, three artefacts out:
  1. checks       -> SQL run against the gold product on every load (results are kept)
  2. expectations -> a Spark Declarative Pipelines expectation set
  3. governance   -> Unity Catalog SQL: owner, tags, grants and the tenant row filter
"""
import re

import yaml

from nexus.paths import ROOT, table

CONTRACTS = ROOT / "contracts"
RUN_DATE = "DATE'2026-09-30'"


def load_products() -> list[dict]:
    out = []
    for p in sorted((CONTRACTS / "products").glob("*.yml")):
        c = yaml.safe_load(p.read_text())
        c["_path"] = str(p.relative_to(ROOT))
        out.append(c)
    return out


def load_sources() -> list[dict]:
    return yaml.safe_load((CONTRACTS / "sources.yml").read_text())


def _q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _refs(sql: str) -> str:
    """{silver.invoice} -> the physical table name for this environment."""
    return re.sub(r"\{(\w+)\.(\w+)\}", lambda m: table(m.group(1), m.group(2)), sql)


def _tests(col: dict):
    for test in col.get("tests", []):
        yield (test, None) if isinstance(test, str) else next(iter(test.items()))


def compile_checks(c: dict) -> list[dict]:
    """Each check is a SQL query that returns the failing rows. Zero rows = pass."""
    t = table("gold", c["product"])
    checks = []
    for col in c.get("columns", []):
        for name, arg in _tests(col):
            if name == "not_null":
                sql = f"SELECT * FROM {t} WHERE {col['name']} IS NULL"
            elif name == "accepted_values":
                sql = f"SELECT * FROM {t} WHERE {col['name']} NOT IN ({', '.join(_q(v) for v in arg)})"
            elif name == "range":
                cond = [f"{col['name']} < {arg['min']}"] if "min" in arg else []
                cond += [f"{col['name']} > {arg['max']}"] if "max" in arg else []
                sql = f"SELECT * FROM {t} WHERE {' OR '.join(cond)}"
            else:
                raise ValueError(f"unknown test {name} in {c['_path']}")
            checks.append({"check": f"{name}: {col['name']}", "kind": "column", "sql": sql})

    g = ", ".join(c["grain"])
    checks.append({"check": f"unique grain: {g}", "kind": "grain",
                   "sql": f"SELECT {g}, count(*) AS n FROM {t} GROUP BY {g} HAVING count(*) > 1"})

    f = c["freshness"]
    checks.append({"check": f"freshness: {f['column']} within {f['max_lag_days']} day(s) of the run",
                   "kind": "freshness",
                   "sql": f"SELECT max({f['column']}) AS latest FROM {t} "
                          f"HAVING max({f['column']}) < {RUN_DATE} - INTERVAL {f['max_lag_days']} DAYS"})

    checks.append({"check": "tenant: every row belongs to a customer with active consent", "kind": "tenant",
                   "sql": f"SELECT p.customer_id, p.company_id FROM {t} p LEFT JOIN "
                          f"{table('silver', 'company_entitlement')} e USING (customer_id, company_id) "
                          f"WHERE e.company_id IS NULL OR e.revoked_at IS NOT NULL"})

    if r := c.get("reconcile"):
        on = ", ".join(r["match_on"])
        checks.append({"check": f"reconcile {r['measure']} to source within {r['tolerance']}", "kind": "reconcile",
                       "sql": f"WITH p AS (SELECT customer_id, {on}, round(sum({r['measure']}), 2) AS published "
                              f"FROM {t} GROUP BY ALL), x AS ({_refs(r['against_sql']).strip()}) "
                              f"SELECT p.customer_id, {', '.join('p.' + k for k in r['match_on'])}, p.published, "
                              f"round(x.expected, 2) AS expected, round(p.published - x.expected, 2) AS difference "
                              f"FROM p JOIN x USING ({on}) WHERE abs(p.published - x.expected) > {r['tolerance']}"})
    return checks


def compile_expectations(c: dict) -> str:
    """The same rules as a Spark Declarative Pipelines expectation set."""
    rules = {}
    for col in c.get("columns", []):
        for name, arg in _tests(col):
            key = f"{col['name']}_{name}"
            if name == "not_null":
                rules[key] = f"{col['name']} IS NOT NULL"
            elif name == "accepted_values":
                rules[key] = f"{col['name']} IN ({', '.join(_q(v) for v in arg)})"
            elif name == "range":
                parts = ([f"{col['name']} >= {arg['min']}"] if "min" in arg else []) + \
                        ([f"{col['name']} <= {arg['max']}"] if "max" in arg else [])
                rules[key] = " AND ".join(parts)
    body = "\n".join(f'    "{k}": "{v}",' for k, v in rules.items())
    return (f"from pyspark import pipelines as dp\n\n"
            f"# generated from {c['_path']}: do not edit by hand\n"
            f"RULES = {{\n{body}\n}}\n\n"
            f"@dp.materialized_view(name=\"{c['product']}\", comment={c['definition'].strip()!r})\n"
            f"@dp.expect_all_or_fail(RULES)\n"
            f"def {c['product']}():\n"
            f"    return build_{c['product']}()\n")


def compile_governance(c: dict, catalog: str = "nexus") -> str:
    t = f"{catalog}.gold.{c['product']}"
    lines = [f"-- generated from {c['_path']}: do not edit by hand",
             f"ALTER TABLE {t} SET OWNER TO `{c['owner']}`;",
             f"COMMENT ON TABLE {t} IS {_q(c['definition'].strip())};",
             f"ALTER TABLE {t} SET TAGS ('team' = {_q(c['team'])}, 'grain' = {_q(', '.join(c['grain']))});"]
    lines += [f"GRANT SELECT ON TABLE {t} TO `{g}`;" for g in c["access"]["read"]]
    tenant = c["access"]["tenant_column"]
    lines.append(f"ALTER TABLE {t} SET ROW FILTER {catalog}.governance.tenant_filter ON ({tenant}, company_id);")
    return "\n".join(lines) + "\n"


def run_checks(spark, c: dict) -> list[dict]:
    results = []
    for chk in compile_checks(c):
        failing = spark.sql(chk["sql"])
        n, sample = failing.count(), [r.asDict() for r in failing.limit(3).collect()]
        results.append(chk | {"failing_rows": n, "status": "pass" if n == 0 else "fail", "sample": sample})
    return results
