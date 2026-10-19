// How the data gets there: every panel is read from assets/data/site.json, written by the run.
NX.site().then((d) => {
  const $ = (id) => document.getElementById(id), r = d.run, e = d.evidence;
  const max = Math.max(...r.tasks.map((t) => t.duration_s));
  const CODE = { generate: "src/nexus/generate.py", ingest: "src/nexus/bronze.py", replay: "src/nexus/bronze.py", late: "src/nexus/bronze.py",
    silver: "src/nexus/silver.py", gold: "src/nexus/gold.py", rerun: "src/nexus/gold.py", restate: "src/nexus/pipeline.py",
    check_issued: "src/nexus/contracts.py", check: "src/nexus/contracts.py" };
  $("tasks").innerHTML = r.tasks.map((t) => `<div class="bar"><a href="#code" data-code="${CODE[t.key] || "src/nexus/pipeline.py"}" class="tasklink">${NX.esc(t.label)} <i>${(CODE[t.key] || "").split("/").pop()}</i></a>
    <span class="track" style="background:#1d1f57"><span class="fill" style="left:0;width:${Math.max(2, (t.duration_s / max) * 100)}%"></span></span>
    <span class="num" style="color:#a9a8d8">${t.duration_s}s</span></div>`).join("") +
    `<p style="margin-top:.8rem;color:#a9a8d8;font-size:.85rem">Total ${r.seconds}s. On Databricks each step is a task in one job (<code>databricks.yml</code>).</p>`;

  const feeds = Object.keys(r.bronze);
  $("bronze").innerHTML = NX.table(feeds.map((f) => ({ feed: f, landed: r.feeds[f] ?? "", "replayed page": r.feeds[f + "_replayed"] ?? "",
    "bronze rows": r.bronze[f], "after replaying every feed": r.bronze_after_replay[f],
    change: r.bronze_after_replay[f] - r.bronze[f] })), null, { change: (v) => `<span class="${v ? "fail" : "pass"}">${v}</span>` });
  const hist = (rows) => NX.table(rows, ["version", "operation", "rows_inserted", "rows_updated", "rows_out"]);
  $("hist-bronze").innerHTML = hist(d.history["bronze.ledgerone_invoice"]);
  $("hist-gold").innerHTML = hist(d.history["gold.insights_revenue_monthly"]);

  $("quarantine").innerHTML = NX.table(e.quarantine, ["source_platform", "source_invoice_id", "status", "currency", "issue_date", "due_date", "_failed_rules"],
    { _failed_rules: (v) => `<span class="fail">${v.join(", ")}</span>` });
  NX.get("assets/data/quality.json").then((q) => ($("quality").textContent = q)).catch(() => {
    $("quality").textContent = `invoice_quality:\n  on_failure: quarantine\n  rules:\n${Object.keys(r.silver.quarantine_reasons).map((k) => `    ${k}: ...`).join("\n")}`; });

  $("scd2").innerHTML = `<h3 style="margin-bottom:.6rem">silver.account_mapping · C-103 · 4100</h3>` +
    NX.table(e.scd2_c103, ["account_name", "account_type", "valid_from", "valid_to", "is_current"]);
  const top = Math.max(...e.c103_revenue.map((x) => x.revenue));
  $("c103").innerHTML = `<h3 style="margin-bottom:.6rem">C-103 revenue by month (gold)</h3><div class="bars">` + e.c103_revenue.map((x) =>
    `<div class="bar"><span>${NX.month(x.month)}</span><span class="track"><span class="fill" style="width:${(x.revenue / top) * 100}%"></span></span><span class="num">${NX.money(x.revenue)}</span></div>`).join("") +
    `</div><p style="font-size:.88rem;color:var(--muted);margin-top:.6rem">From September, invoices on account 4100 count as other income. June to August keep the mapping that applied when they were issued.</p>`;

  const tot = (k) => e.restatement.reduce((a, x) => a + (x[k] || 0), 0);
  $("restatement").innerHTML = `<div class="grid g3" style="margin-bottom:1rem">
      <div class="card top-v"><div class="big">${NX.int(r.feeds.late_total)}</div><p>late documents: backdated credit notes and voids</p></div>
      <div class="card top-p"><div class="big p">${e.restatement.length}</div><p>company-months restated across both customers</p></div>
      <div class="card top-v"><div class="big">${NX.money(tot("delta"))}</div><p>change in published revenue, v0 → v${r.current.revenue_version}</p></div></div>` +
    NX.table(e.restatement, ["customer_id", "company_id", "month", "issued", "now", "delta"],
      { issued: (v) => NX.money2(v), now: (v) => NX.money2(v), delta: (v) => `<span class="${v < 0 ? "delta-down" : "delta-up"}">${NX.money2(v)}</span>`, month: (v) => NX.month(v) });

  $("contracts").innerHTML = d.contracts.map((c) => `<details ${c.passed < c.total ? "open" : ""}><summary><code>${c.product}</code> ·
      <span class="${c.passed < c.total ? "fail" : "pass"}">${c.passed}/${c.total} pass</span> · owner ${NX.esc(c.owner)}</summary>
      ${NX.table(c.results.map((x) => ({ check: x.check, kind: x.kind, status: x.status, failing_rows: x.failing_rows })), null,
        { status: (v) => `<span class="${v}">${v}</span>` })}
      ${c.results.filter((x) => x.status === "fail").map((x) => `<p style="margin-top:.6rem"><b>Evidence:</b></p>${NX.table(x.sample)}`).join("")}
      <p style="margin-top:.6rem"><b>Compiled SQL</b></p><pre>${NX.esc(d.compiled[c.product].checks.map((k) => `-- ${k.check}\n${k.sql}`).join("\n\n"))}</pre>
      <p style="margin-top:.6rem"><b>Generated governance</b></p><pre>${NX.esc(d.compiled[c.product].governance)}</pre></details>`).join("");
}).catch((e) => console.error(e));
