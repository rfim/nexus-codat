// Orchestrator: the last Dagster run, its asset checks, the GX results and the on-call agent's incident.
(async () => {
  const $ = (id) => document.getElementById(id);
  const [run, site, inc] = await Promise.all([NX.get("assets/data/orchestration.json"), NX.site(), NX.get("assets/data/incident.json")]);
  const checks = run.checks, passed = checks.filter((c) => c.passed).length;
  const secs = Object.values(run.step_seconds).reduce((a, b) => a + b, 0);
  $("o-tiles").innerHTML = [
    [run.assets.length, "Dagster assets", `job ${run.job} · Dagster ${run.dagster}`],
    [`${passed}/${checks.length}`, "asset checks pass", "SQL contracts, GX suites and pipeline checks"],
    [site.gx.filter((g) => g.success).length + "/" + site.gx.length, "GX suites pass", `${site.gx.reduce((a, g) => a + g.evaluated, 0)} expectations evaluated`],
    [inc.model === "offline-rules" ? "offline" : "Claude", "wrote the incident", `${inc.transcript.filter((t) => t.kind === "tool").length} MCP tool calls in ${inc.seconds}s`],
  ].map(([n, l, s], i) => `<div class="card ${i % 2 ? "top-p" : "top-v"}"><div class="big ${i % 2 ? "p" : ""}">${n}</div><h3 style="margin:.4rem 0 .2rem">${l}</h3><p>${NX.esc(s)}</p></div>`).join("");
  $("o-sched").textContent = `schedule ${run.schedule.name}: ${run.schedule.cron} (${run.schedule.timezone}) · total ${secs.toFixed(0)}s`;

  // ---------- the asset graph ----------
  const order = ["landing_feeds", "bronze", "silver_tables", "gold_fact", "insights_as_issued", "late_corrections", "insights", "incident_report", "site_data"];
  const pos = {}, W = 122, gap = 9.5;
  order.forEach((k, i) => (pos[k] = { x: 14 + i * (W + gap), y: i % 2 ? 150 : 110 }));
  const byAsset = {};
  checks.forEach((c) => (byAsset[c.asset] ??= []).push(c));
  const kindColor = { spark: "#f0a23a", delta: "#7ce0bf", great_expectations: "#ff7aa8", mcp: "#8fc2ff", anthropic: "#d4a4ff", python: "#c4b5ff" };
  const node = (k) => {
    const n = run.assets.find((a) => a.key === k), p = pos[k], cs = byAsset[k] || [];
    const ok = cs.filter((c) => c.passed).length, bad = cs.length - ok;
    return `<g class="node off" id="a-${k}" transform="translate(${p.x},${p.y})"><rect width="${W}" height="78" rx="12"/>
      <text x="${W / 2}" y="22" text-anchor="middle" style="font-size:12.5px">${k}</text>
      <text class="sm" x="${W / 2}" y="40" text-anchor="middle">${(run.step_seconds[k] ?? 0).toFixed(1)}s · ${n.group}</text>
      ${n.kinds.slice(0, 3).map((kd, j) => `<circle cx="${W / 2 - 18 + j * 18}" cy="55" r="5" fill="${kindColor[kd] || "#888"}"><title>${kd}</title></circle>`).join("")}
      ${cs.length ? `<text x="${W / 2}" y="72" text-anchor="middle" style="font:700 10px var(--mono);fill:${bad ? "#ff8fb0" : "#7ce0bf"}">${ok}/${cs.length} checks</text>` : ""}</g>`;
  };
  const edges = run.assets.flatMap((a) => a.deps.map((d) => [d, a.key])).map(([a, b]) => {
    const p = pos[a], q = pos[b];
    return `<path class="wire" id="e-${b}" d="M${p.x + W} ${p.y + 39} C ${p.x + W + 6} ${p.y + 39}, ${q.x - 6} ${q.y + 39}, ${q.x} ${q.y + 39}"/>`;
  }).join("");
  const legend = Object.entries(kindColor).map(([k, c], i) => `<g transform="translate(${20 + i * 150},300)"><circle r="5" cx="6" cy="0" fill="${c}"/><text x="18" y="4" style="font:500 11px var(--font);fill:#a9a8d8">${k}</text></g>`).join("");
  $("dag").innerHTML = `<text x="14" y="40" style="font:700 11px var(--mono);fill:#8f92c4;letter-spacing:.14em">INGEST → CONFORM → PUBLISH → CHECK → OPERATE</text>` + edges + order.map(node).join("") + legend;

  const say = (k) => {
    const m = run.metadata[k] || {}, cs = byAsset[k] || [];
    const bits = Object.entries(m).filter(([, v]) => typeof v !== "object").slice(0, 4).map(([a, b]) => `${a}: <b>${NX.esc(b)}</b>`);
    const failed = cs.filter((c) => !c.passed).map((c) => c.check);
    return `<b>${k}</b> · ${(run.step_seconds[k] ?? 0).toFixed(1)}s${bits.length ? " · " + bits.join(" · ") : ""}` +
      (failed.length ? ` · <span style="color:#ff8fb0">✕ ${failed.join(", ")}</span>` : cs.length ? ` · <span style="color:#7ce0bf">✓ ${cs.length} checks</span>` : "");
  };
  let playing = false;
  $("o-play").addEventListener("click", async () => {
    if (playing) return; playing = true;
    order.forEach((k) => { document.getElementById("a-" + k).setAttribute("class", "node off"); const e = document.getElementById("e-" + k); if (e) e.setAttribute("class", "wire"); });
    const total = order.reduce((a, k) => a + (run.step_seconds[k] || 0), 0);
    for (const k of order) {
      const e = document.getElementById("e-" + k); if (e) e.setAttribute("class", "wire hot");
      document.getElementById("a-" + k).setAttribute("class", "node hot");
      $("o-cap").innerHTML = say(k);
      await NX.sleep(Math.max(700, ((run.step_seconds[k] || 0) / total) * 9000));
      document.getElementById("a-" + k).setAttribute("class", (byAsset[k] || []).some((c) => !c.passed) ? "node hot" : "node on");
      if (e) e.setAttribute("class", "wire on");
    }
    $("o-cap").innerHTML = `Run <code>${run.run_id.slice(0, 8)}</code> ${run.success ? "succeeded" : "failed"}: ${passed}/${checks.length} checks pass. The one failure is the planted bank break, and <b>incident_report</b> diagnosed it.`;
    playing = false;
  });
  new IntersectionObserver((es, ob) => { if (es[0].isIntersecting) { ob.disconnect(); setTimeout(() => $("o-play").click(), 500); } }, { threshold: .3 }).observe($("dag"));

  // ---------- checks ----------
  $("o-checks").innerHTML = NX.table(checks.map((c) => ({ asset: c.asset, check: c.check, result: c.passed ? "pass" : "fail",
    severity: c.severity, detail: Object.entries(c.metadata).map(([k, v]) => `${k}=${v}`).join(" · ") })), null,
    { result: (v) => `<span class="${v}">${v}</span>`, detail: (v) => NX.esc(v.length > 110 ? v.slice(0, 110) + "…" : v) });

  // ---------- GX ----------
  const gxs = await Promise.all(site.gx.map((g) => NX.get(`assets/data/gx/${g.product}.json`)));
  $("gx-list").innerHTML = gxs.map((g) => `<details ${g.product.includes("cash") ? "open" : ""}><summary><code>${g.suite}</code> ·
      <span class="${g.success ? "pass" : "fail"}">${g.passed}/${g.evaluated} expectations</span></summary>
      <ul class="tlist" style="columns:1">${g.expectations.map((e) => `<li class="${e.success ? "passed" : "failed"}"><span>${e.success ? "✓" : "✕"}</span>${e.type.replace("expect_", "")}
        <i>${NX.esc(Object.entries(e.kwargs).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ").slice(0, 90))}${e.unexpected_count ? ` · ${e.unexpected_count} unexpected` : ""}</i></li>`).join("")}</ul></details>`).join("");

  // ---------- the agent ----------
  $("agent-who").innerHTML = inc.model === "offline-rules"
    ? `<b>Written by offline rules</b> for this published run: no Anthropic credentials were available where it ran, so the agent made the same MCP calls in a fixed order and simple rules wrote the report. Set <code>ANTHROPIC_API_KEY</code> and <code>claude-opus-5-5</code> runs the investigation instead; the tools, server and report schema are the same.`
    : `<b>Written by ${NX.esc(inc.model)}</b> over MCP (${NX.esc(inc.mcp_server)}) as <code>${NX.esc(inc.caller)}</code>, in ${inc.seconds}s.`;
  $("agent-trace").innerHTML = inc.transcript.map((t, i) => t.kind === "tool"
    ? `<div class="msg req" style="background:#090a26;border-radius:10px;padding:.6rem .8rem;margin-bottom:.5rem;font:400 .76rem/1.5 var(--mono);color:#cfcef2;border-left:3px solid var(--violet2);overflow-wrap:anywhere">
        <span style="color:#8f92c4;font-size:.66rem;letter-spacing:.14em">CALL ${i + 1} · tools/call</span><br><b style="color:#fff">${NX.esc(t.tool)}</b>(${NX.esc(JSON.stringify(t.args))})
        <div style="color:#7ce0bf;margin-top:.3rem;white-space:pre-wrap;overflow-wrap:anywhere">${NX.esc(t.result.slice(0, 260))}${t.result.length > 260 ? "…" : ""}</div></div>`
    : `<div class="callout" style="background:#16184d;color:#d9d6ff;margin-bottom:.5rem">${NX.esc(t.text)}</div>`).join("");
  const r = inc.report;
  $("agent-report").innerHTML = `<div class="kicker" style="color:var(--pink)">severity ${r.severity} · confidence ${(r.confidence * 100).toFixed(0)}%</div>
    <h3 style="margin:.3rem 0 .6rem">${NX.esc(r.title)}</h3><p><b>Root cause.</b> ${NX.esc(r.root_cause)}</p>
    <p style="margin-top:.6rem"><b>Evidence</b></p><ul style="padding-left:1.1rem">${r.evidence.map((e) => `<li>${NX.esc(e.claim)} <code style="color:var(--muted)">${NX.esc(e.source_tool)}</code></li>`).join("")}</ul>
    <p style="margin-top:.6rem"><b>Hypotheses</b></p><ul style="padding-left:1.1rem">${r.hypotheses.map((h) => `<li><span class="${h.verdict === "supported" ? "pass" : h.verdict === "rejected" ? "fail" : ""}">${h.verdict}</span>: ${NX.esc(h.hypothesis)}. ${NX.esc(h.why)}</li>`).join("")}</ul>
    <p style="margin-top:.6rem"><b>Proposed fix, as a pull request.</b> ${NX.esc(r.proposed_fix.summary)}</p>
    <p style="font-size:.85rem;color:var(--muted)">Files: ${r.proposed_fix.files.map((f) => `<code>${NX.esc(f)}</code>`).join(", ")} · Test: ${NX.esc(r.proposed_fix.test)}</p>
    <p style="margin-top:.6rem"><b>Customer impact.</b> ${NX.esc(r.customer_impact)}</p>`;
})().catch((e) => console.error(e));
