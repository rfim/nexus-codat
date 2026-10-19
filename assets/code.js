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

  async function open(path) {
    current = path; const f = byPath[path];
    if (!(path in original)) original[path] = await fetch(path).then((r) => r.text());
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
    await Promise.all([...need, ...data].map(async (p) => put(`/repo/${p}`, await fetch(p).then((r) => r.text()))));
    await Promise.all(shims.map(async (s) => put(`/shims/${s}`, await fetch(`assets/pyshims/${s}`).then((r) => r.text()))));
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
      const which = files.filter((f) => f.runs === "tests" && f.path.startsWith("tests/test_") && !["test_site.py"].includes(f.path.split("/").pop())).map((f) => f.path);
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
