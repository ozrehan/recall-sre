/* TraceMind — ChatGPT-style chat logic */
const $ = (id) => document.getElementById(id);

const SCENARIOS = [
  {
    key: "pool", sev: "CRITICAL", title: "payment-service returning 500s",
    desc: "Error rate 34%, p99 9s, deploy v3.1.2 went out 22 min ago.",
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
    },
  },
  {
    key: "flag", sev: "HIGH", title: "checkout 404s after flag rollout",
    desc: "Checkout 99% → 0% at exactly 14:00 UTC, flag hit 100%.",
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
    },
  },
  {
    key: "redis", sev: "HIGH", title: "search-service cache collapse",
    desc: "Cache hit 96% → 11%, pool exhausted, DB CPU 92%.",
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
    },
  },
  {
    key: "novel", sev: "MEDIUM", title: "websocket gateway dropping connections",
    desc: "Unfamiliar signature — watch the agent admit it has no history.",
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
    },
  },
];

let seedIncidents = [];
let busy = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- chat primitives ---------- */
function scrollBottom() { $("chat").scrollTop = $("chat").scrollHeight; }

function addUserMsg(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  thread().appendChild(el); scrollBottom();
}
function addAgentMsg() {
  const el = document.createElement("div");
  el.className = "msg agent";
  el.innerHTML = `<div class="avatar"><img src="logo-icon.png" alt="TM"></div><div class="body"></div>`;
  thread().appendChild(el); scrollBottom();
  return el.querySelector(".body");
}
function thread() {
  let t = document.querySelector(".thread");
  if (!t) { t = document.createElement("div"); t.className = "thread"; $("chat").appendChild(t); }
  return t;
}
function addTyping(body) {
  const d = document.createElement("div");
  d.className = "typing"; d.innerHTML = "<i></i><i></i><i></i>";
  body.appendChild(d); scrollBottom();
  return d;
}
const say = (body, html) => { const p = document.createElement("div"); p.innerHTML = html; body.appendChild(p); scrollBottom(); };

/* ---------- cards ---------- */
function incidentCard(alert) {
  return `<div class="card"><h5>🚨 Live incident</h5>
    <dl class="kv">
      <dt>service</dt><dd>${esc(alert.service)}</dd>
      <dt>severity</dt><dd class="alert">${esc(alert.severity)}</dd>
      <dt>signature</dt><dd>${esc(alert.error_signature)}</dd>
      <dt>deployed</dt><dd>${esc(alert.deployment.version)} · ${esc(alert.deployment.deployed_at)}</dd>
    </dl>
    <div class="logbox">${esc(alert.logs_snippet)}</div></div>`;
}
function matchesCard(matches, scoreLabel) {
  if (!matches.length)
    return `<div class="card"><h5>🧠 Memory search</h5>
      <p>No similar past incidents found. Day 1: the agent just joined the team and has <b>no history</b> — the recommendation below says so honestly instead of guessing.</p></div>`;
  const cards = matches.map((m, i) => `
    <div class="match${i === 0 ? " top" : ""}">
      <div class="row"><div><span class="id">${esc(m.id)}</span></div>
        <div class="score">${m.score_pct}%<small>${esc(scoreLabel)}</small></div></div>
      <div class="title">${esc(m.title)}</div>
      <div class="bar"><i style="width:${m.score_pct}%"></i></div>
      <div class="meta"><span>MTTR <b>${m.mttr_minutes ?? "?"} min</b></span></div>
      <details><summary>What was the fix?</summary>
        <p><b>Root cause:</b> ${esc((m.root_cause || "").slice(0, 220))}</p>
        <p><b>Fix:</b> ${esc((m.fix || "").slice(0, 220))}</p>
      </details>
    </div>`).join("");
  return `<div class="card"><h5>🧠 Memory search — ranked by ${esc(scoreLabel)}</h5>${cards}</div>`;
}
function recCard(rec) {
  if (rec.mode === "cold_start")
    return `<div class="card"><h5>⚡ Recommendation</h5>
      <div class="rec-headline">🧊 ${esc(rec.headline)}<span class="why">No historical incidents match — the agent refuses to guess.</span></div>
      <p style="font-size:13.5px">${esc(rec.body)}</p>
      <ol class="steps-list">${rec.suggested_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
      <div class="conf">⚠ ${esc(rec.confidence_note)} Resolve this incident below and the agent will remember it.</div></div>`;
  const steps = (rec.suggested_steps || []).map((s) => {
    const body = s.startsWith("`") && s.endsWith("`") ? `<span class="cmdchip">${esc(s.slice(1, -1))}</span>` : esc(s);
    return `<li>${body}</li>`;
  }).join("");
  const causes = (rec.likely_causes || []).map((s) => `<li>${esc(s.slice(0, 180))}${s.length > 180 ? "…" : ""}</li>`).join("");
  return `<div class="card"><h5>⚡ Recommendation</h5>
    <div class="rec-headline">${esc(rec.headline)}<span class="why">Built from past incidents with the same signature — cited above.</span></div>
    <p style="font-size:13.5px">${esc(rec.body)}</p>
    ${causes ? `<p style="font-size:12px;color:var(--muted);margin:8px 0 2px"><b>Likely causes — seen before:</b></p><ul class="causes">${causes}</ul>` : ""}
    <p style="font-size:12px;color:var(--muted);margin:8px 0 2px"><b>Investigation steps — in order:</b></p>
    <ol class="steps-list">${steps}</ol>
    <div class="conf">⚠ ${esc(rec.confidence_note)}</div></div>`;
}
function resolveCard(draft, onDone) {
  const wrap = document.createElement("div");
  wrap.className = "card";
  wrap.innerHTML = `<h5>📝 Resolve &amp; teach — close the loop</h5>
    <p style="font-size:13px;color:var(--muted);margin-bottom:10px">The post-mortem goes into organizational memory, so the <i>next</i> similar incident starts smarter.</p>
    <div class="rform">
      <div><label>Root cause</label><textarea data-f="root" placeholder="e.g. DB connection pool exhausted after deploy v3.1.2"></textarea></div>
      <div><label>Fix applied</label><textarea data-f="fix" placeholder="e.g. Raised pool max 100 → 300, added leak detection"></textarea></div>
      <div class="two">
        <div><label>Engineer</label><input data-f="eng" placeholder="on-call"></div>
        <div><label>MTTR (minutes)</label><input data-f="mttr" type="number" min="1" value="8"></div>
      </div>
      <div><button class="btn" data-act="save">Store in organizational memory →</button></div>
    </div>`;
  const btn = wrap.querySelector("[data-act=save]");
  btn.onclick = async () => {
    const v = (k) => wrap.querySelector(`[data-f=${k}]`).value.trim();
    if (!v("root") || !v("fix")) { btn.textContent = "Root cause + fix needed ↑"; setTimeout(() => btn.textContent = "Store in organizational memory →", 1500); return; }
    btn.disabled = true; btn.textContent = "Storing…";
    const res = await api("/api/resolve", { method: "POST", body: JSON.stringify({
      draft, root_cause: v("root"), fix: v("fix"),
      engineer: v("eng") || "on-call", mttr_minutes: parseInt(v("mttr") || "8", 10),
    })});
    btn.disabled = false;
    if (res.error) { btn.textContent = "Error — try again"; return; }
    wrap.innerHTML = `<div class="learned-ok">🧠 <b>Learned.</b> Stored as <b>${esc(res.id)}</b> — memory now holds <b>${res.memory_size}</b> incidents. Fire a similar incident and watch the agent recall this one.</div>`;
    scrollBottom(); refreshMemory(); onDone && onDone(res);
    logActivity("resolved", draft.title || "Incident resolved",
      `Root cause stored in memory — ${res.memory_size} incidents remembered`);
  };
  return wrap;
}

/* ---------- activity panel ---------- */
const ACT_KEY = "tm_activity_v1";
function getActivity() {
  try { return JSON.parse(localStorage.getItem(ACT_KEY) || "[]"); } catch (e) { return []; }
}
function logActivity(type, title, desc) {
  const items = getActivity();
  items.unshift({ type, title, desc, ts: Date.now() });
  try { localStorage.setItem(ACT_KEY, JSON.stringify(items.slice(0, 100))); } catch (e) {}
  renderActivity();
}
function fmtTime(ts) {
  const d = new Date(ts);
  let h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "pm" : "am"; h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}
const ACT_ICON = { fired: "🚨", resolved: "✓" };
let actFilter = "all";
function renderActivity() {
  const list = $("actList"); if (!list) return;
  const items = getActivity().filter((a) => actFilter === "all" || a.type === actFilter);
  if (!items.length) {
    list.innerHTML = `<div class="act-empty">No activity yet.<br>Fire an incident to get started.</div>`;
    return;
  }
  list.innerHTML = items.map((a) => `
    <div class="act-item">
      <div class="act-ico">${ACT_ICON[a.type] || "•"}</div>
      <div><b>${esc(a.title)}</b><p>${esc(a.desc)}</p>
      <span class="act-time">${fmtTime(a.ts)}</span></div>
    </div>`).join("");
}
function setActPanel(open) {
  $("actPanel").classList.toggle("open", open);
  $("actScrim").classList.toggle("show", open);
}

/* ---------- flow ---------- */
async function investigate(alert, userLabel) {
  if (busy) return; busy = true;
  $("chips").style.display = "none";
  addUserMsg(userLabel || `🚨 ${alert.title} — ${alert.service} · ${alert.severity}`);
  addHistory(alert);
  logActivity("fired", alert.title, `${alert.service} · ${alert.severity} — investigation started`);
  const body = addAgentMsg();
  const t1 = addTyping(body);
  const res = await api("/api/investigate", { method: "POST", body: JSON.stringify({ alert }) });
  t1.remove();
  if (res.error) { say(body, `<p>Something went wrong: ${esc(res.error)}</p>`); busy = false; return; }

  say(body, `<p>On it — pulling the alert apart and checking what we've seen before.</p>`);
  await sleep(450);
  say(body, incidentCard(alert));
  const t2 = addTyping(body); await sleep(650); t2.remove();
  say(body, `<p>Searching organizational memory for similar incidents…</p>`);
  await sleep(350);
  say(body, matchesCard(res.matches, res.score_label || "similarity"));
  await sleep(450);
  say(body, recCard(res.recommendation));
  await sleep(300);
  say(body, `<p>When it's fixed, teach me — that's how the memory grows:</p>`);
  body.appendChild(resolveCard(res.incident));
  scrollBottom();
  busy = false;
}

function alertFromText(text) {
  return {
    title: text.length > 80 ? text.slice(0, 80) + "…" : text,
    service: "unknown-service", severity: "medium",
    error_signature: text,
    symptoms: [text],
    logs_snippet: text,
    deployment: { version: "unknown", deployed_at: "unknown" },
  };
}

/* ---------- history ---------- */
function addHistory(alert) {
  const empty = document.querySelector(".history-empty");
  if (empty) empty.remove();
  const b = document.createElement("button");
  b.className = "hist-item";
  b.innerHTML = `<span class="sevdot"></span><span class="t">${esc(alert.title)}</span>`;
  b.title = alert.title;
  b.onclick = () => investigate(alert);
  $("historyList").prepend(b);
}

/* ---------- memory sidebar ---------- */
async function refreshMemory() {
  try {
    const h = await api("/api/health");
    $("memCount").textContent = h.memory_size;
    $("memBackend").textContent = h.backend;
    $("backendBadge").innerHTML = `memory: <b>${esc(h.backend)}</b>`;
    document.querySelectorAll(".timetravel button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === h.mode));
    const m = await api("/api/memory");
    const mttrs = seedIncidents.map((i) => i.mttr_minutes).filter((x) => typeof x === "number");
    $("memMttr").textContent = mttrs.length ? Math.round(mttrs.reduce((a, b) => a + b, 0) / mttrs.length) + " min" : "—";
    $("memSvc").textContent = new Set(seedIncidents.map((i) => i.service)).size || "—";
    try {
      const s = await api("/api/db/stats");
      $("memDb").textContent = `sqlite · ${s.total_incidents}`;
    } catch (e) { $("memDb").textContent = "—"; }
  } catch (e) { /* offline */ }
}

/* ---------- mode / new chat ---------- */
function welcome(mode) {
  $("chat").innerHTML = "";
  $("chips").style.display = "";
  const body = addAgentMsg();
  const msg = mode === "empty"
    ? `<p>🧊 <b>Day 1 — I just joined the team.</b> My memory is blank: fire an incident and I'll tell you honestly that I have no history to draw on.</p>
       <p>Then flip to <b>Day 120</b> and fire the <i>same</i> incident — the difference is organizational memory.</p>`
    : `<p>👋 I'm <b>TraceMind</b> — I turn every production incident into organizational memory.</p>
       <p>Fire an incident (pick one below or describe your own) and I'll search <b>past incidents</b>, show what fixed them, and recommend investigation steps — as evidence-backed hypotheses, never false certainty. When you resolve it, I'll remember the post-mortem.</p>`;
  say(body, msg);
}
function renderChips() {
  $("chips").innerHTML = SCENARIOS.map((s, i) =>
    `<button class="chip" data-i="${i}"><span class="sevtag">${s.sev}</span>${esc(s.title)}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => investigate(SCENARIOS[+c.dataset.i].alert)));
}
async function setMode(mode) {
  if (busy) return;
  await api("/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
  welcome(mode); refreshMemory();
}

/* ---------- composer ---------- */
function send() {
  const inp = $("input");
  const text = inp.value.trim();
  if (!text || busy) return;
  inp.value = ""; inp.style.height = "auto"; $("sendBtn").disabled = true;
  investigate(alertFromText(text), text);
}
document.addEventListener("DOMContentLoaded", async () => {
  renderChips();
  welcome("trained");
  try { const d = await api("/api/incidents"); seedIncidents = d.incidents || []; } catch (e) {}
  refreshMemory();
  const inp = $("input");
  inp.addEventListener("input", () => {
    inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 160) + "px";
    $("sendBtn").disabled = !inp.value.trim();
  });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("sendBtn").addEventListener("click", send);
  $("sendBtn").disabled = true;
  $("newChatBtn").addEventListener("click", () => {
    if (busy) return;
    welcome(document.querySelector(".timetravel button.active").dataset.mode);
    document.body.classList.remove("side-open");
  });
  document.querySelectorAll(".timetravel button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("burger").addEventListener("click", () => document.body.classList.toggle("side-open"));
  $("scrim").addEventListener("click", () => document.body.classList.remove("side-open"));
  $("activityBtn").addEventListener("click", () => { renderActivity(); setActPanel(true); });
  $("actClose").addEventListener("click", () => setActPanel(false));
  $("actScrim").addEventListener("click", () => setActPanel(false));
  document.querySelectorAll("#actTabs button").forEach((b) =>
    b.addEventListener("click", () => {
      actFilter = b.dataset.f;
      document.querySelectorAll("#actTabs button").forEach((x) => x.classList.toggle("active", x === b));
      renderActivity();
    }));
});
