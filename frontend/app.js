/* RecallSRE dashboard logic */
const $ = (id) => document.getElementById(id);

/* Four demo scenarios. The first three mirror real archetypes in memory
   (so matches are strong); the fourth is deliberately novel, showing the
   agent's honest low-confidence path. */
const SCENARIOS = [
  {
    key: "pool",
    sev: "CRITICAL", title: "payment-service returning 500s",
    desc: "Error rate 34%, p99 latency 9s, deploy v3.1.2 went out 22 min ago",
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
    desc: "Checkout success 99% → 0% at exactly 14:00 UTC, flag went to 100%",
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
    desc: "Cache hit rate 96% → 11%, Jedis pool exhausted, DB CPU 92%",
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
    desc: "Unfamiliar signature — tests the honest low-confidence path",
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

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  return r.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function refreshHealth() {
  const h = await api("/api/health");
  $("memCount").textContent = h.memory_size;
  const bb = $("backendBadge");
  bb.innerHTML = `memory: <b>${esc(h.backend)}</b> · ${h.memory_size} incidents`;
  bb.classList.toggle("hindsight", h.backend === "hindsight");
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === h.mode)
  );
  const m = await api("/api/memory");
  $("memStrip").innerHTML =
    m.recent.map((r) => `<span class="memchip">${esc(r.id)} · ${esc(r.title.slice(0, 42))}</span>`).join("") ||
    `<span class="empty-note">memory is empty — resolve an incident and it will be remembered here.</span>`;
}

function renderScenarios() {
  $("scenarios").innerHTML = SCENARIOS.map(
    (s, i) => `<button class="scenario" data-i="${i}">
      <div class="sev">● ${s.sev}</div>
      <div class="t">${esc(s.title)}</div>
      <div class="d">${esc(s.desc)}</div>
    </button>`
  ).join("");
  document.querySelectorAll(".scenario").forEach((b) =>
    b.addEventListener("click", () => investigate(SCENARIOS[+b.dataset.i]))
  );
}

function renderLive(alert, stats) {
  $("livePanel").innerHTML = `
    <h3><span class="dot"></span> Live incident</h3>
    <dl class="kv">
      <dt>service</dt><dd>${esc(alert.service)}</dd>
      <dt>error rate</dt><dd class="big-red">${esc(stats.errorRate)}</dd>
      <dt>latency</dt><dd>${esc(stats.latency)}</dd>
      <dt>affected</dt><dd>${esc(stats.affected)}</dd>
      <dt>started</dt><dd>${esc(stats.started)}</dd>
      <dt>signature</dt><dd style="font-size:11px">${esc(alert.error_signature.slice(0, 90))}…</dd>
    </dl>`;
}

function renderMatches(matches, scoreLabel = "similar") {
  if (!matches.length) {
    $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
      <div class="empty-note">No similar incidents found.<br>The agent is in cold-start mode — its recommendation will say so honestly.</div>`;
    return;
  }
  $("matchPanel").innerHTML = `<h3>🧠 Hindsight memory</h3>
    <div style="font-size:12px;color:var(--muted);margin-bottom:10px">${matches.length} similar incident${matches.length > 1 ? "s" : ""} found</div>` +
    matches.map((m) => `
      <div class="match">
        <div class="row"><span class="id">${esc(m.id)}</span><span class="score">${m.score_pct}% ${esc(scoreLabel)}</span></div>
        <div class="title">${esc(m.title)}</div>
        <div class="bar"><i style="width:${m.score_pct}%"></i></div>
        <div class="meta">resolved ${esc(m.resolved_at?.slice(0, 10) ?? "")} · MTTR ${m.mttr_minutes ?? "?"} min</div>
      </div>`).join("");
}

function renderBefore(matches) {
  if (!matches.length) {
    $("beforePanel").innerHTML = `<h3>📋 What happened before</h3>
      <div class="empty-note">Nothing to show — no historical incidents match.</div>`;
    return;
  }
  const m = matches[0];
  $("beforePanel").innerHTML = `<h3>📋 What happened before — ${esc(m.id)}</h3>
    <dl class="kv">
      <dt>root cause</dt><dd style="font-size:12px;line-height:1.5">${esc(m.root_cause.slice(0, 220))}…</dd>
      <dt>fix</dt><dd style="font-size:12px;line-height:1.5">${esc(m.fix.slice(0, 220))}…</dd>
      <dt>resolved in</dt><dd>${m.mttr_minutes ?? "?"} minutes</dd>
    </dl>`;
}

function renderRec(rec) {
  if (rec.mode === "cold_start") {
    $("recPanel").innerHTML = `<h3>⚡ Recommendation</h3>
      <div class="cold"><b style="color:var(--text)">${esc(rec.headline)}</b><br><br>${esc(rec.body)}</div>
      <h4>Suggested first steps</h4>
      <ul>${rec.suggested_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      <div class="conf">${esc(rec.confidence_note)}</div>`;
    return;
  }
  $("recPanel").innerHTML = `<h3>⚡ Recommendation</h3>
    <div class="rec">
      <div class="rec-headline">${esc(rec.headline)}</div>
      <div class="rec-body">${esc(rec.body)}</div>
      <h4>Likely causes (from past incidents)</h4>
      <ul>${(rec.likely_causes || []).map((s) => `<li>${esc(s.slice(0, 160))}…</li>`).join("")}</ul>
      <h4>Suggested investigation steps</h4>
      <ul>${(rec.suggested_steps || []).map((s) => {
        const code = s.startsWith("`") ? `<code>${esc(s.slice(1, -1))}</code>` : esc(s);
        return `<li>${code}</li>`;
      }).join("")}</ul>
      <div class="conf">⚠ ${esc(rec.confidence_note)}</div>
    </div>`;
}

async function investigate(scn) {
  const res = await api("/api/investigate", {
    method: "POST", body: JSON.stringify({ alert: scn.alert }),
  });
  if (res.error) { alert("error: " + res.error); return; }
  currentDraft = res.incident;
  renderLive(scn.alert, scn.alert.stats);
  renderMatches(res.matches, res.score_label || "similar");
  renderBefore(res.matches);
  renderRec(res.recommendation);
  $("resolveSection").classList.remove("hidden");
  $("learned").classList.remove("show");
  $("resolveSection").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function resolveIncident(ev) {
  ev.preventDefault();
  const btn = $("resolveBtn");
  btn.disabled = true;
  const res = await api("/api/resolve", {
    method: "POST",
    body: JSON.stringify({
      draft: currentDraft,
      root_cause: $("fRoot").value,
      fix: $("fFix").value,
      engineer: $("fEng").value || "on-call",
      mttr_minutes: parseInt($("fMttr").value || "0", 10),
    }),
  });
  btn.disabled = false;
  if (res.error) { alert("error: " + res.error); return; }
  $("learned").innerHTML = `✓ Incident resolved and stored as <b>${esc(res.id)}</b> — organizational memory now holds <b>${res.memory_size}</b> incidents. The next similar incident will be smarter.`;
  $("learned").classList.add("show");
  refreshHealth();
}

async function setMode(mode) {
  await api("/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
  // clear panels to force a fresh investigation under the new memory
  ["livePanel", "matchPanel", "beforePanel", "recPanel"].forEach((id) => {
    $(id).innerHTML = `<div class="empty-note">${mode === "empty"
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
    b.addEventListener("click", () => setMode(b.dataset.mode))
  );
  $("resolveForm").addEventListener("submit", resolveIncident);
});
