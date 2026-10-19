// Enable MCP: a step-by-step animation of the real protocol exchange, then a chat on the same tools.
(async () => {
  await SEM.load();
  const $ = (id) => document.getElementById(id);
  const svg = $("stage").querySelector("svg");
  const SCENARIOS = [
    { q: "What was revenue for C-104 in August 2026?", label: "Revenue for C-104, August" },
    { q: "Show net operating cash flow by month for C-107", label: "Cash flow trend, C-107" },
    { q: "What was revenue for C-101 in August?", label: "Another customer's company (C-101)" },
    { q: "What's the gross margin for C-104?", label: "An uncertified metric (refused)" },
    { q: "List the counterparty bank details for C-104", label: "Personal data (refused)" },
  ];
  $("scenario").innerHTML = SCENARIOS.map((s, i) => `<option value="${i}">${NX.esc(s.label)}</option>`).join("");

  // ---------- answer text, shared with the chat ----------
  const fmtVal = (m, v, cur) => v == null ? "no data" : m.unit === "currency" ? NX.money2(v, cur || "GBP")
    : m.unit === "ratio" ? NX.pct(v) : m.unit === "days" ? `${v} days` : m.unit === "score" ? v.toFixed(3) : v;
  function answerText(p, res) {
    if (res.refused) return { no: true, text: res.message };
    const m = SEM.catalogue[p.args.name];
    if (p.tool === "describe_metric") return { text: `<b>${m.label}:</b> ${NX.esc(res.definition)} ${res.caveats?.length ? `<br><i>Caveat:</i> ${NX.esc(res.caveats[0])}` : ""}` };
    if (p.tool === "get_lineage") return { text: `<b>${m.label}</b> comes from <code>${res.product}</code> (Delta v${res.version}), built from ${res.upstream.map((u) => `<code>${u}</code>`).join(", ")}. Its contract runs ${res.checks_total} checks; ${res.checks_passed} pass now.` };
    const rows = res.rows, scope = `${p.args.company_id ? p.args.company_id + " " : ""}${p.args.month_from ? "in " + NX.month(p.args.month_from + "-01") : ""}`.trim();
    if (!rows.length || rows.every((r) => r[m.name] == null))
      return { text: `I found no ${m.label.toLowerCase()} you're entitled to see${scope ? " for " + scope : ""}. As <b>${res.customer}</b>, you can only query companies that have shared their data with you.` };
    if (rows.length === 1) return { text: `<b>${m.label}${scope ? " for " + scope : ""}:</b> ${fmtVal(m, rows[0][m.name], rows[0].currency)}` };
    return { text: `<b>${m.label}${scope ? " for " + scope : ""}:</b><br>` + rows.map((r) =>
      `${[r.company_id, r.month && NX.month(r.month)].filter(Boolean).join(" · ")}: <b>${fmtVal(m, r[m.name], r.currency)}</b>`).join("<br>") };
  }

  // ---------- stage primitives ----------
  const node = (id) => $(id);
  const setNode = (id, cls) => { const n = node(id); n.classList.remove("on", "hot", "off"); if (cls) n.classList.add(cls); };
  const setWire = (id, cls) => { const w = $(id); w.classList.remove("on", "hot"); if (cls) w.classList.add(cls); };
  const packet = $("packet");
  let speed = 1, instant = false;
  function fly(wireId, { reverse = false, color = "pk", ms = 900 } = {}) {
    const path = $(wireId), L = path.getTotalLength();
    packet.setAttribute("fill", `url(#${color})`);
    setWire(wireId, color === "pk" ? "hot" : "on");
    if (instant) { packet.setAttribute("cx", -50); return Promise.resolve(); }
    return new Promise((res) => {
      const t0 = performance.now(), dur = ms * speed;
      const tick = (t) => {
        const k = Math.min(1, (t - t0) / dur), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        const pt = path.getPointAtLength((reverse ? 1 - e : e) * L);
        packet.setAttribute("cx", pt.x); packet.setAttribute("cy", pt.y);
        if (k < 1) requestAnimationFrame(tick); else { packet.setAttribute("cx", -50); res(); }
      };
      requestAnimationFrame(tick);
    });
  }
  const wait = (ms) => instant ? Promise.resolve() : NX.sleep(ms * speed);
  const log = (dir, obj, cls = "req") => {
    const div = document.createElement("div");
    div.className = `msg ${cls}`;
    div.innerHTML = `<span class="dir">${dir}</span>${NX.esc(typeof obj === "string" ? obj : JSON.stringify(obj, null, 1))}`;
    $("wirelog").appendChild(div); $("wirelog").scrollTop = 1e6;
    return div;
  };
  async function typeInto(div, text) {
    if (instant) { div.lastChild.textContent = text; return; }
    const body = div.lastChild; body.textContent = "";
    for (let i = 0; i < text.length; i += 3) { body.textContent = text.slice(0, i + 3); $("wirelog").scrollTop = 1e6; await NX.sleep(12 * speed); }
  }
  const caption = (html) => { lastCaption.html = html; if (view === "codat") $("caption").innerHTML = html; };
  function drawTools(show) {
    const g = $("tools"); g.innerHTML = "";
    if (!show) return;
    ["list_metrics", "describe_metric", "get_lineage", "query_metric"].forEach((t, i) => {
      const y = 68 + i * 19;
      g.insertAdjacentHTML("beforeend", `<g class="tool-pill" id="tool-${t}" style="opacity:0;transform:translateX(-8px)">
        <rect x="18" y="${y}" width="184" height="16" rx="8" fill="#241f73" stroke="#5b3df5"/>
        <text x="110" y="${y + 11.5}" text-anchor="middle" style="font:500 10.5px var(--mono);fill:#e1defd">${t}</text></g>`);
      setTimeout(() => { const el = $(`tool-${t}`); if (el) { el.style.opacity = 1; el.style.transform = "none"; } }, instant ? 0 : (i + 1) * 180 * speed);
    });
  }
  const hiTool = (t) => { document.querySelectorAll(".tool-pill rect").forEach((r) => r.setAttribute("fill", "#241f73"));
    const el = document.querySelector(`#tool-${t} rect`); if (el) el.setAttribute("fill", "#e8457f"); };

  // ---------- the script ----------
  let steps = [], idx = -1, playing = false, run = 0, view = "codat";
  const VIEW = { lifepal: ["In Lifepal", "lp"], lesson: ["Lesson for Codat · hypothetical", "cx"] };
  const lastCaption = { html: "" };
  const showCaption = () => {
    const st = steps[idx];
    if (view === "codat" || !st) { $("caption").innerHTML = lastCaption.html; return; }
    $("caption").innerHTML = `<b>${VIEW[view][0]}:</b> ${NX.esc(st[VIEW[view][1]])}`;
  };
  function build() {
    const who = $("who").value, sc = SCENARIOS[+$("scenario").value];
    const customer = SEM.PRINCIPALS[who];
    const out = SEM.ask(sc.q, who), p = out.plan, res = out.result;
    const call = p.tool ? { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: p.tool, arguments: p.args } } : null;
    const s = [];
    s.push({ lp: "At Lifepal our MCP server ran beside Databricks and Airflow. Agents reached data only through it, by config, never with database credentials.", cx: "Ship one server with the platform, not one per team: one registration, one audit log of every tool call.", t: "Register the server", d: "One command adds nexus-insights to the agent's MCP config.", go: async () => {
      setNode("n-server", "on");
      log("agent config", `claude mcp add nexus-insights \\\n  --env NEXUS_CALLER=${who} \\\n  -- python -m nexus.mcp_server`, "res");
      caption(`The server is registered. It runs as a separate process and the agent can only reach data <b>through its tools</b>.`);
      $("agent-state").textContent = "configured"; setNode("n-agent", ""); } });
    s.push({ lp: "The server's instructions carried the house rules: certified models only, always cite, never give advice to a policyholder.", cx: "Put Codat's rules in the instructions too: certified Insights only, cite the metric version, never give lending advice.", t: "initialize", d: "Client and server agree a protocol version and capabilities.", go: async () => {
      log("client → server", { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "ai-agent", version: "1.0" } } });
      await fly("w-as", { color: "pv" });
      log("server → client", { jsonrpc: "2.0", id: 1, result: { protocolVersion: "2025-06-18", capabilities: { tools: { listChanged: false } }, serverInfo: { name: "nexus-insights" },
        instructions: "Answer questions about SMB financial Insights using certified metrics only. Cite the metric, its version and freshness; never give financial advice." } }, "res");
      await fly("w-as", { reverse: true, color: "pv" });
      $("agent-state").textContent = "connected"; setNode("n-agent", "on");
      caption(`Handshake done. The server's <b>instructions</b> travel with it: certified metrics only, always cite, never give advice.`); } });
    s.push({ lp: "Agents discovered certified dbt models and read their lineage. No tool reached raw or silver tables.", cx: "Start with a few read-only tools. Add one only when an eval shows a real question the existing ones can't answer.", t: "tools/list", d: "The agent discovers four read-only tools and their schemas.", go: async () => {
      log("client → server", { jsonrpc: "2.0", method: "notifications/initialized" });
      log("client → server", { jsonrpc: "2.0", id: 2, method: "tools/list" });
      await fly("w-as", { color: "pv" });
      log("server → client", { jsonrpc: "2.0", id: 2, result: { tools: [
        { name: "list_metrics", description: "Certified metrics an agent may quote, with owner, grain and freshness." },
        { name: "describe_metric", description: "Definition, allowed dimensions and known caveats of one certified metric." },
        { name: "get_lineage", description: "Upstream sources, the contract checks that guard the metric, and their latest results." },
        { name: "query_metric", description: "Compile a certified metric through the semantic layer and run it AS THE CALLER, with a citation.",
          inputSchema: { properties: { name: {}, group_by: {}, company_id: {}, month_from: {}, month_to: {} }, required: ["name"] } } ] } }, "res");
      await fly("w-as", { reverse: true, color: "pv" });
      drawTools(true);
      caption(`MCP is enabled. Four tools, all <b>read-only</b>. There is no tool for raw tables, personal data or writes, so an agent can't ask for them.`); } });
    s.push({ lp: "Questions came from Finance, Marketing and Product, and through the RAG copilot, which served 1,000+ outcomes a day.", cx: "Expect lenders' analysts, platform teams and internal agents. Log every question; the misses become new eval cases.", t: "The analyst asks", d: sc.q, go: async () => {
      setNode("n-user", "on");
      log(`analyst (${customer})`, `“${sc.q}”`, "res");
      await fly("w-ua", { color: "pk" });
      caption(`<b>${customer === "northbank" ? "Northbank" : "Brightpay"}</b> asks: “${NX.esc(sc.q)}”`); } });
    if (!p.tool) {
      s.push({ lp: "No tool exposed personal data, so the copilot could only refuse, and said why.", cx: "Keep personal and bank details out of tools entirely. A clear refusal is a feature, and it belongs in the eval set.", t: "No tool can answer", d: "The agent refuses before calling anything.", go: async () => {
        setNode("n-agent", "hot");
        log("agent", `refused: ${res.reason}\n${res.message}`, "err");
        caption(`<b>Refused (${res.reason.replace("_", " ")}).</b> ${NX.esc(res.message)}`); } });
    } else {
      s.push({ lp: "The caller's identity travelled with every call; there was no shared, broadly privileged service account.", cx: "Over HTTP, take the customer from the token, never from a tool argument the agent could change.", t: `tools/call · ${p.tool}`, d: JSON.stringify(p.args), go: async () => {
        hiTool(p.tool); log("client → server", call); await fly("w-as", { color: "pk" });
        setNode("n-server", "hot");
        caption(`The agent picks <code>${p.tool}</code> with <code>${NX.esc(JSON.stringify(p.args))}</code>. The server knows who is asking: <b>${who}</b>.`); } });
      s.push({ lp: "One definition per metric in the dbt semantic layer over Kimball stars. Agreeing “sale” took four workshops; the code took an afternoon.", cx: "Agree each Insights definition with its product owner before an agent can quote it. Uncertified metrics stay refused.", t: "Semantic layer compiles", d: "Metric → one SQL statement from metrics.yml.", go: async () => {
        await fly("w-ss", { color: "pk" }); setNode("n-sem", "hot");
        if (res.refused) {
          $("refuse-x").setAttribute("y", 150); $("refuse-x").style.transition = "opacity .3s"; $("refuse-x").setAttribute("opacity", 1);
          log("semantic layer", `Refused(${res.reason}): ${res.message}`, "err");
          caption(`<b>Refused by the semantic layer.</b> ${NX.esc(res.message)}`);
          return;
        }
        if (p.tool === "query_metric") { const div = log("semantic layer → SQL", ""); await typeInto(div, res.sql); }
        else log("semantic layer", p.tool === "describe_metric" ? `catalogue lookup: ${p.args.name}` : `lineage lookup: ${p.args.name}`, "res");
        caption(p.tool === "query_metric" ? `One certified definition becomes one SQL statement. The consent predicate is added by the compiler, <b>never by the agent</b>.`
          : `Read from the catalogue: no data rows are touched.`); } });
      if (!res.refused && p.tool === "query_metric") {
        s.push({ lp: "Each insurer saw only its own applicants: a row policy on every product, applied before the first query.", cx: "Consent per customer and company, added by the compiler, never by the agent, and tested by a cross-tenant eval on every PR.", t: "Consent filter", d: `customer_id = '${customer}'`, go: async () => {
          await fly("w-sc", { color: "pk" }); setNode("n-con", "hot");
          $("con-label").textContent = `customer_id = '${customer}'`;
          caption(`The query is scoped to <b>${customer}</b>. Companies that haven't shared their data with ${customer}, or revoked it, are invisible, to people and agents alike.`); } });
        s.push({ lp: "Agents queried certified gold only. Bronze and silver held no agent grants.", cx: "Watch cost and load: agent queries carry their own workload tag, and popular Insights can be cached per company.", t: "Gold answers", d: `${res.rows.length} row(s) from ${res.citation.product}`, go: async () => {
          await fly("w-cg", { color: "pk" }); setNode("n-gold", "hot");
          log("gold · Delta", { rows: res.rows.slice(0, 6), more: Math.max(0, res.rows.length - 6) }, "res");
          caption(`<code>${res.citation.product}</code> at Delta version <b>${res.citation.version}</b> returns ${res.rows.length} row(s).`); } });
      }
      s.push({ lp: "An answer without a citation was logged as a failure, not shown as an answer.", cx: "Return the product version and freshness, so a lender can say exactly which number they relied on.", t: "Result with citation", d: "Back to the agent: rows, SQL, citation, caveats.", go: async () => {
        await fly(res.refused || p.tool !== "query_metric" ? "w-ss" : "w-gs", { reverse: true, color: "pv" });
        const body = res.refused ? { isError: false, structuredContent: res } : { structuredContent: p.tool === "query_metric"
          ? { rows: res.rows.slice(0, 3), citation: res.citation, caveats: res.caveats } : res };
        log("server → client", { jsonrpc: "2.0", id: 3, result: body }, res.refused ? "err" : "res");
        await fly("w-as", { reverse: true, color: "pv" });
        setNode("n-agent", "on");
        caption(res.refused ? `The refusal is a normal result with a reason, so the agent can explain it rather than guess.`
          : `Every result carries its citation: metric, product, version, owner and contract checks${res.citation ? ` (${res.citation.checks})` : ""}.`); } });
    }
    s.push({ lp: "Once people and agents shared one layer, ad-hoc requests fell 60%: 214 to 86 over two quarters.", cx: "Measure it: share of answers with a citation, refusals that were right, and analyst time saved, before widening access.", t: "The agent answers", d: "Cited, or refused with a reason.", go: async () => {
      await fly("w-ua", { reverse: true, color: "pv" });
      ["n-sem", "n-con", "n-gold", "n-server"].forEach((n) => setNode(n, n === "n-server" ? "on" : ""));
      const a = answerText(p, res);
      caption(`${a.no ? "✕ " : "✓ "}${a.text}${res.citation ? `<br><span style="font-size:.85rem;color:#a9a8d8">Source: ${res.citation.product} v${res.citation.version} · ${res.citation.checks} · owner ${res.citation.owner}</span>` : ""}`); } });
    return s;
  }

  function renderSteps() {
    $("steps").innerHTML = steps.map((s, i) => `<li data-i="${i}" class="${i < idx ? "done" : i === idx ? "now" : ""}">
      <span class="dot">${i < idx ? "✓" : i + 1}</span><span><b>${NX.esc(s.t)}</b>${NX.esc(view === "codat" ? s.d : s[VIEW[view][1]])}</span></li>`).join("");
    $("steps").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => jump(+li.dataset.i)));
  }
  function resetStage() {
    run++; playing = false; $("play").textContent = "▶ Play";
    ["n-user", "n-sem", "n-con", "n-gold"].forEach((n) => setNode(n, ""));
    setNode("n-agent", "off"); setNode("n-server", "off");
    ["w-ua", "w-as", "w-ss", "w-sc", "w-cg", "w-gs"].forEach((w) => setWire(w, ""));
    $("agent-state").textContent = "not connected"; $("con-label").textContent = "customer_id = ?";
    $("refuse-x").setAttribute("opacity", 0); drawTools(false);
    $("wirelog").innerHTML = ""; $("persona-label").textContent = $("who").value.includes("northbank") ? "Northbank" : "Brightpay";
    caption(`Without MCP, an agent either knows nothing about the data, or is handed raw tables and a broad service account. Press <b>Play</b>.`);
    steps = build(); idx = -1; renderSteps();
  }
  async function stepForward() {
    if (idx >= steps.length - 1) return false;
    idx++; renderSteps(); const my = run;
    await steps[idx].go();
    showCaption();
    return my === run;
  }
  async function jump(target) {
    resetStage(); instant = true;
    while (idx < target) await stepForward();
    instant = false; renderSteps();
  }
  async function play() {
    if (playing) { playing = false; $("play").textContent = "▶ Play"; return; }
    if (idx >= steps.length - 1) resetStage();
    playing = true; $("play").textContent = "❚❚ Pause"; const my = run;
    while (playing && my === run && idx < steps.length - 1) {
      const ok = await stepForward(); if (!ok) return;
      await wait(1100);
    }
    if (my === run) { playing = false; $("play").textContent = "↻ Replay"; }
  }
  document.querySelectorAll("#views [role=tab]").forEach((b) => b.addEventListener("click", () => {
    view = b.dataset.view;
    document.querySelectorAll("#views [role=tab]").forEach((x) => x.setAttribute("aria-selected", x === b));
    $("stage").dataset.view = view; renderSteps(); showCaption();
  }));
  $("play").addEventListener("click", play);
  $("next").addEventListener("click", () => { playing = false; $("play").textContent = "▶ Play"; stepForward(); });
  $("prev").addEventListener("click", () => jump(Math.max(-1, idx - 1)));
  $("reset").addEventListener("click", resetStage);
  $("speed").addEventListener("change", (e) => (speed = +e.target.value));
  ["who", "scenario"].forEach((id) => $(id).addEventListener("change", resetStage));
  resetStage();
  // start on its own once the stage is on screen
  new IntersectionObserver((es, ob) => { if (es[0].isIntersecting && idx < 0) { ob.disconnect(); setTimeout(play, 600); } }, { threshold: .2 }).observe($("stage"));

  // ---------- chat ----------
  let who2 = "analyst@northbank.example";
  const personas = [["analyst@northbank.example", "Northbank analyst"], ["analyst@brightpay.example", "Brightpay analyst"]];
  const renderPersona = () => ($("persona2").innerHTML = personas.map(([k, l]) =>
    `<button aria-pressed="${k === who2}" data-k="${k}">${l}</button>`).join(""));
  $("persona2").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { who2 = b.dataset.k; renderPersona(); } });
  renderPersona();
  const QS = [["Revenue by month for C-104", 0], ["Online sales for C-101 in September", 0], ["Net operating cash flow for C-107 by month", 0],
    ["What is DSO for C-102 in August?", 0], ["Revenue growth by month for C-108", 0], ["Data completeness for C-107", 0],
    ["How do you define revenue?", 0], ["Where does the cash flow number come from?", 0],
    ["What was revenue for C-101 in August?", 1], ["Revenue by month for C-112", 1], ["What's the gross margin for C-104?", 1],
    ["Should we lend to C-107?", 1], ["List the counterparty bank details for C-104", 1]];
  $("asks").innerHTML = QS.map(([q, r]) => `<button class="${r ? "refuse" : ""}">${NX.esc(q)}</button>`).join("");
  $("asks").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { $("q").value = b.textContent; answer(b.textContent); } });
  $("chatform").addEventListener("submit", (e) => { e.preventDefault(); if ($("q").value.trim()) answer($("q").value.trim()); });
  function answer(q) {
    const out = SEM.ask(q, who2), p = out.plan, res = out.result, a = answerText(p, res);
    $("answer").innerHTML = `<div class="kicker">${NX.esc(who2)} asks</div><p style="font-weight:650">“${NX.esc(q)}”</p>
      <div class="bubble ${a.no ? "no" : ""}">${a.text}</div>
      ${res.citation ? `<div class="cite">Source: <code>${res.citation.product}</code> v${res.citation.version} · ${res.citation.checks} · owner ${res.citation.owner} · fresh within ${res.citation.freshness_hours}h${res.caveats?.length ? `<br>Caveat: ${NX.esc(res.caveats[0])}` : ""}</div>` : ""}
      <div class="trace">${p.tool ? `tools/call ${p.tool} ${NX.esc(JSON.stringify(p.args))}` : `no tool call: refused (${p.refuse})`}${res.sql ? `\n\n${NX.esc(res.sql)}` : ""}${res.refused && p.tool ? `\n\nrefused: ${res.reason}` : ""}</div>`;
  }
})();
