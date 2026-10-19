"""Generate the synthetic feeds and look at the problems they carry. Runs in the browser or locally."""
import json

from nexus import generate as g

counts = g.generate()
print("records landed per feed:")
for k, v in counts.items():
    if isinstance(v, int):
        print(f"  {k:<30} {v:>6}")

print("\nthe same invoice, as each system sends it:")
for p in g.PLATFORMS:
    row = json.loads((g.LANDING / f"{p}_invoices" / "part-0.json").read_text().splitlines()[0])
    print(f"  {p:<10}", {k: row[k] for k in list(row)[:6]})

print("\nthe planted break:", counts["planted_break"])
