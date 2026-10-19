// The semantic layer and planner, ported from src/nexus/semantic.py and src/nexus/agent.py.
// Same catalogue, same SQL text, same refusals; the rows are aggregated here from the exported gold tables.
const SEM = (() => {
  const PRINCIPALS = { "analyst@northbank.example": "northbank", "analyst@brightpay.example": "brightpay" };
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
  const PERSONAL = ["iban", "bank details", "account number", "sort code", "email", "phone", "address", "counterparty"];
  const ADVICE = ["should i lend", "should we lend", "approve", "recommend", "is it safe to lend", "credit decision"];
  let cat, lineage, products = {};

  async function load() {
    if (cat) return;
    const [c, l] = await Promise.all([NX.get("assets/data/catalogue.json"), NX.get("assets/data/lineage.json")]);
    cat = Object.fromEntries(c.map((m) => [m.name, m])); lineage = l;
    const names = [...new Set(c.filter((m) => m.product).map((m) => m.product))];
    await Promise.all(names.map(async (p) => (products[p] = await NX.get(`assets/data/products/${p}.json`))));
  }

  class Refused extends Error { constructor(reason, message) { super(message); this.reason = reason; } }

  const requireCertified = (name) => {
    const m = cat[name];
    if (!m) throw new Refused("unknown_metric", `'${name}' is not a metric in the catalogue.`);
    if (!m.certified) throw new Refused("not_certified", `'${m.label}' is not certified yet: ${m.definition}`);
    return m;
  };
  const customerFor = (p) => {
    if (!PRINCIPALS[p]) throw new Refused("unknown_principal", `${p} is not entitled to any customer's data.`);
    return PRINCIPALS[p];
  };

  function compile(name, groupBy, customer, companyId, months) {
    const m = requireCertified(name);
    groupBy = [...new Set(groupBy)];
    const bad = groupBy.filter((d) => !m.dimensions.includes(d));
    if (bad.length) throw new Refused("bad_dimension", `${m.label} can't be split by ${bad.join(", ")}; allowed: ${m.dimensions.join(", ")}.`);
    for (const need of m.requires || []) {
      if (!groupBy.includes(need) && !(need === "company_id" && companyId)) {
        if (m.kind === "point_in_time")
          throw new Refused("non_additive", `${m.label} is point in time: ask for it by ${m.requires.join(" and ")}.`);
        groupBy.push(need);
      }
    }
    const where = [`customer_id = '${customer}'`];
    if (companyId) where.push(`company_id = '${companyId}'`);
    if (months) where.push(`month BETWEEN DATE '${months[0]}-01' AND DATE '${months[1]}-01'`);
    const dims = groupBy.join(", ");
    let sql = `SELECT ${dims ? dims + ", " : ""}${m.expr} AS ${m.name}\nFROM gold.${m.product}\nWHERE ${where.join(" AND ")}`;
    if (dims) sql += `\nGROUP BY ${dims}\nORDER BY ${dims}`;
    return { sql, groupBy, where, m };
  }

  function execute({ m, groupBy }, customer, companyId, months) {
    let rows = products[m.product].filter((r) => r.customer_id === customer && (!companyId || r.company_id === companyId));
    if (months) rows = rows.filter((r) => r.month >= `${months[0]}-01` && r.month <= `${months[1]}-01`);
    const field = (m.expr.match(/^(?:sum|max)\((\w+)\)/) || [])[1];
    const key = (r, dims) => dims.map((d) => r[d]).join("|");
    const groups = new Map();
    for (const r of rows) {
      const k = key(r, groupBy);
      if (!groups.has(k)) groups.set(k, { dims: Object.fromEntries(groupBy.map((d) => [d, r[d]])), rows: [] });
      groups.get(k).rows.push(r);
    }
    if (!groupBy.length && !groups.size) groups.set("", { dims: {}, rows: [] });
    let out = [...groups.values()].sort((a, b) => key(a.dims, groupBy) < key(b.dims, groupBy) ? -1 : 1);
    if (m.kind === "derived") {  // revenue growth: per company, month on month
      const byCo = {};
      for (const g of out) {
        const v = g.rows.reduce((a, r) => a + r.revenue, 0);
        (byCo[g.dims.company_id] ??= []).push({ ...g.dims, v });
      }
      return Object.values(byCo).flatMap((list) => list.map((x, i) => ({
        company_id: x.company_id, month: x.month,
        [m.name]: i === 0 || !list[i - 1].v ? null : +((x.v - list[i - 1].v) / list[i - 1].v).toFixed(4) })));
    }
    return out.map((g) => ({ ...g.dims, [m.name]: g.rows.length ? +(m.kind === "point_in_time"
      ? Math.max(...g.rows.map((r) => r[field] ?? -Infinity)) : g.rows.reduce((a, r) => a + (r[field] || 0), 0)).toFixed(2) : null }));
  }

  function monthOf(q) {
    let mm = q.match(/(20\d\d)-(\d\d)/);
    if (mm) return `${mm[1]}-${mm[2]}`;
    for (let i = 0; i < 12; i++) {
      const n = MONTHS[i];
      if (new RegExp(`\\b(${n}|${n.slice(0, 3)})\\b`).test(q)) {
        const y = q.match(/20\d\d/);
        return `${y ? y[0] : "2026"}-${String(i + 1).padStart(2, "0")}`;
      }
    }
    return null;
  }

  function plan(question) {
    const q = question.toLowerCase();
    if (PERSONAL.some((w) => q.includes(w))) return { refuse: "personal_data", message: "I can't share row-level personal or bank details. I can answer with certified, aggregated metrics." };
    if (ADVICE.some((w) => q.includes(w))) return { refuse: "advice", message: "I can show the data behind a decision, but I don't make lending decisions or give financial advice." };
    const hits = Object.values(cat).filter((m) => (m.synonyms || []).some((s) => q.includes(s)));
    hits.sort((a, b) => Math.max(...b.synonyms.filter((s) => q.includes(s)).map((s) => s.length)) - Math.max(...a.synonyms.filter((s) => q.includes(s)).map((s) => s.length)));
    if (!hits.length) return { refuse: "unknown_metric", message: "That isn't a metric in the catalogue. Try revenue, growth, cash flow, DSO, online sales or data completeness." };
    const metric = hits[0];
    if (q.includes("define") || q.includes("definition") || q.includes("how do you calculate") || (q.includes("what is") && !q.includes("for")))
      return { tool: "describe_metric", args: { name: metric.name } };
    if (q.includes("where does") || q.includes("lineage") || q.includes("come from")) return { tool: "get_lineage", args: { name: metric.name } };
    const args = { name: metric.name, group_by: [] };
    const c = q.match(/\bc-\d{3}\b/);
    if (c) args.company_id = c[0].toUpperCase();
    if (["by month", "trend", "each month", "monthly"].some((w) => q.includes(w))) args.group_by.push("month");
    if (["by company", "each company", "which compan", "per company"].some((w) => q.includes(w))) args.group_by.push("company_id");
    const mo = monthOf(q);
    if (mo) args.month_from = mo;
    return { tool: "query_metric", args };
  }

  // the four MCP tools, as the server implements them
  const tools = {
    list_metrics: () => Object.values(cat).filter((m) => m.certified).map((m) => ({ name: m.name, label: m.label, product: m.product, kind: m.kind, dimensions: m.dimensions, owner: m.owner, freshness_hours: m.freshness_hours })),
    describe_metric: ({ name }) => { const m = requireCertified(name); return Object.fromEntries(["name", "label", "definition", "kind", "unit", "dimensions", "requires", "owner", "caveats", "product"].map((k) => [k, m[k] ?? null])); },
    get_lineage: ({ name }) => lineage[requireCertified(name).product],
    query_metric: ({ name, group_by = [], company_id, month_from, month_to }, principal) => {
      const customer = customerFor(principal);
      const months = month_from ? [month_from, month_to || month_from] : null;
      const compiled = compile(name, group_by, customer, company_id, months);
      const rows = execute(compiled, customer, company_id, months);
      const l = lineage[compiled.m.product];
      return { rows, sql: compiled.sql, caller: principal, customer,
        citation: { metric: name, product: `gold.${compiled.m.product}`, version: l.version, owner: compiled.m.owner,
          freshness_hours: compiled.m.freshness_hours, checks: `${l.checks_passed}/${l.checks_total} contract checks pass` },
        caveats: compiled.m.caveats || [] };
    },
  };

  function call(tool, args, principal) {
    try { return tools[tool](args, principal); }
    catch (e) { if (e instanceof Refused) return { refused: true, reason: e.reason, message: e.message }; throw e; }
  }

  function ask(question, principal) {
    const p = plan(question);
    if (p.refuse) return { plan: p, result: { refused: true, reason: p.refuse, message: p.message } };
    return { plan: p, result: call(p.tool, p.args, principal) };
  }

  return { load, plan, call, ask, compile, PRINCIPALS, get catalogue() { return cat; } };
})();
