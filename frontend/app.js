/* TraceMind — ChatGPT-style chat logic */
const $ = (id) => document.getElementById(id);

/* black doodle siren icon (replaces the red siren emoji everywhere) */
const SIREN_SVG = `<svg class="ico-siren" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5v2.5"/><path d="M5.8 4.8l1.7 1.7"/><path d="M18.2 4.8l-1.7 1.7"/><path d="M3.5 11H6"/><path d="M20.5 11H18"/><path d="M8 15v-4.5a4 4 0 0 1 8 0V15"/><path d="M10.6 12.6a2.6 2.6 0 0 1 1.6-2.6"/><path d="M5.5 15h13l1.5 4.5H4z"/></svg>`;

/* black doodle brain icon (replaces the color brain emoji everywhere) */
const BRAIN_IMG = `<img class="ico-img" src="data:image/png;base64,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" alt="Memory" width="22" height="22">`;

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
    slot.innerHTML = `<button class="uavatar trace-avatar" id="avatarBtn" title="${esc(authUser.name)} — profile & activity"><video src="profile.mp4" autoplay muted loop playsinline></video></button>`;
  } else {
    slot.innerHTML = `<button class="loginbtn" id="loginBtn">Log in</button>`;
  }
}

function renderActAuth() {
  const box = $("actAuth");
  if (!box) return;
  const panel = $("actPanel");
  if (authUser) {
    panel.classList.remove("auth-mode");
    box.innerHTML = `<div class="auth-card"><div class="user-chip">
      <div class="uavatar">${esc(initialOf(authUser.name))}</div>
      <div class="user-meta"><b>${esc(authUser.name)}</b><span>${esc(authUser.email)}</span></div>
      <button class="logoutbtn" id="logoutBtn">Log out</button>
    </div></div>`;
    $("logoutBtn").addEventListener("click", doLogout);
    return;
  }
  const lu = lastUser();
  panel.classList.add("auth-mode");
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
  renderGsiButton("gsiBtn");
}

/* ---------- Google Sign-In (GIS) ---------- */
function renderGsiButton(slotId) {
  const slot = $(slotId);
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
    s.onload = () => { renderGsiButton("gsiBtn"); renderGsiButton("gsiBtnSheet"); };
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
    onAuthSuccess(data);
  } catch (e) {
    if (err) err.textContent = e.message;
  }
}

async function submitAuth(pfx, mode) {
  const err = $(pfx + "Err"), go = $(pfx + "Go");
  err.textContent = ""; go.disabled = true;
  try {
    const body = { email: $(pfx + "Email").value.trim(), password: $(pfx + "Pass").value };
    const path = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    if (mode === "signup") body.name = $(pfx + "Name").value.trim();
    const r = await fetch(path, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "something went wrong");
    onAuthSuccess(data);
  } catch (e) {
    err.textContent = e.message;
  } finally {
    go.disabled = false;
  }
}

function onAuthSuccess(data) {
  localStorage.setItem("tm_token", data.token);
  rememberUser(data.user);
  authUser = data.user;
  renderAuthSlot(); renderActAuth(); closeLoginSheet();
}

async function doAuthSubmit() { submitAuth("auth", authMode); }

/* ---------- login bottom sheet: pops up on site open, like ChatGPT ---------- */
let sheetMode = "login";
function openLoginSheet() {
  renderLoginSheet();
  $("loginSheet").classList.add("open");
  $("sheetScrim").classList.add("show");
}
function closeLoginSheet() {
  $("loginSheet").classList.remove("open");
  $("sheetScrim").classList.remove("show");
  try { sessionStorage.setItem("tm_sheet_off", "1"); } catch (e) {}
}
function renderLoginSheet() {
  const box = $("loginSheet");
  const lu = lastUser();
  box.innerHTML = `
    <div class="sheet-handle"></div>
    <button class="sheet-close" id="sheetClose" aria-label="Close">✕</button>
    <div class="sheet-title">${lu ? "Welcome back" : "Log in to TraceMind"}</div>
    <div class="sheet-sub">${lu ? "Choose an account to continue." : "Choose how you'd like to continue."}</div>
    ${lu ? `<div class="g-account" id="sheetAccount" role="button" tabindex="0">
      <span class="uavatar sm">${esc(initialOf(lu.name))}</span>
      <span class="g-acc-meta"><b>${esc(lu.name)}</b><span>${esc(lu.email)}</span></span>
      <span class="g-acc-x" id="sheetForget" title="Remove">✕</span>
    </div>` : ""}
    ${googleClientId ? `<div id="gsiBtnSheet"></div>` : ""}
    ${(lu || googleClientId) ? `<div class="auth-or"><span>OR</span></div>` : ""}
    <div class="auth-tabs">
      <button data-m="login" class="${sheetMode === "login" ? "active" : ""}">Log in</button>
      <button data-m="signup" class="${sheetMode === "signup" ? "active" : ""}">Sign up</button>
    </div>
    ${sheetMode === "signup" ? `<input id="shName" placeholder="Your name" autocomplete="name" maxlength="60">` : ""}
    <input id="shEmail" type="email" placeholder="Email" autocomplete="email" value="${lu && sheetMode === "login" ? esc(lu.email) : ""}">
    <input id="shPass" type="password" placeholder="Password${sheetMode === "signup" ? " (min 6 characters)" : ""}" autocomplete="${sheetMode === "signup" ? "new-password" : "current-password"}">
    <button class="auth-go" id="shGo">${sheetMode === "signup" ? "Create account" : "Log in"}</button>
    <p class="auth-err" id="shErr"></p>`;
  $("sheetClose").addEventListener("click", closeLoginSheet);
  box.querySelectorAll(".auth-tabs button").forEach((b) =>
    b.addEventListener("click", () => { sheetMode = b.dataset.m; renderLoginSheet(); }));
  $("shGo").addEventListener("click", () => submitAuth("sh", sheetMode));
  ["shName", "shEmail", "shPass"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth("sh", sheetMode); });
  });
  const row = $("sheetAccount");
  if (row) row.addEventListener("click", (e) => {
    if (e.target.id === "sheetForget") {
      e.stopPropagation();
      localStorage.removeItem("tm_last_user");
      renderLoginSheet();
      return;
    }
    sheetMode = "login"; renderLoginSheet();
    setTimeout(() => { const p = $("shPass"); if (p) p.focus(); }, 80);
  });
  renderGsiButton("gsiBtnSheet");
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

function addUserMsg(text, isHtml = false) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${isHtml ? text : esc(text)}</div>`;
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
  return `<div class="card"><h5>${SIREN_SVG} Live incident</h5>
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
    return `<div class="card"><h5>${BRAIN_IMG} Memory search</h5>
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
  return `<div class="card"><h5>${BRAIN_IMG} Memory search — ranked by ${esc(scoreLabel)}</h5>${cards}</div>`;
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
    wrap.innerHTML = `<div class="learned-ok">${BRAIN_IMG} <b>Learned.</b> Stored as <b>${esc(res.id)}</b> — memory now holds <b>${res.memory_size}</b> incidents. Fire a similar incident and watch the agent recall this one.</div>`;
    scrollBottom(); refreshMemory(); saveTranscript(); onDone && onDone(res);
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
  const ts = Date.now();
  const items = getActivity();
  items.unshift({ type, title, desc, ts });
  try { localStorage.setItem(ACT_KEY, JSON.stringify(items.slice(0, 100))); } catch (e) {}
  renderActivity();
  renderRecents();
  return ts;
}
function fmtTime(ts) {
  const d = new Date(ts);
  let h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "pm" : "am"; h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}
const ACT_ICON = { fired: SIREN_SVG, resolved: "✓" };
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

/* ---------- GitHub + Plugins panels ---------- */
function setPanel(panelId, scrimId, open) {
  $(panelId).classList.toggle("open", open);
  $(scrimId).classList.toggle("show", open);
}
const tmApi = {
  async get(p) { const r = await fetch(p); return r.json(); },
  async post(p, b) {
    const r = await fetch(p, {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(b || {})});
    return r.json();
  },
};
async function refreshGithubPanel() {
  try {
    const st = await tmApi.get("/api/plugins/status");
    $("ghRepoLine").textContent = st.github_repo || "—";
    $("ghRepoLink").href = st.repo_url || "#";
    $("ghStatusText").textContent = "Connected — watching on cloud";
    const sn = st.sentinel || {};
    $("ghScanLine").textContent = "Last scan: " +
      (sn.last_run ? new Date(sn.last_run).toLocaleString() : "never") +
      (sn.enabled ? "" : " (paused)");
    const res = sn.last_result;
    const box = $("ghFindings");
    if (res && res.problems && res.problems.length) {
      box.innerHTML = res.problems.map((p) =>
        `<div class="finding"><b>${esc(p.title)}</b>`
        + (p.run_id ? "" : "") + `</div>`).join("");
    } else if (res && !res.error) {
      box.innerHTML = `<p class="plug-sub">No problems found. CI is green.</p>`;
    } else if (res && res.error) {
      box.innerHTML = `<p class="plug-sub">Scan error: ${esc(res.error)}</p>`;
    } else {
      box.innerHTML = "";
    }
  } catch (e) {
    $("ghStatusText").textContent = "Could not reach server";
  }
}
async function refreshPluginsPanel() {
  try {
    const st = await tmApi.get("/api/plugins/status");
    $("plugList").innerHTML = st.plugins.map((p) => `
      <div class="plug-card">
        <div class="plug-head"><b>${esc(p.name)}</b>
          <label class="switch"><input type="checkbox" data-plug="${p.id}"
            ${p.enabled ? "checked" : ""}><span></span></label>
        </div>
        <p class="plug-sub">${esc(p.description)}</p>
      </div>`).join("");
    document.querySelectorAll("#plugList input[data-plug]").forEach((el) => {
      el.addEventListener("change", async () => {
        await tmApi.post("/api/plugins/toggle/" + el.dataset.plug,
                       {enabled: el.checked});
        refreshGithubPanel();
      });
    });
    const mins = String((st.sentinel || {}).interval_minutes || 15);
    $("scanInterval").value = ["5","15","30","60"].includes(mins) ? mins : "15";
  } catch (e) { /* offline */ }
}
function bindPanels() {
  $("navGithub").addEventListener("click", () => {
    setPanel("ghPanel", "ghScrim", true); refreshGithubPanel();
  });
  $("navPlugins").addEventListener("click", () => {
    setPanel("plugPanel", "plugScrim", true); refreshPluginsPanel();
  });
  $("ghClose").addEventListener("click", () => setPanel("ghPanel", "ghScrim", false));
  $("ghScrim").addEventListener("click", () => setPanel("ghPanel", "ghScrim", false));
  $("plugClose").addEventListener("click", () => setPanel("plugPanel", "plugScrim", false));
  $("plugScrim").addEventListener("click", () => setPanel("plugPanel", "plugScrim", false));
  $("ghConnectBtn").addEventListener("click", async () => {
    const repo = $("ghRepoInput").value.trim();
    if (!repo) return;
    $("ghConnectBtn").textContent = "…";
    const r = await tmApi.post("/api/settings", {github_repo: repo});
    $("ghConnectBtn").textContent = "Connect";
    if (r.github_repo) { $("ghRepoInput").value = ""; refreshGithubPanel(); }
    else alert(r.error || "Could not connect");
  });
  $("ghScanBtn").addEventListener("click", async () => {
    $("ghScanBtn").textContent = "Scanning…";
    await tmApi.post("/api/plugins/scan", {});
    $("ghScanBtn").textContent = "Scan now";
    refreshGithubPanel();
  });
  $("scanIntervalBtn").addEventListener("click", async () => {
    await tmApi.post("/api/plugins/interval",
                   {minutes: parseInt($("scanInterval").value, 10)});
    refreshPluginsPanel();
  });
}
if (document.readyState === "loading")
  document.addEventListener("DOMContentLoaded", bindPanels);
else bindPanels();

/* ---------- chat transcripts: reopen previous chats ---------- */
let currentChatTs = null;
const CHAT_PREFIX = "tm_chat_";
function saveTranscript() {
  if (!currentChatTs) return;
  try {
    const t = document.querySelector(".thread");
    if (!t) return;
    const msgs = [];
    t.querySelectorAll(":scope > .msg").forEach((m) => {
      if (m.classList.contains("user")) {
        const b = m.querySelector(".bubble");
        if (b) msgs.push({ who: "u", html: b.innerHTML });
      } else if (m.classList.contains("agent")) {
        const b = m.querySelector(".body");
        if (b) msgs.push({ who: "a", html: b.innerHTML });
      }
    });
    if (!msgs.length) return;
    localStorage.setItem(CHAT_PREFIX + currentChatTs, JSON.stringify({ ts: currentChatTs, msgs }));
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(CHAT_PREFIX)) keys.push(k);
    }
    keys.sort().reverse();
    keys.slice(20).forEach((k) => { try { localStorage.removeItem(k); } catch (e) {} });
  } catch (e) {
    try {
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(CHAT_PREFIX)) keys.push(k);
      }
      keys.sort();
      if (keys.length) localStorage.removeItem(keys[0]);
    } catch (e2) {}
  }
}
function getTranscript(ts) {
  try { return JSON.parse(localStorage.getItem(CHAT_PREFIX + ts) || "null"); } catch (e) { return null; }
}
function openChat(ts) {
  const tr = getTranscript(ts);
  const a = getActivity().find((x) => x.ts === ts);
  if (!tr) {
    if (a && !busy) investigate(alertFromText(a.title), a.title); // legacy: no saved transcript, re-fire
    document.body.classList.remove("side-open");
    return;
  }
  saveTranscript();
  busy = false;
  currentChatTs = ts;
  $("chat").innerHTML = "";
  $("chips").style.display = "none";
  const t = thread();
  const banner = document.createElement("div");
  banner.className = "viewing-banner";
  banner.textContent = `Viewing past investigation — ${new Date(ts).toLocaleString()}`;
  t.appendChild(banner);
  tr.msgs.forEach((m) => {
    const el = document.createElement("div");
    if (m.who === "u") {
      el.className = "msg user";
      el.innerHTML = `<div class="bubble">${m.html}</div>`;
    } else {
      el.className = "msg agent";
      el.innerHTML = `<div class="avatar"><img src="logo-icon.png" alt="TM"></div><div class="body">${m.html}</div>`;
      el.querySelectorAll("[data-act=save]").forEach((b) => {
        b.disabled = true;
        b.textContent = "Stored earlier — view only";
      });
      el.querySelectorAll("textarea, input").forEach((f) => { f.disabled = true; });
    }
    t.appendChild(el);
  });
  scrollBottom();
  document.body.classList.remove("side-open");
}

/* ---------- flow ---------- */
async function investigate(alert, userLabel) {
  if (busy) return; busy = true;
  $("chips").style.display = "none";
  if (userLabel) addUserMsg(userLabel);
  else addUserMsg(`${SIREN_SVG} ${esc(alert.title)} — ${esc(alert.service)} · ${esc(alert.severity)}`, true);
  currentChatTs = logActivity("fired", alert.title, `${alert.service} · ${alert.severity} — investigation started`);
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
  saveTranscript();
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

/* ---------- sidebar: recents + pinned ---------- */
const PIN_KEY = "tm_pinned";
const getPinned = () => { try { return JSON.parse(localStorage.getItem(PIN_KEY) || "[]"); } catch (e) { return []; } };
function togglePin(ts) {
  let p = getPinned();
  p = p.includes(ts) ? p.filter((x) => x !== ts) : [ts, ...p].slice(0, 30);
  try { localStorage.setItem(PIN_KEY, JSON.stringify(p)); } catch (e) {}
  renderRecents();
}
function renderRecents() {
  const pl = $("pinnedList"), rl = $("recentsList");
  if (!pl || !rl) return;
  const q = (($("sbSearchInput") || {}).value || "").toLowerCase().trim();
  const pinned = getPinned();
  const items = getActivity().filter((a) => a.type === "fired");
  const match = (a) => !q || (a.title || "").toLowerCase().includes(q);
  const row = (a, isPinned) => `
    <div class="sb-row" data-ts="${a.ts}">
      <button class="sb-row-main" title="${esc(a.title)}"><span class="sb-row-ico">💬</span><span class="sb-row-t">${esc(a.title)}</span></button>
      <button class="sb-pin" title="${isPinned ? "Unpin" : "Pin"}">${isPinned ? "📌" : "📍"}</button>
    </div>`;
  const pinnedItems = items.filter((a) => pinned.includes(a.ts) && match(a));
  const recentItems = items.filter((a) => !pinned.includes(a.ts) && match(a)).slice(0, 25);
  pl.innerHTML = pinnedItems.length ? pinnedItems.map((a) => row(a, true)).join("")
    : `<div class="sb-empty">Nothing pinned yet.</div>`;
  rl.innerHTML = recentItems.length ? recentItems.map((a) => row(a, false)).join("")
    : `<div class="sb-empty">No incidents yet.<br>Fire one from the chat.</div>`;
  pl.querySelectorAll(".sb-row").forEach(wireSbRow);
  rl.querySelectorAll(".sb-row").forEach(wireSbRow);
}
function wireSbRow(r) {
  const ts = +r.dataset.ts;
  r.querySelector(".sb-row-main").addEventListener("click", () => {
    if (busy) return;
    openChat(ts);
  });
  r.querySelector(".sb-pin").addEventListener("click", (e) => { e.stopPropagation(); togglePin(ts); });
}

/* ---------- sidebar info modals ---------- */
function openInfo(title, bodyHTML) {
  $("infoTitle").textContent = title;
  $("infoBody").innerHTML = bodyHTML || `<p class="info-hint">Loading…</p>`;
  $("infoModal").classList.add("open");
  $("infoScrim").classList.add("show");
}
function closeInfo() {
  $("infoModal").classList.remove("open");
  $("infoScrim").classList.remove("show");
}
async function openIncidentsModal() {
  openInfo("Incidents");
  try {
    const d = await api("/api/incidents");
    const list = d.incidents || [];
    $("infoBody").innerHTML = list.length ? list.map((i, idx) => `
      <button class="info-row" data-i="${idx}">
        <span class="sevtag">${esc((i.severity || "medium").toUpperCase())}</span>
        <span class="info-row-t">${esc(i.title)}</span>
        <span class="info-row-s">${esc(i.service || "")}</span>
      </button>`).join("")
      : `<p class="info-hint">No open incidents right now. They sync from GitHub issues — check Scheduled → Sync now.</p>`;
    $("infoBody").querySelectorAll(".info-row").forEach((b) =>
      b.addEventListener("click", () => {
        closeInfo();
        document.body.classList.remove("side-open");
        investigate(alertFromIncident(list[+b.dataset.i]));
      }));
  } catch (e) { $("infoBody").innerHTML = `<p class="info-hint">Couldn't load incidents.</p>`; }
}
async function openMemoryModal() {
  openInfo("Memory");
  try {
    const [h, s] = await Promise.all([api("/api/health"), api("/api/db/stats").catch(() => null)]);
    $("infoBody").innerHTML = `
      <div class="membox">
        <div class="memrow"><span>incidents remembered</span><b>${h.memory_size ?? "—"}</b></div>
        <div class="memrow"><span>semantic backend</span><b>${esc(h.backend || "—")}</b></div>
        <div class="memrow"><span>database</span><b>sqlite · ${s ? s.total_incidents : "—"}</b></div>
        <div class="memrow"><span>avg resolution</span><b>${s && s.avg_mttr_minutes != null ? Math.round(s.avg_mttr_minutes) + " min" : "—"}</b></div>
        <div class="memrow"><span>services</span><b>${s ? (Object.keys(s.by_service || {}).length || "—") : "—"}</b></div>
      </div>
      <p class="info-hint">Every resolved incident is retained — in the database and in semantic memory — so the next similar incident starts smarter.</p>`;
  } catch (e) { $("infoBody").innerHTML = `<p class="info-hint">Couldn't load memory stats.</p>`; }
}
async function openDbModal() {
  openInfo("Database");
  try {
    const d = await api("/api/db/incidents?limit=50");
    const list = d.incidents || [];
    $("infoBody").innerHTML = (list.length ? `<p class="info-hint">${d.total} incidents stored locally.</p>` : "") +
      (list.length ? list.map((i) => {
        const resolved = !!(i.resolved_at || i.status === "resolved");
        return `<div class="info-row" style="cursor:default">
          <span class="sevtag">${esc((i.severity || "medium").toUpperCase())}</span>
          <span class="info-row-t">${esc(i.title || i.id)}</span>
          <span class="info-row-s">${resolved ? "✓ resolved" : "● open"}</span>
        </div>`;
      }).join("") : `<p class="info-hint">Database is empty. Sync from GitHub to fill it.</p>`);
  } catch (e) { $("infoBody").innerHTML = `<p class="info-hint">Couldn't load the database.</p>`; }
}
async function openScheduledModal() {
  openInfo("Scheduled");
  try {
    const s = await api("/api/settings");
    $("infoBody").innerHTML = `
      <div class="info-kv"><span>repository</span><b>${esc(s.github_repo || "—")}</b></div>
      <div class="info-kv"><span>sync every</span><b>${s.sync_minutes || 5} min</b></div>
      <div class="info-kv"><span>last sync</span><b>${s.last_sync_at ? new Date(s.last_sync_at).toLocaleString() : "never"}</b></div>
      <div class="info-kv"><span>token</span><b>${s.github_token_configured ? "connected" : "not set"}</b></div>
      <button class="btn wide" id="infoSyncNow">Sync now</button>
      <p class="info-hint">TraceMind polls the repo on this schedule. New and closed issues sync automatically — closed ones become resolved incidents.</p>`;
    $("infoSyncNow").addEventListener("click", async () => {
      const b = $("infoSyncNow");
      b.disabled = true; b.textContent = "Syncing…";
      await api("/api/integrations/github/sync", { method: "POST" });
      b.disabled = false; b.textContent = "Sync now";
      loadIncidents(); openScheduledModal();
    });
  } catch (e) { $("infoBody").innerHTML = `<p class="info-hint">Couldn't load schedule info.</p>`; }
}

/* ---------- memory (cached for sidebar modals) ---------- */
let memCache = {};
async function refreshMemory() {
  try {
    const h = await api("/api/health");
    memCache = { backend: h.backend, memory_size: h.memory_size, github: h.github || {} };
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
  currentChatTs = null;
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
  renderAuthSlot(); renderActAuth(); renderRecents();
  let sheetOff = false;
  try { sheetOff = !!sessionStorage.getItem("tm_sheet_off"); } catch (e) {}
  if (!authUser && !sheetOff) openLoginSheet();
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
    saveTranscript();
    welcome(); loadIncidents();
    document.body.classList.remove("side-open");
  });
  $("burger").addEventListener("click", () => document.body.classList.toggle("side-open"));
  $("scrim").addEventListener("click", () => document.body.classList.remove("side-open"));
  $("navIncidents").addEventListener("click", () => openIncidentsModal());
  $("navMemory").addEventListener("click", () => openMemoryModal());
  $("navDb").addEventListener("click", () => openDbModal());
  $("navScheduled").addEventListener("click", () => openScheduledModal());
  $("navSettings").addEventListener("click", () => setModal(true));
  $("infoClose").addEventListener("click", closeInfo);
  $("infoScrim").addEventListener("click", closeInfo);
  $("sbSearchBtn").addEventListener("click", () => {
    const box = $("sbSearchBox");
    box.hidden = !box.hidden;
    if (!box.hidden) $("sbSearchInput").focus();
  });
  $("sbSearchInput").addEventListener("input", renderRecents);
  $("authSlot").addEventListener("click", () => {
    if (authUser) { renderActAuth(); renderActivity(); setActPanel(true); }
    else openLoginSheet();
  });
  $("sheetScrim").addEventListener("click", closeLoginSheet);
  $("actClose").addEventListener("click", () => setActPanel(false));
  $("actScrim").addEventListener("click", () => setActPanel(false));
  $("actTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    actFilter = b.dataset.f;
    document.querySelectorAll("#actTabs button").forEach((x) => x.classList.toggle("active", x === b));
    renderActivity();
  });
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
