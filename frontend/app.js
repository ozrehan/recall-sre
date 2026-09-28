/* TraceMind — ChatGPT-style chat logic */
const $ = (id) => document.getElementById(id);

/* black doodle siren icon (replaces the red siren emoji everywhere) */
const SIREN_SVG = `<svg class="ico-siren" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5v2.5"/><path d="M5.8 4.8l1.7 1.7"/><path d="M18.2 4.8l-1.7 1.7"/><path d="M3.5 11H6"/><path d="M20.5 11H18"/><path d="M8 15v-4.5a4 4 0 0 1 8 0V15"/><path d="M10.6 12.6a2.6 2.6 0 0 1 1.6-2.6"/><path d="M5.5 15h13l1.5 4.5H4z"/></svg>`;

/* black doodle brain icon (replaces the color brain emoji everywhere) */
const BRAIN_IMG = `<img class="ico-img" src="icons/memory.png" alt="Memory" width="22" height="22">`;

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
