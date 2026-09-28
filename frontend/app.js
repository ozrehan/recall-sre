/* RecallSRE dashboard logic — guided demo: fire → recall → recommend → teach */
const $ = (id) => document.getElementById(id);

/* Four demo scenarios. The first three mirror real archetypes in memory
   (so matches are strong); the fourth is deliberately novel, showing the
   agent's honest low-confidence path. */
const SCENARIOS = [
  {
    key: "pool",
    sev: "CRITICAL", title: "payment-service returning 500s",
    desc: "Error rate 34%, p99 latency 9s, deploy v3.1.2 went out 22 min ago.",
    impact: "8,412 users affected · started 05:38 UTC",
    alert: {
      title: "payment-service returning 500 errors",
      service: "payment-service", severity: "critical",
      error_signature: "HTTP 500 spike + 'remaining connection slots are reserved' in postgres logs",
      symptoms: [
        "p99 latency jumped from 180ms to 9.1s",
        "error rate 34% on /api/v1/pay/charge",
        "postgres logs: 'remaining connection slots are reserved for non-replication superuser connections'",
        "HikariPool - Connection is not available, request timed out after 30000ms",
      ],
      logs_snippet: "2026-09-28T05:41:02Z ERROR [HikariPool-1 housekeeper] HikariPool-1 - Connection is not available, request timed out after 30000ms.",
      deployment: { version: "v3.1.2", deployed_at: "22 minutes ago" },
      stats: { errorRate: "34%", latency: "9.1s p99", affected: "8,412 users", started: "05:38 UTC" },
    },
  },
  {
    key: "flag",
    sev: "HIGH", title: "checkout 404s after flag rollout",
    desc: "Checkout success 99% → 0% at exactly 14:00 UTC, when the flag hit 100%.",
    impact: "All checkouts failing · started 14:00 UTC",
    alert: {
      title: "checkout failing after feature flag rollout",
      service: "order-service", severity: "high",
      error_signature: "100% of checkout requests failing with PricingV2Exception after flag rollout",
      symptoms: [
        "checkout success rate 99.1% → 0% at exactly 14:00 UTC",
        "flag express-checkout rolled to 100% at 14:00 UTC",
        "PricingV2Exception: endpoint /v2/price not found (404)",
      ],
      logs_snippet: "2026-09-28T14:00:31Z ERROR [http-nio-8080-exec-55] PricingV2Exception: endpoint /v2/price not found (404)",
      deployment: { version: "v2.9.0", deployed_at: "3 days ago" },
      stats: { errorRate: "100% checkout", latency: "—", affected: "all checkouts", started: "14:00 UTC" },
    },
  },
  {
    key: "redis",
    sev: "HIGH", title: "search-service cache collapse",
    desc: "Cache hit rate 96% → 11%, connection pool exhausted, DB CPU 92%.",
    impact: "21,300 users affected · started 06:02 UTC",
    alert: {
      title: "search-service latency spike, cache failing",
      service: "search-service", severity: "high",
      error_signature: "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
      symptoms: [
        "cache hit rate collapsed 96% → 11%",
        "p95 latency 240ms → 3.1s",
        "Jedis pool exhausted: 500/500 connections borrowed",
        "DB CPU spiked to 92% from cache-miss thundering herd",
      ],
      logs_snippet: "2026-09-28T06:12:44Z ERROR redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
      deployment: { version: "v2.6.2", deployed_at: "2 days ago" },
      stats: { errorRate: "9%", latency: "3.1s p95", affected: "21,300 users", started: "06:02 UTC" },
    },
  },
  {
    key: "novel",
    sev: "MEDIUM", title: "websocket gateway dropping connections",
    desc: "Unfamiliar signature — watch the agent admit it has no matching history.",
    impact: "1,204 sessions affected · started 07:15 UTC",
    alert: {
      title: "websocket gateway dropping idle connections",
      service: "api-gateway", severity: "medium",
      error_signature: "WebSocket close code 1006 spikes on idle connections > 5min",
      symptoms: [
        "websocket close code 1006 rate up 40x",
        "only connections idle > 5 minutes affected",
        "no deployment in the last 48 hours",
        "LB access logs show RST from client side",
      ],
      logs_snippet: "2026-09-28T07:20:11Z WARN [ws-gateway] close code 1006 for 1,204 idle sessions in 60s window",
      deployment: { version: "v3.0.0", deployed_at: "3 days ago" },
      stats: { errorRate: "ws drops 40x", latency: "—", affected: "1,204 sessions", started: "07:15 UTC" },
    },
  },
];

let currentDraft = null;
let seedIncidents = [];

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function setStep(n) {
  for (let i = 1; i <= 4; i++) {
    const el = $("step" + i);
    el.classList.toggle("active", i === n);
    el.classList.toggle("done", i < n);
  }
}

/* ---------- health / memory overview ---------- */
async function refreshHealth() {
  const h = await api("/api/health");
  $("memCount").textContent = h.memory_size;
  const bb = $("backendBadge");
  bb.innerHTML = `memory: <b>${esc(h.backend)}</b> · ${h.memory_size} incidents`;
  bb.classList.toggle("hindsight", h.backend === "hindsight");
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === h.mode));
  const m = await api("/api/memory");
  $("memStrip").innerHTML =
    m.recent.map((r) => `<span class="memchip"><b>${esc(r.id)}</b> ${esc(r.title.slice(0, 40))}</span>`).join("") ||
    `<span class="empty-note">Memory is empty — resolve an incident and it will be remembered here.</span>`;
  renderStats(m, h);
}

function renderStats(m, h) {
  const mttrs = seedIncidents.map((i) => i.mttr_minutes).filter((x) => typeof x === "number");
  const avgMttr = mttrs.length ? Math.round(mttrs.reduce((a, b) => a + b, 0) / mttrs.length) : "—";
  const services = new Set(seedIncidents.map((i) => i.service)).size;
  $("statsRow").innerHTML = `
    <div class="stat"><div class="v green">${m.size}</div><div class="k">incidents remembered</div></div>
    <div class="stat"><div class="v amber">${avgMttr}${avgMttr === "—" ? "" : " min"}</div><div class="k">avg resolution time</div></div>
    <div class="stat"><div class="v blue">${services}</div><div class="k">services covered</div></div>
    <div class="stat"><div class="v purple">${esc(h.backend)}</div><div class="k">memory backend</div></div>`;
  renderGrowthChart();
}

function renderGrowthChart() {
  // bucket seed incidents by ISO week -> real data, shows memory accumulating
  const buckets = {};
  seedIncidents.forEach((i) => {
    const d = (i.resolved_at || "").slice(0, 10);
    if (!d) return;
    buckets[d] = (buckets[d] || 0) + 1;
  });
  const days = Object.keys(buckets).sort().slice(-14);
  if (!days.length) { $("growthChart").innerHTML = `<div class="empty-note">No data yet.</div>`; return; }
  const max = Math.max(...days.map((d) => buckets[d]));
  let cum = 0;
  $("growthChart").innerHTML = days.map((d) => {
    cum += buckets[d];
    const h = Math.max(6, Math.round((cum / (seedIncidents.length || 1)) * 100));
    return `<div class="cbar" title="${d}: ${cum} total"><b>${cum}</b><i style="height:${h}px"></i><span>${d.slice(5)}</span></div>`;
  }).join("");
}

/* ---------- step 1: scenarios ---------- */
function renderScenarios() {
  $("scenarios").innerHTML = SCENARIOS.map((s, i) => `
    <button class="scenario" data-i="${i}">
      <div class="top"><span class="sev ${s.sev.toLowerCase()}">${s.sev}</span><span class="svc">${esc(s.alert.service)}</span></div>
      <div class="t">${esc(s.title)}</div>
      <div class="d">${esc(s.desc)}</div>
      <div class="impact">⚠ <b>${esc(s.impact)}</b></div>
    </button>`).join("");
  document.querySelectorAll(".scenario").forEach((b) =>
    b.addEventListener("click", () => investigate(SCENARIOS[+b.dataset.i])));
}

/* ---------- steps 2 & 3 ---------- */
function renderLive(alert, stats) {
  $("livePanel").innerHTML = `
    <h3><span class="dot"></span> Live incident — paging now</h3>
    <div class="hint">What the on-call engineer sees at 05:38 UTC.</div>
    <dl class="kv">
      <dt>service</dt><dd>${esc(alert.service)}</dd>
      <dt>error rate</dt><dd class="big-red">${esc(stats.errorRate)}</dd>
      <dt>latency</dt><dd>${esc(stats.latency)}</dd>
      <dt>affected</dt><dd>${esc(stats.affected)}</dd>
      <dt>started</dt><dd>${esc(stats.started)}</dd>
      <dt>deployed</dt><dd>${esc(alert.deployment.version)} · ${esc(alert.deployment.deployed_at)}</dd>
    </dl>
    <div class="logbox">${esc(alert.logs_snippet)}</div>`;
}

function renderMatches(matches, scoreLabel) {
  if (!matches.length) {
    $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
      <div class="hint">Past incidents that look like this one — none found.</div>
      <div class="empty-note">Day 1: the agent just joined the team.<br>It has <b>no history</b> to draw on, so its recommendation below will say so honestly.</div>`;
    return;
  }
  $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
    <div class="hint">Past incidents that look like this one — ranked by ${esc(scoreLabel)}.</div>` +
    matches.map((m, i) => `
      <div class="match${i === 0 ? " top" : ""}">
        <div class="row">
          <div><span class="rank">#${i + 1}</span><span class="id">${esc(m.id)}</span></div>
          <div class="score">${m.score_pct}%<small>${esc(scoreLabel)}</small></div>
        </div>
        <div class="title">${esc(m.title)}</div>
        <div class="bar"><i style="width:${m.score_pct}%"></i></div>
        <div class="meta"><span>resolved ${esc(m.resolved_at?.slice(0, 10) ?? "—")}</span><span>MTTR <b>${m.mttr_minutes ?? "?"} min</b></span></div>
        <details><summary>What was the fix?</summary>
          <p><b>Root cause:</b> ${esc((m.root_cause || "").slice(0, 200))}${(m.root_cause || "").length > 200 ? "…" : ""}</p>
          <p><b>Fix:</b> ${esc((m.fix || "").slice(0, 200))}${(m.fix || "").length > 200 ? "…" : ""}</p>
        </details>
      </div>`).join("");
}

function renderRec(rec) {
  if (rec.mode === "cold_start") {
    $("recPanel").innerHTML = `<h3>⚡ Agent recommendation</h3>
      <div class="rec-headline">🧊 ${esc(rec.headline)}
        <span class="why">No historical incidents match this signature — the agent refuses to guess.</span>
      </div>
      <div class="cold">${esc(rec.body)}</div>
      <h4 style="font-size:11.5px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);margin:16px 0 8px">Sane first steps (generic runbook)</h4>
      <div class="rec"><ol class="steps-list">${rec.suggested_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>
      <div class="conf">⚠ ${esc(rec.confidence_note)} Resolve this incident below and the agent will remember it.</div>`;
    return;
  }
  $("recPanel").innerHTML = `<h3>⚡ Agent recommendation</h3>
    <div class="rec">
      <div class="rec-headline">${esc(rec.headline)}
        <span class="why">Built from ${rec.likely_causes?.length ?? 0} past incident(s) with the same signature — cited below.</span>
      </div>
      <div style="font-size:14px;line-height:1.7;margin-bottom:4px">${esc(rec.body)}</div>
      <h4>Likely causes — seen before</h4>
      <ul class="causes">${(rec.likely_causes || []).map((s) => `<li>${esc(s.slice(0, 180))}${s.length > 180 ? "…" : ""}</li>`).join("")}</ul>
      <h4>Suggested investigation steps — in order</h4>
      <ol class="steps-list">${(rec.suggested_steps || []).map((s) => {
        const body = s.startsWith("`") && s.endsWith("`")
          ? `<span class="cmdchip">${esc(s.slice(1, -1))}</span>`
          : esc(s);
        return `<li>${body}</li>`;
      }).join("")}</ol>
      <div class="conf">⚠ ${esc(rec.confidence_note)}</div>
    </div>`;
}

/* ---------- flow ---------- */
async function investigate(scn) {
  setStep(2);
  const res = await api("/api/investigate", { method: "POST", body: JSON.stringify({ alert: scn.alert }) });
  if (res.error) { alert("error: " + res.error); return; }
  currentDraft = res.incident;
  renderLive(scn.alert, scn.alert.stats);
  renderMatches(res.matches, res.score_label || "similar");
  renderRec(res.recommendation);
  setStep(3);
  $("resolveSection").classList.remove("hidden");
  $("learned").classList.remove("show");
  ["fRoot", "fFix", "fSteps", "fCmds"].forEach((id) => { $(id).value = ""; });
}

async function resolveIncident(ev) {
  ev.preventDefault();
  const btn = $("resolveBtn");
  btn.disabled = true;
  const steps = $("fSteps").value.split(";").map((s) => s.trim()).filter(Boolean);
  const cmds = $("fCmds").value.split(";").map((s) => s.trim()).filter(Boolean);
  const res = await api("/api/resolve", {
    method: "POST",
    body: JSON.stringify({
      draft: currentDraft,
      root_cause: $("fRoot").value,
      fix: $("fFix").value,
      engineer: $("fEng").value || "on-call",
      mttr_minutes: parseInt($("fMttr").value || "0", 10),
      investigation_steps: steps,
      commands_used: cmds,
    }),
  });
  btn.disabled = false;
  if (res.error) { alert("error: " + res.error); return; }
  setStep(4);
  $("learned").innerHTML = `🧠 <b>Learned.</b> Incident stored as <b>${esc(res.id)}</b> — organizational memory now holds <b>${res.memory_size}</b> incidents. Fire a similar incident and watch the agent recall this one.`;
  $("learned").classList.add("show");
  $("learned").scrollIntoView({ behavior: "smooth", block: "nearest" });
  refreshHealth();
}

async function setMode(mode) {
  await api("/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
  setStep(1);
  const msg = mode === "empty"
    ? "🧊 <b>Day 1</b> — the agent just joined. Memory is blank: fire an incident and watch it admit it has no history."
    : "🧠 <b>Day 120</b> — 28 incidents remembered. Fire the <i>same</i> incident and watch the difference memory makes.";
  $("livePanel").innerHTML = `<h3><span class="dot"></span> Live incident</h3><div class="empty-note">${msg}</div>`;
  $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3><div class="empty-note">${msg}</div>`;
  $("recPanel").innerHTML = `<h3>⚡ Agent recommendation</h3><div class="empty-note">${msg}</div>`;
  $("resolveSection").classList.add("hidden");
  refreshHealth();
}

document.addEventListener("DOMContentLoaded", async () => {
  renderScenarios();
  setStep(1);
  try {
    const d = await api("/api/incidents");
    seedIncidents = d.incidents || [];
  } catch (e) { /* chart just stays empty */ }
  refreshHealth();
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("resolveForm").addEventListener("submit", resolveIncident);
});
