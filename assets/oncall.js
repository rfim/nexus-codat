// On call: the planted bank break, investigated with read-only tools. Evidence comes from the run.
NX.site().then((d) => {
  const $ = (id) => document.getElementById(id), e = d.evidence;
  const cash = d.contracts.find((c) => c.product === "insights_cash_flow_monthly");
  const fail = cash.results.find((x) => x.status === "fail");
  const s = fail.sample[0], bal = e.c107_balance[0], dup = e.break_dupes[0] || {};
  const lines = e.break_c107;

  const steps = [
    ["07:02", "The contract check fails", `<p><code>insights_cash_flow_monthly</code>: <span class="fail">✗ ${NX.esc(fail.check)}</span>, ${fail.failing_rows} rows (C-107, for both customers it's shared with).</p>
      ${NX.table(fail.sample.map((x) => ({ customer: x.customer_id, company: x.company_id, published: NX.money2(x.published), "bank says": NX.money2(x.expected), difference: NX.money2(x.difference) })))}
      <p style="margin-top:.5rem">The pager fires on reconciliation breaches, not on volume. The insight isn't withdrawn; it carries the caveat until the source is fixed.</p>`, "At Lifepal, reconciliations against insurers' commission statements paged us; volume alone never did.", "Page on bank reconciliation per company. Keep the insight live, with a caveat, while the source is fixed."],
    ["07:03", "The agent gathers context, read-only", `<div class="trace">get_contract("insights_cash_flow_monthly")    → reconcile net_movement_all to silver.bank_balance, tolerance 0.01
get_lineage("net_operating_cash_flow")        → ${NX.esc(["silver.bank_transaction", "bronze.bank_transaction", "silver.bank_balance"].join(" → "))}
get_check_history("cash_flow", days=7)        → first failure on this run; all other companies pass
recent_changes(paths=["contracts/", "src/"]) → no code change touches banking</div>`, "On-call started from the contract and lineage, not from memory. Median time to trace a reported discrepancy to its source fell from hours to under five minutes.", "Give the agent exactly the read-only view the engineer starts from: contract, failing rows, lineage, recent changes."],
    ["07:05", "Evidence 1: only one company, by exactly one amount", `<p>Every bank line for C-107 should explain the reported balance movement:</p>
      <div class="trace">Σ lines (${NX.money2(s.published)}) − Δ balance (${NX.money2(bal.balance_movement)}) = ${NX.money2(s.difference)}</div>
      <p>${NX.money2(s.difference)} is a round, single-payment-sized number. Every other company reconciles to the penny, so it isn't the method.</p>`, "A difference that was one round amount, at one partner, almost always meant a duplicate, not a bug in shared logic.", "Check “one company, one amount” before touching shared code: it narrows the search in seconds."],
    ["07:06", "Evidence 2: the same payment, twice", `<p>Lines for C-107 with the same date and amount:</p>${NX.table(lines.map((x) => ({ txn_id: x.txn_id, booked_date: x.booked_date, amount: NX.money2(x.amount), description: x.description, sync_seq: x.sync_seq })))}
      <p style="margin-top:.5rem">Same date, amount and description; a different id and a sync sequence 10,000 higher. The MERGE key is <code>(company_id, txn_id)</code>, so a re-sent line under a new id is, correctly, a new row. The key can't catch it; the reconciliation did.</p>`, "Kafka and Debezium replays sent the same change twice; the ordered MERGE absorbed those. A record re-sent under a new id needed a content rule.", "Bank feeds can re-send a line under a new id. Deduplicate on content as well as the key, and quarantine rather than delete."],
    ["07:07", "Ranked hypotheses", `<ol style="padding-left:1.2rem"><li><b>The bank feed re-sent one payment under a new id.</b> Supported by evidence 2. <span class="pass">likely</span></li>
      <li>The reported balance is stale. Rejected: it matches every other line exactly. <span class="fail">no</span></li>
      <li>Currency or rounding. Rejected: GBP account, a whole-pound difference. <span class="fail">no</span></li></ol>`, "Hypotheses went into the incident note with the evidence for and against each, so the review checked reasoning.", "Have the agent rank hypotheses with evidence queries attached, so a reviewer checks the reasoning, not a guess."],
    ["07:09", "A fix, proposed as a pull request", `<div class="diff"><span>contracts/quality.yml</span>
<span class="add">+bank_quality:</span>
<span class="add">+  on_failure: quarantine</span>
<span class="add">+  rules:</span>
<span class="add">+    # a re-sent line: same account, date, amount and description as an earlier sync</span>
<span class="add">+    not_resent: "NOT exists_earlier(company_id, account_id, booked_date, amount, description)"</span>

<span>tests/test_bank_resend.py</span>
<span class="add">+def test_a_line_resent_under_a_new_id_is_quarantined(spark): ...</span></div>
      <p style="margin-top:.5rem">Plus a note to the source owner (banking-data@) with the two ids, and a re-run of the affected interval once merged. Quarantine, not delete: a genuine second payment of the same amount must stay reviewable.</p>`, "Fixes went through the same CI gate as any change, with a test that reproduced the incident first.", "The agent's only write is a pull request with a failing-then-passing test. It never changes data."],
    ["07:14", "A human approves", `<p>The on-call engineer checks the evidence queries, asks for one change (match within one day, not the same day only), and merges. The re-run is the runbook's one line: <code>re-run the interval</code>, safe because every load is a MERGE.</p>
      <div class="callout" style="margin-top:.5rem">The check is still red in this published run on purpose: the fix is shown as a proposal, so the evidence on this site stays exactly what the pipeline produced.</div>`, "A blameless write-up the same week, published where the business could read it.", "Track time to a drafted fix, how often the top hypothesis was right, and how many PRs merged unchanged."],
  ];
  let shown = -1, view = "codat";
  const render = () => ($("tl").innerHTML = steps.map(([t, h, body, lp, cx], i) => `<div class="tl ${shown >= i ? "on" : ""}" id="tl${i}"><div class="t">${t}</div>
    <h3 style="margin:.2rem 0 .4rem">${h}</h3>${view === "codat" ? body : `<div class="lesson ${view}"><b>${view === "lifepal" ? "In Lifepal" : "Lesson for Codat · hypothetical"}</b><p>${NX.esc(view === "lifepal" ? lp : cx)}</p></div>`}</div>`).join(""));
  render();
  document.querySelectorAll("#views [role=tab]").forEach((b) => b.addEventListener("click", () => {
    view = b.dataset.view; document.querySelectorAll("#views [role=tab]").forEach((x) => x.setAttribute("aria-selected", x === b)); render(); }));
  let i = 0, timer;
  const show = (n) => { shown = n; for (let k = 0; k <= n; k++) $("tl" + k).classList.add("on"); $("ttd").textContent = n >= 5 ? "7 minutes" : "–"; };
  $("go").addEventListener("click", () => { clearInterval(timer); i = 0; shown = -1; document.querySelectorAll(".tl").forEach((x) => x.classList.remove("on"));
    show(0); timer = setInterval(() => { i++; show(i); $("tl" + i)?.scrollIntoView({ behavior: "smooth", block: "center" }); if (i >= steps.length - 1) clearInterval(timer); }, 2200); });
  $("all").addEventListener("click", () => { clearInterval(timer); show(steps.length - 1); });

  // z-scores of daily line counts against the trailing 30 days
  const v = e.daily_volume_c107.map((x) => x.n), dates = e.daily_volume_c107.map((x) => x.booked_date);
  const z = v.map((n, k) => { if (k < 10) return null; const w = v.slice(Math.max(0, k - 30), k), mu = w.reduce((a, b) => a + b, 0) / w.length;
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - mu) ** 2, 0) / w.length) || 1; return (n - mu) / sd; });
  const X = (k) => 30 + (k / (v.length - 1)) * 360, Y = (zz) => 85 - Math.max(-3, Math.min(4.5, zz)) * 17;
  const over = z.filter((x) => x != null && x > 2).length, planted = dates.indexOf("2026-08-14");
  $("zplot").innerHTML = `<line x1="30" x2="390" y1="${Y(2)}" y2="${Y(2)}" stroke="#e8457f" stroke-dasharray="4 4"/><text x="2" y="${Y(2) + 3}" font-size="9" fill="#e8457f">2σ</text>
    <line x1="30" x2="390" y1="${Y(3)}" y2="${Y(3)}" stroke="#5b3df5" stroke-dasharray="4 4"/><text x="2" y="${Y(3) + 3}" font-size="9" fill="#5b3df5">3σ</text>
    <line x1="30" x2="390" y1="${Y(0)}" y2="${Y(0)}" stroke="#dedcef"/>` +
    z.map((zz, k) => zz == null ? "" : `<circle cx="${X(k)}" cy="${Y(zz)}" r="${k === planted ? 5 : 2.4}" fill="${k === planted ? "#ff4f8b" : zz > 2 ? "#8a73ff" : "#b9b7d8"}"/>`).join("") +
    (planted >= 0 ? `<text x="${X(planted) + 7}" y="${Y(z[planted] ?? 0) - 6}" font-size="9" fill="#ff4f8b">the re-sent line</text>` : "");
  const over3 = z.filter((x, k) => x != null && x > 3 && k !== planted).length, zp = planted >= 0 ? z[planted] : null;
  $("zcap").innerHTML = `The day of the re-sent payment scored z = ${zp == null ? "–" : zp.toFixed(1)}. But ${over} day(s) sat above 2σ
    and ${over3} other day(s) above 3σ with nothing wrong, and a spike can't say which line, which company's books or why.
    The reconciliation named the company, the amount and the cause, so pages come from reconciliations and SLOs, and volume goes to a digest.`;
}).catch((err) => console.error(err));
