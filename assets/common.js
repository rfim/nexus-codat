// Shared helpers: load the run's data, format numbers, small DOM utilities.
const NX = (() => {
  const cache = {};
  const get = (path) => (cache[path] ??= fetch(path).then((r) => {
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }));
  const site = () => get("assets/data/site.json");
  const money = (v, cur = "GBP") => v == null ? "—" :
    new Intl.NumberFormat("en-GB", { style: "currency", currency: cur, maximumFractionDigits: 0 }).format(v);
  const money2 = (v, cur = "GBP") => v == null ? "—" :
    new Intl.NumberFormat("en-GB", { style: "currency", currency: cur, minimumFractionDigits: 2 }).format(v);
  const int = (v) => v == null ? "—" : new Intl.NumberFormat("en-GB").format(v);
  const pct = (v, d = 1) => v == null ? "—" : `${(v * 100).toFixed(d)}%`;
  const month = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const h = (tag, attrs = {}, html = "") => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    el.innerHTML = html;
    return el;
  };
  const table = (rows, cols, fmt = {}) => {
    if (!rows.length) return "<p class='muted'>No rows.</p>";
    cols = cols || Object.keys(rows[0]);
    const th = cols.map((c) => `<th>${esc(c)}</th>`).join("");
    const tr = rows.map((r) => `<tr>${cols.map((c) => {
      const v = r[c];
      const out = fmt[c] ? fmt[c](v, r) : Array.isArray(v) ? v.join(", ") : v == null ? "—" : v;
      return `<td class="${typeof v === "number" ? "num" : ""}">${typeof out === "string" && out.startsWith("<") ? out : esc(out)}</td>`;
    }).join("")}</tr>`).join("");
    return `<div class="tablewrap"><table><tr>${th}</tr>${tr}</table></div>`;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  return { get, site, money, money2, int, pct, month, esc, h, table, sleep };
})();

// the hero network: nodes drifting, linked when close. Static under reduced motion.
(() => {
  const c = document.getElementById("hero-net");
  if (!c) return;
  const ctx = c.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W, H, pts;
  const resize = () => {
    W = c.width = c.offsetWidth * devicePixelRatio; H = c.height = c.offsetHeight * devicePixelRatio;
    pts = Array.from({ length: Math.round((W * H) / 26000 / devicePixelRatio) }, () => ({
      x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .35, vy: (Math.random() - .5) * .35,
      pink: Math.random() < .18 }));
  };
  const frame = () => {
    ctx.clearRect(0, 0, W, H);
    const R = 140 * devicePixelRatio;
    for (const p of pts) {
      if (!still) { p.x += p.vx; p.y += p.vy; if (p.x < 0 || p.x > W) p.vx *= -1; if (p.y < 0 || p.y > H) p.vy *= -1; }
    }
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const a = pts[i], b = pts[j], d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d < R) { ctx.strokeStyle = `rgba(138,115,255,${(1 - d / R) * .35})`; ctx.lineWidth = devicePixelRatio;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
    }
    for (const p of pts) { ctx.fillStyle = p.pink ? "#ff4f8b" : "#8a73ff"; ctx.beginPath();
      ctx.arc(p.x, p.y, (p.pink ? 2.6 : 1.8) * devicePixelRatio, 0, 7); ctx.fill(); }
    if (!still) requestAnimationFrame(frame);
  };
  addEventListener("resize", resize); resize(); frame();
})();
