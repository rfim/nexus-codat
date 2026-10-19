import json, sys
R = "/home/user/nexus-codat/assets/data/"
d = json.load(open(R + "site.json")); e = d["evidence"]; r = d["run"]
rev = json.load(open(R + "products/insights_revenue_monthly.json"))
com = json.load(open(R + "products/insights_commerce_monthly.json"))
gbp = lambda v: ("−" if v < 0 else "") + "£{:,.0f}".format(abs(v))
gbp2 = lambda v: ("−" if v < 0 else "") + "£{:,.2f}".format(abs(v))
cash = next(c for c in d["contracts"] if c["product"] == "insights_cash_flow_monthly")
s = next(x for x in cash["results"] if x["status"] == "fail")["sample"][0]
aug1 = sum(x["revenue"] for x in rev if x["month"] == "2026-08-01")
delta = sum(x["delta"] for x in e["restatement"]); aug0 = aug1 - delta
ent = [x for x in e["entitlements"] if not x["revoked_at"]]
nb = sum(x["customer_id"] == "northbank" for x in ent); bp = sum(x["customer_id"] == "brightpay" for x in ent)
po = sum(x["payouts_in_bank_ratio"] * x["payouts"] for x in com) / sum(x["payouts"] for x in com)
v = [x["n"] for x in e["daily_volume_c107"]]; zs = []
for k in range(10, len(v)):
    w = v[max(0, k - 30):k]; mu = sum(w) / len(w); sd = (sum((b - mu) ** 2 for b in w) / len(w)) ** .5 or 1
    zs.append((v[k] - mu) / sd)
c2, c25, c3 = (sum(z > t for z in zs) for t in (2, 2.5, 3))
mx = max(c2, 1)
bars = "".join(f'<div>{n}<i style="height:{max(3, n / mx * 16)}mm{";background:var(--navy2)" if i == 3 else ""}"></i></div>'
               for i, n in enumerate((c2, c25, c3, 1)))
c103 = next(x["revenue"] for x in rev if x["company_id"] == "C-103" and x["month"] == "2026-08-01")
passed = sum(c["passed"] for c in d["contracts"]); total = sum(c["total"] for c in d["contracts"])
evals = sum(1 for l in open("/home/user/nexus-codat/evals/questions.yml") if l.startswith("- id:"))
tok = {"passed": passed, "total": total, "break_amt": gbp(s["difference"]), "quarantined": r["silver"]["invoice_quarantine"],
       "canonical": r["silver"]["invoice"] + r["silver"]["invoice_quarantine"], "late_total": r["feeds"]["late_total"], "evals": evals,
       "pub": gbp2(s["published"]), "exp": gbp2(s["expected"]), "w_pub": 96, "w_exp": round(96 * s["expected"] / s["published"], 1),
       "restated_rows": len(e["restatement"]), "restate_total": gbp(delta), "aug_v0": gbp(aug0), "aug_v1": gbp(aug1),
       "w_aug1": round(96 * aug1 / aug0, 1), "restate_pct": f"{delta / aug0 * 100:.1f}%".replace("-", "−"),
       "nb": nb, "bp": bp, "w_nb": 90, "w_bp": round(90 * bp / nb, 1), "po_ratio": f"{po * 100:.1f}%",
       "zbars": bars, "z2": c2, "c103_aug": gbp2(c103)}
html = open(sys.argv[1]).read()
for k, val in tok.items():
    html = html.replace("{{" + k + "}}", str(val))
assert "{{" not in html, html[html.index("{{"):html.index("{{") + 30]
open(sys.argv[2], "w").write(html)
print(json.dumps({k: v for k, v in tok.items() if k != "zbars"}))
