/* RecallSRE static demo — the entire memory loop runs in the browser.
   Same TF-IDF memory + agent logic as the Python backend, zero server needed.
   INCIDENTS is injected via incidents.js (generated from incidents.json). */
const $ = (id) => document.getElementById(id);

/* ---------- memory layer (port of backend/memory/local_store.py) ---------- */
function tokenize(text) {
  return (String(text).toLowerCase().match(/[a-z0-9]+(?:[._-][a-z0-9]+)*/g) || []);
}
function incidentToText(inc) {
  return [inc.title, "service " + inc.service, "severity " + inc.severity,
    inc.error_signature, (inc.symptoms || []).join(" "),
    inc.root_cause, inc.fix, (inc.investigation_steps || []).join(" ")
  ].filter(Boolean).join("\n");
}
class MemoryStore {
  constructor() { this.docs = new Map(); this.order = []; }
  store(inc) {
    const id = inc.id || ("INC-" + String(this.docs.size + 1).padStart(4, "0"));
    inc = { ...inc, id };
    this.docs.set(id, inc);
    if (!this.order.includes(id)) this.order.push(id);
    return id;
  }
  count() { return this.docs.size; }
  recent(n = 5) { return this.order.slice(-n).reverse().map((id) => this.docs.get(id)); }
  search(queryText, topK = 3) {
    const qTokens = tokenize(queryText);
    if (!qTokens.length || !this.docs.size) return [];
    const ids = [...this.order];
    const docTokens = ids.map((id) => tokenize(incidentToText(this.docs.get(id))));
    const df = {};
    docTokens.forEach((toks) => new Set(toks).forEach((t) => { df[t] = (df[t] || 0) + 1; }));
    const n = docTokens.length;
    const idf = (t) => Math.log((n + 1) / ((df[t] || 0) + 1)) + 1;
    const vec = (toks) => {
      const tf = {}; toks.forEach((t) => { tf[t] = (tf[t] || 0) + 1; });
      const v = {}; Object.keys(tf).forEach((t) => { v[t] = (tf[t] / toks.length) * idf(t); });
      return v;
    };
    const norm = (v) => Math.sqrt(Object.values(v).reduce((s, x) => s + x * x, 0)) || 1e-9;
    const qv = vec(qTokens), qn = norm(qv);
    return ids.map((id, i) => {
      const dv = vec(docTokens[i]);
      let dot = 0;
      Object.keys(qv).forEach((t) => { dot += (qv[t] || 0) * (dv[t] || 0); });
      return { incident: this.docs.get(id), score: dot / (qn * norm(dv)) };
    })
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }
}

/* ---------- agent (port of backend/agent/core.py) ---------- */
function analyze(alert) {
  return {
    draft: {
      title: alert.title || "Untitled incident",
      service: alert.service || "unknown",
      severity: alert.severity || "high",
      error_signature: alert.error_signature || "",
      symptoms: alert.symptoms || [],
      logs_snippet: alert.logs_snippet || "",
      deployment: alert.deployment || {},
    },
    queryText: [alert.title, "service " + alert.service, alert.error_signature,
      (alert.symptoms || []).join(" "), (alert.logs_snippet || "").slice(0, 2000)]
      .filter(Boolean).join("\n"),
  };
}
function recommend(draft, matches) {
  if (!matches.length) {
    return {
      mode: "cold_start",
      headline: "No similar incidents in memory yet.",
      body: "I don't have enough historical context for this signature. Possible areas to check: " +
        "database connectivity, recent deployments, dependency health. Resolve this incident and I'll " +
        "remember it — the next similar one will get a memory-backed recommendation.",
      suggested_steps: ["Check service dashboards for error rate / latency spikes",
        "Correlate incident start time with recent deployments",
        "Inspect downstream dependency health"],
      confidence_note: "Cold start — no historical data.",
    };
  }
  const top = matches[0], ti = top.incident;
  const causes = [], steps = [], seen = new Set();
  matches.forEach((m) => {
    const inc = m.incident;
    if (inc.root_cause && !causes.includes(inc.root_cause)) causes.push(inc.root_cause);
    (inc.investigation_steps || []).slice(0, 2).forEach((s) => { if (!steps.includes(s)) steps.push(s); });
    (inc.commands_used || []).slice(0, 2).forEach((c) => {
      if (!seen.has(c)) { seen.add(c); steps.push("`" + c + "`"); }
    });
  });
  return {
    mode: "memory_match",
    headline: Math.round(top.score * 100) + "% similarity to " + ti.id + " — " + ti.title,
    body: "Incident " + ti.id + " had the same error signature and similar symptoms. Its root cause was: " +
      ti.root_cause + " It was resolved in " + ti.mttr_minutes + " minutes by: " + ti.fix,
    likely_causes: causes.slice(0, 3),
    suggested_steps: steps.slice(0, 6),
    confidence_note: "Based on " + matches.length + " similar past incident(s). Top match similarity: " +
      Math.round(top.score * 100) + "%. Verify before acting — similar symptoms can have different root causes.",
  };
}

/* ---------- demo scenarios ---------- */
const SCENARIOS = [
  { key: "pool", sev: "CRITICAL", title: "payment-service returning 500s",
    desc: "Error rate 34%, p99 latency 9s, deploy v3.1.2 went out 22 min ago",
    alert: { title: "payment-service returning 500 errors", service: "payment-service", severity: "critical",
      error_signature: "HTTP 500 spike + 'remaining connection slots are reserved' in postgres logs",
      symptoms: ["p99 latency jumped from 180ms to 9.1s", "error rate 34% on /api/v1/pay/charge",
        "postgres logs: 'remaining connection slots are reserved for non-replication superuser connections'",
        "HikariPool - Connection is not available, request timed out after 30000ms"],
      logs_snippet: "2026-09-28T05:41:02Z ERROR [HikariPool-1 housekeeper] HikariPool-1 - Connection is not available, request timed out after 30000ms.",
      deployment: { version: "v3.1.2", deployed_at: "22 minutes ago" },
      stats: { errorRate: "34%", latency: "9.1s p99", affected: "8,412 users", started: "05:38 UTC" } } },
  { key: "flag", sev: "HIGH", title: "checkout 404s after flag rollout",
    desc: "Checkout success 99% → 0% at exactly 14:00 UTC, flag went to 100%",
    alert: { title: "checkout failing after feature flag rollout", service: "order-service", severity: "high",
      error_signature: "100% of checkout requests failing with PricingV2Exception after flag rollout",
      symptoms: ["checkout success rate 99.1% → 0% at exactly 14:00 UTC",
        "flag express-checkout rolled to 100% at 14:00 UTC",
        "PricingV2Exception: endpoint /v2/price not found (404)"],
      logs_snippet: "2026-09-28T14:00:31Z ERROR [http-nio-8080-exec-55] PricingV2Exception: endpoint /v2/price not found (404)",
      deployment: { version: "v2.9.0", deployed_at: "3 days ago" },
      stats: { errorRate: "100% checkout", latency: "—", affected: "all checkouts", started: "14:00 UTC" } } },
  { key: "redis", sev: "HIGH", title: "search-service cache collapse",
    desc: "Cache hit rate 96% → 11%, Jedis pool exhausted, DB CPU 92%",
    alert: { title: "search-service latency spike, cache failing", service: "search-service", severity: "high",
      error_signature: "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
      symptoms: ["cache hit rate collapsed 96% → 11%", "p95 latency 240ms → 3.1s",
        "Jedis pool exhausted: 500/500 connections borrowed", "DB CPU spiked to 92% from cache-miss thundering herd"],
      logs_snippet: "2026-09-28T06:12:44Z ERROR redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
      deployment: { version: "v2.6.2", deployed_at: "2 days ago" },
      stats: { errorRate: "9%", latency: "3.1s p95", affected: "21,300 users", started: "06:02 UTC" } } },
  { key: "novel", sev: "MEDIUM", title: "websocket gateway dropping connections",
    desc: "Unfamiliar signature — tests the honest low-confidence path",
    alert: { title: "websocket gateway dropping idle connections", service: "api-gateway", severity: "medium",
      error_signature: "WebSocket close code 1006 spikes on idle connections > 5min",
      symptoms: ["websocket close code 1006 rate up 40x", "only connections idle > 5 minutes affected",
        "no deployment in the last 48 hours", "LB access logs show RST from client side"],
      logs_snippet: "2026-09-28T07:20:11Z WARN [ws-gateway] close code 1006 for 1,204 idle sessions in 60s window",
      deployment: { version: "v3.0.0", deployed_at: "3 days ago" },
      stats: { errorRate: "ws drops 40x", latency: "—", affected: "1,204 sessions", started: "07:15 UTC" } } },
];

/* ---------- app state ---------- */
const trained = new MemoryStore(), empty = new MemoryStore();
INCIDENTS.forEach((i) => trained.store(i));
let mode = "trained";
let currentDraft = null;
const mem = () => (mode === "trained" ? trained : empty);

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function refreshHealth() {
  $("memCount").textContent = mem().count();
  const bb = $("backendBadge");
  bb.innerHTML = "memory: <b>browser</b> · " + mem().count() + " incidents";
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  $("memStrip").innerHTML = mem().recent()
    .map((r) => `<span class="memchip">${esc(r.id)} · ${esc(r.title.slice(0, 42))}</span>`).join("") ||
    `<span class="empty-note">memory is empty — resolve an incident and it will be remembered here.</span>`;
}

function renderScenarios() {
  $("scenarios").innerHTML = SCENARIOS.map((s, i) =>
    `<button class="scenario" data-i="${i}"><div class="sev">● ${s.sev}</div>` +
    `<div class="t">${esc(s.title)}</div><div class="d">${esc(s.desc)}</div></button>`).join("");
  document.querySelectorAll(".scenario").forEach((b) =>
    b.addEventListener("click", () => investigate(SCENARIOS[+b.dataset.i])));
}

function renderLive(alert, stats) {
  $("livePanel").innerHTML = `<h3><span class="dot"></span> Live incident</h3>
    <dl class="kv"><dt>service</dt><dd>${esc(alert.service)}</dd>
    <dt>error rate</dt><dd class="big-red">${esc(stats.errorRate)}</dd>
    <dt>latency</dt><dd>${esc(stats.latency)}</dd><dt>affected</dt><dd>${esc(stats.affected)}</dd>
    <dt>started</dt><dd>${esc(stats.started)}</dd>
    <dt>signature</dt><dd style="font-size:11px">${esc(alert.error_signature.slice(0, 90))}…</dd></dl>`;
}

function renderMatches(matches) {
  if (!matches.length) {
    $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
      <div class="empty-note">No similar incidents found.<br>The agent is in cold-start mode — its recommendation will say so honestly.</div>`;
    return;
  }
  $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
    <div style="font-size:12px;color:var(--muted);margin-bottom:10px">${matches.length} similar incident${matches.length > 1 ? "s" : ""} found</div>` +
    matches.map((m) => { const pct = Math.round(m.score * 100); return `
      <div class="match"><div class="row"><span class="id">${esc(m.incident.id)}</span><span class="score">${pct}% similar</span></div>
      <div class="title">${esc(m.incident.title)}</div><div class="bar"><i style="width:${pct}%"></i></div>
      <div class="meta">resolved ${esc((m.incident.resolved_at || "").slice(0, 10))} · MTTR ${m.incident.mttr_minutes ?? "?"} min</div></div>`; }).join("");
}

function renderBefore(matches) {
  if (!matches.length) {
    $("beforePanel").innerHTML = `<h3>📋 What happened before</h3><div class="empty-note">Nothing to show — no historical incidents match.</div>`;
    return;
  }
  const m = matches[0].incident;
  $("beforePanel").innerHTML = `<h3>📋 What happened before — ${esc(m.id)}</h3>
    <dl class="kv"><dt>root cause</dt><dd style="font-size:12px;line-height:1.5">${esc((m.root_cause || "").slice(0, 220))}…</dd>
    <dt>fix</dt><dd style="font-size:12px;line-height:1.5">${esc((m.fix || "").slice(0, 220))}…</dd>
    <dt>resolved in</dt><dd>${m.mttr_minutes ?? "?"} minutes</dd></dl>`;
}

function renderRec(rec) {
  if (rec.mode === "cold_start") {
    $("recPanel").innerHTML = `<h3>⚡ Recommendation</h3>
      <div class="cold"><b style="color:var(--text)">${esc(rec.headline)}</b><br><br>${esc(rec.body)}</div>
      <h4>Suggested first steps</h4><ul>${rec.suggested_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      <div class="conf">${esc(rec.confidence_note)}</div>`;
    return;
  }
  $("recPanel").innerHTML = `<h3>⚡ Recommendation</h3><div class="rec">
    <div class="rec-headline">${esc(rec.headline)}</div><div class="rec-body">${esc(rec.body)}</div>
    <h4>Likely causes (from past incidents)</h4>
    <ul>${(rec.likely_causes || []).map((s) => `<li>${esc(s.slice(0, 160))}…</li>`).join("")}</ul>
    <h4>Suggested investigation steps</h4>
    <ul>${(rec.suggested_steps || []).map((s) => `<li>${s.startsWith("`") ? `<code>${esc(s.slice(1, -1))}</code>` : esc(s)}</li>`).join("")}</ul>
    <div class="conf">⚠ ${esc(rec.confidence_note)}</div></div>`;
}

function investigate(scn) {
  const { draft, queryText } = analyze(scn.alert);
  const matches = mem().search(queryText, 3);
  currentDraft = draft;
  renderLive(scn.alert, scn.alert.stats);
  renderMatches(matches);
  renderBefore(matches);
  renderRec(recommend(draft, matches));
  $("resolveSection").classList.remove("hidden");
  $("learned").classList.remove("show");
  $("resolveSection").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function resolveIncident(ev) {
  ev.preventDefault();
  const btn = $("resolveBtn");
  btn.disabled = true;
  const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const id = mem().store({
    ...currentDraft,
    root_cause: $("fRoot").value, fix: $("fFix").value,
    engineer: $("fEng").value || "on-call",
    mttr_minutes: parseInt($("fMttr").value || "0", 10),
    resolved_at: now, outcome: "resolved",
  });
  btn.disabled = false;
  $("learned").innerHTML = `✓ Incident resolved and stored as <b>${esc(id)}</b> — organizational memory now holds <b>${mem().count()}</b> incidents. The next similar incident will be smarter.`;
  $("learned").classList.add("show");
  refreshHealth();
}

function setMode(m) {
  mode = m;
  ["livePanel", "matchPanel", "beforePanel", "recPanel"].forEach((id) => {
    $(id).innerHTML = `<div class="empty-note">${m === "empty"
      ? "Day 1 — memory is blank. Fire an incident above and watch the agent admit it has no history."
      : "Day 120 — 28 incidents remembered. Fire the same incident and watch the difference."}</div>`;
  });
  $("resolveSection").classList.add("hidden");
  refreshHealth();
}

document.addEventListener("DOMContentLoaded", () => {
  renderScenarios();
  refreshHealth();
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("resolveForm").addEventListener("submit", resolveIncident);
});
