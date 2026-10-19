"""Compile a certified metric to SQL, run it as one customer, and watch the refusals."""
from nexus import semantic

wh = semantic.warehouse()          # DuckDB locally; the compiled-SQL evaluator in the browser
sql = semantic.compile_sql("revenue", ["month"], "northbank", company_id="C-104")
print(sql, "\n")
for row in wh.run(sql):
    print(row)

for name, dims in [("dso_days", []), ("gross_margin", []), ("revenue", ["industry"])]:
    try:
        semantic.compile_sql(name, dims, "northbank")
    except semantic.Refused as e:
        print(f"\nrefused {name}{dims}: {e.reason} · {e.message}")
