// The code, runnable: open any file from the repo, edit it, and run the pure-Python parts in Pyodide.
// Spark modules are shown with what they need; they run in CI and with ./scripts/build.sh.
(async () => {
  const $ = (id) => document.getElementById(id);
  const files = await NX.get("assets/data/files.json");
  const byPath = Object.fromEntries(files.map((f) => [f.path, f]));
  const BADGE = { browser: ["runs in your browser", "b-run"], spark: ["needs Spark · runs in CI", "b-spark"],
                  tests: ["tests · run below", "b-test"], view: ["read only", "b-view"],
                  local: ["Dagster · GX · MCP · Claude: runs in a Python env", "b-local"] };
  const MODE = { py: "python", yml: "yaml", yaml: "yaml", sql: "sql", sh: "shell", txt: null, js: "javascript" };
  const original = {}, edited = {};
  // a missing file must fail loudly: never hand Python an HTML 404 page as source
  const text = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(`${p}: HTTP ${r.status} from the site`); return r.text(); });
  let current = null;

  // ---------- file tree ----------
  const folders = {};
  files.forEach((f) => (folders[f.folder] ??= []).push(f));
  $("tree").innerHTML = Object.entries(folders).map(([dir, fs]) => `<div class="tree-dir">${NX.esc(dir === "." ? "repo root" : dir + "/")}</div>` +
    fs.map((f) => `<button class="tree-file" data-path="${NX.esc(f.path)}"><span>${NX.esc(f.path.split("/").pop())}</span>
      <i class="dot-${f.runs}" title="${BADGE[f.runs][0]}"></i></button>`).join("")).join("");

  const cm = CodeMirror($("editor"), { value: "", mode: "python", lineNumbers: true, indentUnit: 4, theme: "nexus",
    viewportMargin: 20, lineWrapping: false });
  cm.setSize("100%", "100%");
  cm.on("change", () => { if (current) { edited[current] = cm.getValue(); $("dirty").hidden = edited[current] === original[current]; } });

  // ---------- Lineage tab: where the open file sits in the table graph ----------
  const LIN = await NX.get("assets/data/code_lineage.json");
  const checks = await NX.get("assets/data/lineage.json").catch(() => ({}));
  let view = "code", picked = null;
  const COLS = ["landing", "bronze", "silver", "gold", "serve"], NW = 160, NH = 24, NG = 7, CX = (i) => 12 + i * 178, TOP = 34;
  const at = {};
  COLS.forEach((c, i) => LIN.nodes.filter((n) => n.layer === c).forEach((n, j) => (at[n.id] = { x: CX(i), y: TOP + j * (NH + NG) })));
  const H = TOP + Math.max(...COLS.map((c) => LIN.nodes.filter((n) => n.layer === c).length)) * (NH + NG) + 8;
  const up = {}, down = {};
  LIN.edges.forEach(([a, b]) => { (down[a] ??= []).push(b); (up[b] ??= []).push(a); });
  const walk = (id, g, seen = new Set()) => { (g[id] || []).forEach((x) => { if (!seen.has(x)) { seen.add(x); walk(x, g, seen); } }); return seen; };
  const short = (n) => n.label.replace(/^insights_/, "");
  const label = (id) => { const n = LIN.nodes.find((x) => x.id === id); return n ? (n.layer === "serve" ? n.label : `${n.layer}.${n.label}`) : id; };
  function drawLineage() {
    const f = LIN.files[current] || { role: "not part of the table graph", reads: [], writes: [] };
    let R = new Set(f.reads), W = new Set(f.writes);
    if (picked) { R = new Set([...walk(picked, up), ...walk(picked, down)]); W = new Set([picked]); }
    const hot = ([a, b]) => picked ? (R.has(a) || a === picked) && (R.has(b) || b === picked) : (R.has(a) || W.has(a)) && W.has(b);
    const edge = ([a, b]) => { const p = at[a], q = at[b], x1 = p.x + NW, y1 = p.y + NH / 2, x2 = q.x, y2 = q.y + NH / 2, same = p.x === q.x;
      const d = same ? `M${p.x + NW} ${y1} C ${p.x + NW + 16} ${y1}, ${q.x + NW + 16} ${y2}, ${q.x + NW} ${y2}` : `M${x1} ${y1} C ${x1 + 9} ${y1}, ${x2 - 9} ${y2}, ${x2} ${y2}`;
      return `<path class="le${hot([a, b]) ? " hot" : ""}" d="${d}"/>`; };
    const node = (n) => { const p = at[n.id], ck = n.layer === "gold" && checks[n.label];
      const cls = W.has(n.id) ? " w" : R.has(n.id) ? " r" : "";
      return `<g class="ln${cls}${picked === n.id ? " sel" : ""}" data-node="${n.id}" transform="translate(${p.x},${p.y})"><title>${NX.esc(n.id)}${n.source ? " · " + NX.esc(n.source) : ""}</title>
        <rect width="${NW}" height="${NH}" rx="6"/><text x="8" y="16">${NX.esc(short(n)).slice(0, ck ? 19 : 23)}</text>
        ${ck ? `<text x="${NW - 6}" y="16" text-anchor="end" class="${ck.checks_passed === ck.checks_total ? "ok" : "bad"}">${ck.checks_passed === ck.checks_total ? "✓" : "✕"}${ck.checks_passed}/${ck.checks_total}</text>` : ""}</g>`; };
    $("lin-svg").setAttribute("viewBox", `0 0 900 ${H}`);
    $("lin-svg").innerHTML = COLS.map((c, i) => `<text x="${CX(i) + 2}" y="18" style="font:700 10px var(--mono);letter-spacing:.14em;fill:#8f92c4">${c.toUpperCase()}</text>`).join("") +
      LIN.edges.filter((e) => !hot(e)).map(edge).join("") + LIN.edges.filter(hot).map(edge).join("") + LIN.nodes.map(node).join("");
    const users = (id, k) => Object.entries(LIN.files).filter(([, v]) => v[k].includes(id)).map(([p]) => p);
    const list = (ids) => ids.length ? `<ul>${ids.map((i) => `<li>${NX.esc(label(i))}</li>`).join("")}</ul>` : `<p style="color:#8f92c4">none</p>`;
    const flist = (ps) => ps.length ? `<ul>${ps.map((p) => `<li><button data-lin-open="${NX.esc(p)}">${NX.esc(p)}</button></li>`).join("")}</ul>` : `<p style="color:#8f92c4">none</p>`;
    const key = `<div class="lin-key"><span><i style="background:#5a1f4a;border:1px solid var(--pink)"></i>writes</span><span><i style="background:#24206e;border:1px solid #8f7dff"></i>reads</span><span><i style="background:#141650;border:1px solid #2f3270"></i>elsewhere</span></div>`;
    $("lin-info").innerHTML = picked
      ? `<b style="color:#fff">${NX.esc(picked)}</b> <button data-lin-clear>back to the file</button>
         <h4>Upstream</h4>${list([...walk(picked, up)])}<h4>Downstream</h4>${list([...walk(picked, down)])}
         <h4>Written by</h4>${flist(users(picked, "writes"))}<h4>Read by</h4>${flist(users(picked, "reads"))}`
      : `<b style="color:#fff">${NX.esc(current)}</b><p style="margin:.3rem 0 0;color:#a9a8d8">${NX.esc(f.role)}</p>${key}
         <h4>Writes</h4>${list(f.writes)}<h4>Reads</h4>${list(f.reads)}<p style="margin-top:.8rem;color:#8f92c4;font-size:.74rem">Click any table to trace it up and downstream. Built from the repo by <code>scripts/code_lineage.py</code>.</p>`;
  }
  function show(v) {
    view = v;
    document.querySelectorAll(".ide-tabs button").forEach((b) => { b.classList.toggle("on", b.dataset.view === v); b.setAttribute("aria-selected", b.dataset.view === v); });
    $("editor").hidden = v !== "code"; $("lineage").hidden = v !== "lineage";
    if (v === "lineage") drawLineage(); else cm.refresh();
  }
  document.querySelector(".ide-tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) show(b.dataset.view); });
  $("lineage").addEventListener("click", (e) => {
    const n = e.target.closest("[data-node]"), o = e.target.closest("[data-lin-open]");
    if (o) { picked = null; open(o.dataset.linOpen); return; }
    if (e.target.closest("[data-lin-clear]")) { picked = null; drawLineage(); return; }
    if (n) { picked = picked === n.dataset.node ? null : n.dataset.node; drawLineage(); }
  });

  async function open(path) {
    current = path; const f = byPath[path];
    if (!(path in original)) original[path] = await text(path);
    cm.setOption("mode", MODE[path.split(".").pop()] ?? null);
    cm.setValue(edited[path] ?? original[path]); cm.clearHistory();
    document.querySelectorAll(".tree-file").forEach((b) => b.classList.toggle("active", b.dataset.path === path));
    $("fname").textContent = path;
    const [label, cls] = BADGE[f.runs];
    $("badge").textContent = label; $("badge").className = `badge ${cls}`;
    $("gh").href = `https://github.com/rfim/nexus-codat/blob/main/${path}`;
    $("run").disabled = f.runs !== "browser";
    $("run").title = f.runs === "spark" ? "This module needs Spark and Delta. It runs in CI and with ./scripts/build.sh." :
      f.runs === "tests" ? "Run the tests with the panel below." : "";
    $("dirty").hidden = (edited[path] ?? original[path]) === original[path];
    if (f.runs === "local") note(`<b>${NX.esc(path)}</b> runs in a real Python environment (Dagster, Great Expectations, the MCP client and the Anthropic SDK). ` +
      `It ran for this page with <code>./scripts/build.sh</code>; the results are in the Orchestrator page.`);
    if (f.runs === "spark") note(`<b>${NX.esc(path)}</b> needs PySpark and Delta, which can't run in a browser. ` +
      `It ran for real to produce every number on this page; run it yourself with <code>./scripts/build.sh</code>, or see the CI log.`);
    history.replaceState(null, "", `#code=${encodeURIComponent(path)}`);
    if (view === "lineage") { picked = null; drawLineage(); }
  }
  $("tree").addEventListener("click", (e) => { const b = e.target.closest(".tree-file"); if (b) open(b.dataset.path); });
  $("reset").addEventListener("click", () => { if (current) { delete edited[current]; cm.setValue(original[current]); } });

  // ---------- Pyodide ----------
  const out = $("out");
  const write = (s, cls = "") => { const span = document.createElement("span"); if (cls) span.className = cls; span.textContent = s; out.appendChild(span); out.scrollTop = 1e9; };
  const note = (html) => { out.innerHTML = `<span class="o-note">${html}</span>`; };
  let py = null;
  async function boot() {
    if (py) return py;
    write("Loading Python (Pyodide, about 10 MB the first time)…\n", "o-note");
    const t0 = performance.now();
    py = await loadPyodide({ indexURL: "assets/vendor/pyodide/", stdout: (s) => write(s + "\n"), stderr: (s) => write(s + "\n", "o-err") });
    const need = files.filter((f) => /^(src|contracts|semantic|evals|tests|examples)\//.test(f.path)).map((f) => f.path);
    const data = ["assets/data/catalogue.json", "assets/data/lineage.json", "assets/data/site.json",
      ...["revenue", "cash_flow", "dso", "commerce"].map((p) => `assets/data/products/insights_${p}_monthly.json`),
      "assets/data/products/insights_data_completeness.json"];
    const shims = ["yaml.py", "pytest.py", "nexus_browser.py", "mcp/__init__.py", "mcp/server/__init__.py", "mcp/server/mcpserver.py"];
    const put = (path, text) => {
      const dir = path.split("/").slice(0, -1);
      for (let i = 1; i <= dir.length; i++) { const d = dir.slice(0, i).join("/"); if (d && !py.FS.analyzePath(d).exists) py.FS.mkdir(d); }
      py.FS.writeFile(path, text);
    };
    await Promise.all([...need, ...data].map(async (p) => put(`/repo/${p}`, await text(p))));
    await Promise.all(shims.map(async (s) => put(`/shims/${s}`, await text(`assets/pyshims/${s}`))));
    py.runPython(`import sys; sys.path[:0] = ["/shims", "/repo/src"]; import os; os.chdir("/repo")`);
    write(`Python ${py.runPython("import sys; sys.version.split()[0]")} ready in ${((performance.now() - t0) / 1000).toFixed(1)}s. ` +
      `${need.length} repo files mounted at /repo.\n\n`, "o-note");
    return py;
  }
  async function runCurrent() {
    if (!current || byPath[current].runs !== "browser") return;
    out.innerHTML = ""; $("run").disabled = true;
    try {
      const p = await boot();
      for (const [path, text] of Object.entries(edited)) p.FS.writeFile(`/repo/${path}`, text);
      write(`$ python ${current}${current in edited && edited[current] !== original[current] ? "   (your edited version)" : ""}\n`, "o-cmd");
      const t0 = performance.now();
      p.globals.set("TARGET_FILE", current);
      p.runPython("import nexus_browser; nexus_browser.run_file(TARGET_FILE)");
      write(`\n✓ finished in ${((performance.now() - t0) / 1000).toFixed(2)}s\n`, "o-ok");
    } catch (e) {
      write(String(e.message || e).split("\n").slice(-12).join("\n") + "\n", "o-err");
    } finally { $("run").disabled = false; }
  }
  $("run").addEventListener("click", runCurrent);
  cm.setOption("extraKeys", { "Ctrl-Enter": runCurrent, "Cmd-Enter": runCurrent });

  // ---------- tests ----------
  const report = await NX.get("assets/data/tests.json").catch(() => null);
  if (report) {
    $("t-sum").innerHTML = `<b class="pass">${report.passed} passed</b> · ${report.skipped} skipped · <b class="${report.failed ? "fail" : ""}">${report.failed} failed</b>
      · ${report.total} tests in ${report.seconds}s, last run ${new Date(report.generated_at).toLocaleString("en-GB")}`;
    $("t-suites").innerHTML = report.suites.map((s) => {
      const c = (k) => s.tests.filter((t) => t.outcome === k).length;
      return `<details class="suite"><summary><code>${s.file}</code><span>${NX.esc(s.about)}</span>
        <span class="pill ${s.spark ? "b-spark" : "b-run"}">${s.spark ? "Spark" : "pure Python"}</span>
        <span class="${c("failed") ? "fail" : "pass"}">${c("passed")}/${s.tests.length}</span>
        <button class="linkish" data-open="${s.file}">open</button></summary>
        <ul class="tlist">${s.tests.map((t) => `<li class="${t.outcome}"><span>${t.outcome === "passed" ? "✓" : t.outcome === "skipped" ? "–" : "✕"}</span>${NX.esc(t.name)}<i>${t.seconds}s</i></li>`).join("")}</ul></details>`;
    }).join("");
    $("t-suites").addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) { e.preventDefault(); open(b.dataset.open); $("code").scrollIntoView({ behavior: "smooth" }); } });
  }
  $("t-run").addEventListener("click", async () => {
    const box = $("t-live"); box.innerHTML = ""; $("t-run").disabled = true;
    try {
      const p = await boot();
      const which = files.filter((f) => f.runs === "tests" && f.path.startsWith("tests/test_") && !["test_site.py", "test_code_lineage.py"].includes(f.path.split("/").pop())).map((f) => f.path);
      p.globals.set("TEST_FILES", p.toPy(which));
      const t0 = performance.now();
      const res = p.runPython("import nexus_browser; [list(r) for r in nexus_browser.run_tests(TEST_FILES)]").toJs();
      const n = (k) => res.filter((r) => r[2] === k).length;
      box.innerHTML = `<p><b class="pass">${n("passed")} passed</b> · ${n("skipped")} skipped (DuckDB parity needs DuckDB; the Spark suites run in CI) ·
        <b class="${n("failed") ? "fail" : ""}">${n("failed")} failed</b> · in your browser, ${((performance.now() - t0) / 1000).toFixed(1)}s</p>` +
        `<ul class="tlist">${res.filter((r) => r[2] !== "skipped").map((r) => `<li class="${r[2]}"><span>${r[2] === "passed" ? "✓" : "✕"}</span>${NX.esc(r[0].replace("tests/", ""))} · ${NX.esc(r[1])}${r[3] ? `<i class="fail">${NX.esc(r[3])}</i>` : ""}</li>`).join("")}</ul>`;
    } catch (e) { box.innerHTML = `<pre class="o-err">${NX.esc(String(e.message || e))}</pre>`; }
    finally { $("t-run").disabled = false; }
  });

  // tasks in the run chart open their code
  document.addEventListener("click", (e) => { const a = e.target.closest("[data-code]"); if (a) { e.preventDefault(); open(a.dataset.code); $("code").scrollIntoView({ behavior: "smooth" }); } });
  const start = decodeURIComponent((location.hash.match(/code=([^&]+)/) || [])[1] || "examples/04_mcp_tools_as_two_customers.py");
  open(byPath[start] ? start : files[0].path);
})();
