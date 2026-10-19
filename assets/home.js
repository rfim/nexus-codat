// Home page: fill the run's real figures from assets/data/site.json.
NX.site().then((d) => {
  const r = d.run;
  const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  const replayDelta = sum(r.bronze_after_replay) - sum(r.bronze);
  const passed = d.contracts.reduce((a, c) => a + c.passed, 0), total = d.contracts.reduce((a, c) => a + c.total, 0);
  document.querySelectorAll("[data-k=replay_delta]").forEach((e) => (e.textContent = NX.int(replayDelta)));
  document.querySelectorAll("[data-k=checks]").forEach((e) => (e.textContent = `${passed}/${total}`));

  const restated = d.evidence.restatement;
  const tiles = [
    [NX.int(sum(r.bronze)), "records in bronze", `${NX.int(replayDelta)} changed when every feed was replayed`],
    [NX.int(r.silver.invoice_quarantine), "invoices quarantined", Object.entries(r.silver.quarantine_reasons).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ")],
    [`v${r.current.revenue_version}`, "revenue restated", `${restated.length} company-months changed after ${NX.int(r.feeds.late_total)} late corrections`],
    [`${passed}/${total}`, "contract checks pass", "the one failure is the planted bank break"],
  ];
  document.getElementById("run-tiles").innerHTML = tiles.map(([n, l, s], i) =>
    `<div class="card ${i % 2 ? "top-p" : "top-v"}"><div class="big ${i % 2 ? "p" : ""}">${n}</div><h3 style="margin:.4rem 0 .2rem">${l}</h3><p>${NX.esc(s)}</p></div>`).join("");

  document.getElementById("contract-list").innerHTML = d.contracts.map((c) => {
    const fails = c.results.filter((x) => x.status === "fail");
    return `<div style="display:flex;justify-content:space-between;gap:1rem;border-bottom:1px solid var(--line);padding:.45rem 0">
      <code>${c.product}</code><span class="${fails.length ? "fail" : "pass"}">${c.passed}/${c.total}</span></div>` +
      fails.map((f) => `<p style="font-size:.85rem;color:var(--red);margin:.3rem 0 .5rem">✗ ${NX.esc(f.check)}: ${f.failing_rows} rows,
        e.g. ${NX.esc(f.sample[0].company_id)} off by ${NX.money2(f.sample[0].difference)}</p>`).join("");
  }).join("");

  const ent = d.evidence.entitlements;
  const lessons = [
    `<b>Replayed sync pages:</b> 60 records re-sent per system, ${NX.int(replayDelta)} rows changed.`,
    `<b>Three schemas, one invoice:</b> ${NX.int(r.silver.invoice)} canonical invoices from LedgerOne, BookWise and OrbitERP.`,
    `<b>Malformed rows:</b> ${r.silver.invoice_quarantine} quarantined with the rule attached, none reached gold.`,
    `<b>Chart-of-accounts remap:</b> C-103's account 4100 became other income from 1 Sep; August kept its revenue (SCD2).`,
    `<b>Backdated credit notes:</b> August revenue restated as Delta v1; v0 still shows what was issued.`,
    `<b>Revoked consent:</b> ${ent.filter((e) => e.revoked_at).map((e) => `${e.company_id} for ${e.customer_id}`).join(", ")}: gone from every product and tool.`,
    `<b>A duplicate the key can't catch:</b> one bank payment re-sent under a new id. The cash-flow reconciliation caught it.`,
  ];
  document.getElementById("lessons").innerHTML = lessons.map((l) => `<li>${l}</li>`).join("");

  const ex = d.evidence.canonical_examples;
  const names = { ledgerone: "LedgerOne · accounting", bookwise: "BookWise · accounting", orbiterp: "OrbitERP · ERP" };
  const pick = (o, ks) => Object.fromEntries(ks.filter((k) => k in o).map((k) => [k, o[k]]));
  const rawKeys = { ledgerone: ["InvoiceID", "Type", "Status", "Date", "SubTotal", "CurrencyCode", "UpdatedDateUTC"],
                    bookwise: ["id", "doc", "state", "txn_date", "net", "currency_ref", "last_updated"],
                    orbiterp: ["subsidiary", "ledger", "series", "doc_number", "status_code", "created", "lines_total"] };
  document.getElementById("canonical").innerHTML = Object.entries(ex).map(([p, v]) => `
    <div class="card"><div class="kicker" style="color:var(--violet2)">${names[p]}</div>
      <pre style="margin:.5rem 0;font-size:.72rem">${NX.esc(JSON.stringify(pick(v.raw, rawKeys[p]), null, 1))}</pre>
      <div class="kicker" style="color:var(--pink)">→ canonical</div>
      <pre style="margin-top:.5rem;font-size:.72rem">${NX.esc(JSON.stringify(pick(v.canonical, ["source_invoice_id", "doc_type", "status", "issue_date", "subtotal", "currency"]), null, 1))}</pre></div>`).join("");
}).catch((e) => console.error(e));
