/* TraceMind — ChatGPT-style chat logic */
const $ = (id) => document.getElementById(id);

let openIncidents = [];
let busy = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- auth: login before profile ---------- */
let authUser = null;
let authMode = "login";
let googleClientId = "";
const tmToken = () => localStorage.getItem("tm_token") || "";
const lastUser = () => { try { return JSON.parse(localStorage.getItem("tm_last_user") || "null"); } catch (e) { return null; } };
const initialOf = (name) => (String(name || "?").trim().charAt(0) || "?").toUpperCase();

function rememberUser(u) {
  localStorage.setItem("tm_last_user", JSON.stringify({ name: u.name, email: u.email }));
}

function renderAuthSlot() {
  const slot = $("authSlot");
  if (authUser) {
    slot.innerHTML = `<button class="uavatar" id="avatarBtn" title="${esc(authUser.name)}">${esc(initialOf(authUser.name))}</button>`;
  } else {
    slot.innerHTML = `<button class="loginbtn" id="loginBtn">Log in</button>`;
  }
}

function renderActAuth() {
  const box = $("actAuth");
  if (!box) return;
  if (authUser) {
    box.innerHTML = `<div class="auth-card"><div class="user-chip">
      <div class="uavatar">${esc(initialOf(authUser.name))}</div>
      <div class="user-meta"><b>${esc(authUser.name)}</b><span>${esc(authUser.email)}</span></div>
      <button class="logoutbtn" id="logoutBtn">Log out</button>
    </div></div>`;
    $("logoutBtn").addEventListener("click", doLogout);
    return;
  }
  const lu = lastUser();
  box.innerHTML = `<div class="auth-card">
    ${lu ? `<div class="auth-welcome">Welcome back</div>
    <div class="g-account" id="gAccountRow" role="button" tabindex="0" title="Continue as ${esc(lu.email)}">
      <span class="uavatar sm">${esc(initialOf(lu.name))}</span>
      <span class="g-acc-meta"><b>${esc(lu.name)}</b><span>${esc(lu.email)}</span></span>
      <span class="g-acc-x" id="gForget" title="Remove">✕</span>
    </div>` : ""}
    ${googleClientId ? `<div id="gsiBtn"></div>` : ""}
    ${(lu || googleClientId) ? `<div class="auth-or"><span>OR</span></div>` : ""}
    <div class="auth-tabs">
      <button data-m="login" class="${authMode === "login" ? "active" : ""}">Log in</button>
      <button data-m="signup" class="${authMode === "signup" ? "active" : ""}">Sign up</button>
    </div>
    ${authMode === "signup" ? `<input id="authName" placeholder="Your name" autocomplete="name" maxlength="60">` : ""}
    <input id="authEmail" type="email" placeholder="Email" autocomplete="email" value="${lu && authMode === "login" ? esc(lu.email) : ""}">
    <input id="authPass" type="password" placeholder="Password${authMode === "signup" ? " (min 6 characters)" : ""}" autocomplete="${authMode === "signup" ? "new-password" : "current-password"}">
    <button class="auth-go" id="authGo">${authMode === "signup" ? "Create account" : "Log in"}</button>
    <p class="auth-err" id="authErr"></p>
  </div>`;
  box.querySelectorAll(".auth-tabs button").forEach((b) =>
    b.addEventListener("click", () => { authMode = b.dataset.m; renderActAuth(); }));
  $("authGo").addEventListener("click", doAuthSubmit);
  ["authName", "authEmail", "authPass"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("keydown", (e) => { if (e.key === "Enter") doAuthSubmit(); });
  });
  const row = $("gAccountRow");
  if (row) {
    row.addEventListener("click", (e) => {
      if (e.target.id === "gForget") {
        e.stopPropagation();
        localStorage.removeItem("tm_last_user");
        renderActAuth();
        return;
      }
      authMode = "login"; renderActAuth();
      setTimeout(() => { const p = $("authPass"); if (p) p.focus(); }, 50);
    });
  }
  renderGsiButton();
}

/* ---------- Google Sign-In (GIS) ---------- */
function renderGsiButton() {
  const slot = $("gsiBtn");
  if (!slot || !googleClientId) return;
  if (window.google && google.accounts && google.accounts.id) {
    slot.innerHTML = "";
    google.accounts.id.initialize({
      client_id: googleClientId,
      callback: onGoogleCredential,
      auto_select: false,
    });
    google.accounts.id.renderButton(slot, {
      theme: "outline", size: "large", width: "100%", text: "continue_with",
    });
    return;
  }
  if (!document.querySelector('script[data-gsi]')) {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true; s.defer = true; s.dataset.gsi = "1";
    s.onload = renderGsiButton;
    document.head.appendChild(s);
  }
}

async function onGoogleCredential(resp) {
  const err = $("authErr");
  if (err) err.textContent = "Signing you in with Google…";
  try {
    const r = await fetch("/api/auth/google", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: resp.credential }) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Google sign-in failed");
    localStorage.setItem("tm_token", data.token);
    rememberUser(data.user);
    authUser = data.user;
    renderAuthSlot(); renderActAuth();
  } catch (e) {
    if (err) err.textContent = e.message;
  }
}

async function doAuthSubmit() {
  const err = $("authErr"), go = $("authGo");
  err.textContent = ""; go.disabled = true;
  try {
    const body = { email: $("authEmail").value.trim(), password: $("authPass").value };
    const path = authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    if (authMode === "signup") body.name = $("authName").value.trim();
    const r = await fetch(path, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "something went wrong");
    localStorage.setItem("tm_token", data.token);
    rememberUser(data.user);
    authUser = data.user;
    renderAuthSlot(); renderActAuth();
  } catch (e) {
    err.textContent = e.message;
  } finally {
    go.disabled = false;
  }
}

async function doLogout() {
  try { await fetch("/api/auth/logout", { method: "POST" }); } catch (e) {}
  localStorage.removeItem("tm_token");
  authUser = null;
  renderAuthSlot(); renderActAuth();
}

async function authMe() {
  const t = tmToken();
  if (!t) return;
  try {
    const r = await fetch("/api/auth/me", { headers: { Authorization: "Bearer " + t } });
    if (r.ok) authUser = (await r.json()).user;
    else localStorage.removeItem("tm_token");
  } catch (e) {}
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
  const gh = alert.github || {};
  return `<div class="card"><h5>🚨 Live incident</h5>
    <dl class="kv">
      <dt>service</dt><dd>${esc(alert.service)}</dd>
      <dt>severity</dt><dd class="alert">${esc(alert.severity)}</dd>
      ${alert.error_signature ? `<dt>signature</dt><dd>${esc(alert.error_signature)}</dd>` : ""}
      ${gh.url ? `<dt>issue</dt><dd><a href="${esc(gh.url)}" target="_blank" rel="noopener">#${esc(gh.number)} ↗</a></dd>` : ""}
    </dl>
    ${alert.logs_snippet ? `<div class="logbox">${esc(alert.logs_snippet)}</div>` : ""}</div>`;
}
function matchesCard(matches, scoreLabel) {
  if (!matches.length)
    return `<div class="card"><h5>🧠 Memory search</h5>
      <p>No similar past incidents in memory yet — the recommendation below says so honestly instead of guessing. Resolve this incident and it becomes the first memory of its kind.</p></div>`;
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

/* ---------- profile / activity panel ---------- */
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
    try {
      const s = await api("/api/db/stats");
      $("memMttr").textContent = s.avg_mttr_minutes != null ? Math.round(s.avg_mttr_minutes) + " min" : "—";
      $("memSvc").textContent = Object.keys(s.by_service || {}).length || "—";
      $("memDb").textContent = `sqlite · ${s.total_incidents}`;
    } catch (e) { $("memDb").textContent = "—"; }
    const g = h.github || {};
    $("ghPillText").textContent = g.repo
      ? `${g.repo}${g.last_sync_at ? " · synced " + relTime(g.last_sync_at) : " · syncing…"}`
      : "no repo";
  } catch (e) { /* offline */ }
}
function relTime(iso) {
  try {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  } catch (e) { return ""; }
}

/* ---------- welcome / new chat ---------- */
function welcome() {
  $("chat").innerHTML = "";
  $("chips").style.display = "";
  const body = addAgentMsg();
  say(body, `<p>👋 I'm <b>Trace</b> — I turn your repo's GitHub issues into organizational memory.</p>
    <p>Open issues are synced as live incidents. Pick one below (or describe your own) and I'll search <b>past incidents</b>, show what fixed them, and recommend investigation steps — as evidence-backed hypotheses, never false certainty. When you resolve it, I'll remember the post-mortem, so the next similar issue starts smarter.</p>`);
}
function renderChips() {
  const open = openIncidents.filter((i) => i.outcome === "open").slice(0, 8);
  if (!open.length) {
    $("chips").innerHTML = `<span class="chip-hint">No open issues synced yet — check Settings → Sync now, or describe an incident below.</span>`;
    return;
  }
  $("chips").innerHTML = open.map((i, idx) =>
    `<button class="chip" data-i="${idx}"><span class="sevtag">${esc((i.severity || "medium").toUpperCase())}</span>${esc(i.title)}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => investigate(alertFromIncident(open[+c.dataset.i]))));
}
function alertFromIncident(i) {
  return {
    title: i.title, service: i.service || "unknown",
    severity: i.severity || "medium",
    error_signature: "", symptoms: [i.title],
    logs_snippet: "", deployment: {},
    github: i.github || {},
  };
}
async function loadIncidents() {
  try {
    const d = await api("/api/incidents");
    openIncidents = d.incidents || [];
  } catch (e) { openIncidents = []; }
  renderChips();
}

/* ---------- settings ---------- */
function setModal(open) {
  $("setModal").classList.toggle("open", open);
  $("setScrim").classList.toggle("show", open);
  if (open) loadSettings();
}
async function loadSettings() {
  try {
    const s = await api("/api/settings");
    $("setRepo").value = s.github_repo || "";
    $("setSyncMin").value = s.sync_minutes || 5;
    $("setLastSync").textContent = s.last_sync_at
      ? new Date(s.last_sync_at).toLocaleString() : "never";
    $("setTokenBadge").textContent = s.github_token_configured ? "Connected" : "Not set";
    $("setTokenBadge").classList.toggle("on", !!s.github_token_configured);
    $("setBackendBadge").textContent = s.memory_backend || "—";
    $("setBankDesc").textContent = s.hindsight_bank
      ? `Hindsight bank "${s.hindsight_bank}" — every resolved incident is retained here.`
      : "Local TF-IDF memory — set HINDSIGHT_API_KEY for durable cloud memory.";
    $("setMemCount").textContent = s.incidents_remembered ?? "—";
    $("setGroqBadge").textContent = s.groq_configured ? "Connected" : "Not set";
    $("setGroqBadge").classList.toggle("on", !!s.groq_configured);
  } catch (e) { /* offline */ }
}
async function saveSettings() {
  const repo = $("setRepo").value.trim();
  const mins = parseInt($("setSyncMin").value, 10);
  const btn = $("setSaveBtn");
  const payload = {};
  if (repo) payload.github_repo = repo;
  if (mins >= 1 && mins <= 1440) payload.sync_minutes = mins;
  btn.disabled = true; btn.textContent = "Saving…";
  const res = await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  btn.disabled = false; btn.textContent = "Save";
  if (res.error) { btn.textContent = res.error; setTimeout(() => btn.textContent = "Save", 1800); return; }
  loadSettings(); refreshMemory(); loadIncidents();
}

/* ---------- composer ---------- */
const WAVE_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><rect x="3.4" y="10" width="2.2" height="4" rx="1.1"/><rect x="7.4" y="7" width="2.2" height="10" rx="1.1"/><rect x="11" y="4" width="2.2" height="16" rx="1.1"/><rect x="14.6" y="8" width="2.2" height="8" rx="1.1"/><rect x="18.2" y="10.5" width="2.2" height="3" rx="1.1"/></svg>';
const ARROW_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
function refreshSendBtn() {
  const has = $("input").value.trim().length > 0;
  const btn = $("sendBtn");
  btn.innerHTML = has ? ARROW_ICON : WAVE_ICON;
  btn.classList.toggle("send", has);
  btn.title = has ? "Send" : "Voice input";
  btn.setAttribute("aria-label", has ? "Send" : "Voice input");
}
function send() {
  const inp = $("input");
  const text = inp.value.trim();
  if (!text || busy) return;
  inp.value = ""; inp.style.height = "auto"; refreshSendBtn();
  investigate(alertFromText(text), text);
}
let recog = null, listening = false;
function toggleVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  if (listening) { try { recog.stop(); } catch (e) {} return; }
  const inp = $("input"), mic = $("micBtn");
  recog = new SR();
  recog.lang = "en-US"; recog.interimResults = false; recog.maxAlternatives = 1;
  recog.onresult = (e) => {
    const t = e.results[0][0].transcript;
    inp.value = (inp.value ? inp.value + " " : "") + t;
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    inp.focus();
  };
  const done = () => { listening = false; mic.classList.remove("live"); };
  recog.onend = done; recog.onerror = done;
  try { recog.start(); listening = true; mic.classList.add("live"); } catch (e) { done(); }
}
document.addEventListener("DOMContentLoaded", async () => {
  welcome();
  loadIncidents();
  refreshMemory();
  try {
    const s = await api("/api/settings");
    googleClientId = s.google_client_id || "";
  } catch (e) {}
  await authMe();
  renderAuthSlot(); renderActAuth();
  setInterval(refreshMemory, 60000);
  const inp = $("input");
  inp.addEventListener("input", () => {
    inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 160) + "px";
    refreshSendBtn();
  });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("sendBtn").addEventListener("click", () => {
    if ($("input").value.trim()) send(); else toggleVoice();
  });
  $("micBtn").addEventListener("click", toggleVoice);
  if (!window.SpeechRecognition && !window.webkitSpeechRecognition) $("micBtn").classList.add("hidden");
  $("plusBtn").addEventListener("click", () => { if (!busy) $("newChatBtn").click(); });
  refreshSendBtn();
  $("newChatBtn").addEventListener("click", () => {
    if (busy) return;
    welcome(); loadIncidents();
    document.body.classList.remove("side-open");
  });
  $("burger").addEventListener("click", () => document.body.classList.toggle("side-open"));
  $("scrim").addEventListener("click", () => document.body.classList.remove("side-open"));
  $("settingsBtn").addEventListener("click", () => setModal(true));
  $("authSlot").addEventListener("click", () => { renderActAuth(); renderActivity(); setActPanel(true); });
  $("actClose").addEventListener("click", () => setActPanel(false));
  $("actScrim").addEventListener("click", () => setActPanel(false));
  $("actTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    actFilter = b.dataset.f;
    document.querySelectorAll("#actTabs button").forEach((x) => x.classList.toggle("active", x === b));
    renderActivity();
  });
  $("ghPill").addEventListener("click", () => setModal(true));
  $("setClose").addEventListener("click", () => setModal(false));
  $("setScrim").addEventListener("click", () => setModal(false));
  $("setSaveBtn").addEventListener("click", saveSettings);
  $("setSyncNow").addEventListener("click", async () => {
    const b = $("setSyncNow");
    b.disabled = true; b.textContent = "Syncing…";
    await api("/api/integrations/github/sync", { method: "POST" });
    b.disabled = false; b.textContent = "Sync now";
    loadSettings(); refreshMemory(); loadIncidents();
  });
  $("setClearDb").addEventListener("click", async () => {
    const b = $("setClearDb");
    if (b.dataset.armed) {
      b.disabled = true; b.textContent = "Clearing…";
      await api("/api/settings/clear-db", { method: "POST" });
      delete b.dataset.armed; b.disabled = false; b.textContent = "Clear";
      loadSettings(); refreshMemory(); loadIncidents(); welcome();
    } else {
      b.dataset.armed = "1"; b.textContent = "Click again to confirm";
      setTimeout(() => { delete b.dataset.armed; b.textContent = "Clear"; }, 3000);
    }
  });
});
