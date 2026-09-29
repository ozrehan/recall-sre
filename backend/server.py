#!/usr/bin/env python3
"""TraceMind server — stdlib only, zero dependencies.

Real incident pipeline (no demo data):

  GitHub Issues (connected repo) ──sync──> SQLite ──retain──> Hindsight
        │ new issue = new incident          │ db of record      │ semantic memory
        │ closed issue = resolved + post-mortem learned

Serves the frontend dashboard and exposes the agent API:

  GET  /api/health              -> {ok, backend, memory_size, github{...}}
  GET  /api/incidents           -> real incidents from the database (open first)
  POST /api/investigate         -> {alert} -> {incident, matches, recommendation}
  POST /api/resolve             -> {draft..., root_cause, fix, ...} -> {id, memory_size}
  GET  /api/memory              -> {backend, size, recent:[...]}
  GET  /api/integrations/github -> {repo, last_sync_at, synced, open, ...}
  POST /api/integrations/github/sync -> run a sync pass now

Environment:
  GITHUB_REPO        repo to watch, e.g. owner/name (default ozrehan/recall-sre)
  GITHUB_TOKEN       optional: private repos + post recommendations as comments
  HINDSIGHT_URL / HINDSIGHT_API_KEY  semantic memory (Hindsight Cloud)
  HINDSIGHT_BANK_ID  memory bank (default incident-memory-prod)
  GROQ_API_KEY       optional briefing synthesizer
  DB_PATH            sqlite file (default backend/data/tracemind.db)
  TURSO_DATABASE_URL optional: libsql:// URL for a Turso database — when set,
                     ALL data (users, logins, incidents) lives in Turso and
                     survives Render's ephemeral filesystem across deploys
  TURSO_AUTH_TOKEN   auth token for the Turso database
  GITHUB_SYNC_MINUTES poll interval (default 5)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent.core import IncidentAgent
from backend import auth as auth_mod
from backend.integrations import sync as gh_sync
from backend.plugins import (
    is_enabled as _plugin_enabled,
    list_plugins as _list_plugins,
    set_enabled as _set_plugin_enabled,
    set_setting as _set_plugin_setting,
)
from backend.plugins import sentinel as _sentinel
from backend.plugins import autofix as _autofix
from backend.plugins import github_api as _gh_api
from backend.integrations import github_issues as gh_api
from backend.memory.db import IncidentDB, _db_label
from backend.memory.hybrid_store import HybridMemoryStore
from backend.memory.local_store import LocalMemoryStore

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(HERE, "..", "frontend")


def _oauth_dbg(msg: str) -> None:
    """Temporary OAuth callback diagnostics (safe: no tokens/codes logged)."""
    try:
        with open(os.path.join(FRONTEND_DIR, "oauth-debug.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    + " " + msg[:200] + "\n")
    except Exception:
        pass


# One-time login codes: the OAuth callback redirects with ?code=... instead
# of a raw token, so a copied/shared URL can never carry a live login to
# another phone. Single use, 2-minute expiry.
_OAUTH_CODES: dict = {}
_OAUTH_CODES_LOCK = threading.Lock()


def _issue_oauth_code(token: str) -> str:
    code = secrets.token_urlsafe(24)
    now = time.time()
    with _OAUTH_CODES_LOCK:
        for k in [k for k, (_, exp) in _OAUTH_CODES.items() if exp < now]:
            del _OAUTH_CODES[k]
        _OAUTH_CODES[code] = (token, now + 120)
    return code


def _consume_oauth_code(code: str):
    with _OAUTH_CODES_LOCK:
        item = _OAUTH_CODES.pop(code or "", None)
    if not item:
        return None
    token, exp = item
    return token if exp >= time.time() else None
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "data", "tracemind.db"))

MIME = {
    ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
}

CLOUD_URL = "https://api.hindsight.vectorize.io"
BANK_ID = os.environ.get("HINDSIGHT_BANK_ID", "incident-memory-prod")
GITHUB_REPO = gh_api.env_repo()
GITHUB_TOKEN = gh_api.env_token()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
SYNC_MINUTES = int(os.environ.get("GITHUB_SYNC_MINUTES", "5") or 5)
# Admin dashboard: comma-separated emails that may view site-wide stats.
ADMIN_EMAILS = {e.strip().lower()
                for e in os.environ.get("ADMIN_EMAILS", "").split(",")
                if e.strip()}


def build_memory():
    """Semantic recall layer + SQLite database of record, as one store."""
    backend_name = "local"
    try:
        from backend.memory.hindsight_store import HindsightMemoryStore
        url = os.environ.get("HINDSIGHT_URL")
        key = os.environ.get("HINDSIGHT_API_KEY")
        if key and not url:
            url = CLOUD_URL  # API key alone implies Hindsight Cloud
        if url or key:
            semantic = HindsightMemoryStore(url=url or CLOUD_URL,
                                            api_key=key, bank_id=BANK_ID)
            backend_name = "hindsight"
            return HybridMemoryStore(semantic, DB_PATH), backend_name
    except Exception as e:  # SDK missing / unreachable -> fall back
        print(f"[memory] hindsight unavailable ({e}); using local store")
    return HybridMemoryStore(LocalMemoryStore(), DB_PATH), backend_name


def build_llm():
    """Optional Groq-backed briefing synthesizer (GROQ_API_KEY)."""
    try:
        from backend.llm.groq import GroqBriefing
        key = os.environ.get("GROQ_API_KEY")
        if key:
            return GroqBriefing(api_key=key)
    except Exception as e:
        print(f"[llm] groq unavailable ({e}); using template briefings")
    return None


class State:
    def __init__(self):
        mem, backend = build_memory()
        self.backend_name = backend
        self.memory = mem  # HybridMemoryStore: SQLite db of record + semantic
        # Render's free disk is ephemeral — reseed SQLite from the bundled
        # incidents.json whenever the database comes up empty (fresh deploy).
        try:
            if self.memory.db.count() == 0:
                import json as _json
                import os as _os
                _seed_path = _os.path.join(
                    _os.path.dirname(_os.path.abspath(__file__)),
                    "data", "incidents.json",
                )
                with open(_seed_path) as _f:
                    _incidents = _json.load(_f)
                self.memory.seed(
                    [dict(i, source="seed") for i in _incidents]
                )
                print(f"[memory] reseeded SQLite with {len(_incidents)} incidents")
        except Exception as _e:
            print(f"[memory] startup reseed failed ({_e})")
        self.agent = IncidentAgent(self.memory, llm=build_llm())
        db = self.memory.db
        self.github_repo = db.meta_get("github_repo") or GITHUB_REPO
        try:
            self.sync_minutes = int(db.meta_get("sync_minutes") or SYNC_MINUTES)
        except ValueError:
            self.sync_minutes = SYNC_MINUTES
        self.sync_status: dict = {"last": None, "running": False}
        self.sentinel_status: dict = {"running": False}

    def set_github_repo(self, repo: str) -> dict:
        """Change the watched repo at runtime (persisted in SQLite)."""
        repo = (repo or "").strip()
        if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo):
            return {"error": "repo must look like owner/name"}
        self.github_repo = repo
        self.memory.db.meta_set("github_repo", repo)
        return {"repo": repo}

    @property
    def github_token(self) -> str:
        """Effective token: OAuth grant (DB) wins, env PAT is fallback."""
        try:
            oauth = self.memory.db.meta_get("github_oauth_token")
        except Exception:
            oauth = ""
        return oauth or GITHUB_TOKEN or ""

    @property
    def github_oauth_connected(self) -> bool:
        try:
            return bool(self.memory.db.meta_get("github_oauth_token"))
        except Exception:
            return False

    @property
    def github_repos(self) -> list:
        """All connected repos (migrates legacy single-repo setting)."""
        raw = self.memory.db.meta_get("github_repos")
        if raw:
            try:
                repos = json.loads(raw)
                if isinstance(repos, list) and repos:
                    return repos
            except Exception:
                pass
        return [self.github_repo] if self.github_repo else []

    def add_github_repo(self, repo: str) -> dict:
        repo = (repo or "").strip()
        if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo):
            return {"error": "repo must look like owner/name"}
        repos = self.github_repos
        if repo not in repos:
            repos.append(repo)
            self.memory.db.meta_set("github_repos", json.dumps(repos))
        return {"repos": repos}

    def remove_github_repo(self, repo: str) -> dict:
        repos = [r for r in self.github_repos if r != repo]
        self.memory.db.meta_set("github_repos", json.dumps(repos))
        return {"repos": repos}

    def github_access_mode(self) -> str:
        return self.memory.db.meta_get("github_access_mode") or "write"

    def set_github_access_mode(self, mode: str) -> dict:
        mode = "write" if mode == "write" else "read"
        self.memory.db.meta_set("github_access_mode", mode)
        return {"access_mode": mode}

    # ---- per-user GitHub (each login connects their own repos) ----
    def gh_for(self, user_id: int | None) -> dict:
        """This user's GitHub settings: token, repos, access_mode.

        Strictly per-user: another login never sees your repos.
        Token falls back to the GITHUB_TOKEN env var (server owner's PAT)."""
        if user_id:
            db = self.memory.db
            with db._lock, db._conn() as c:
                s = auth_mod.get_user_github(c, user_id)
            s["token"] = s["token"] or GITHUB_TOKEN or ""
            return s
        return {"token": GITHUB_TOKEN or "", "repos": [],
                "access_mode": self.github_access_mode()}

    def gh_token_for(self, user_id: int | None) -> str:
        return self.gh_for(user_id)["token"]

    def gh_repos_for(self, user_id: int | None) -> list:
        return self.gh_for(user_id)["repos"]

    def gh_mode_for(self, user_id: int | None) -> str:
        return self.gh_for(user_id)["access_mode"]

    def _gh_write(self, user_id: int, **kw) -> dict:
        db = self.memory.db
        with db._lock, db._conn() as c:
            if "token" in kw:
                auth_mod.set_user_github_token(c, user_id, kw["token"])
            if "repos" in kw:
                auth_mod.set_user_github_repos(c, user_id, kw["repos"])
            if "mode" in kw:
                auth_mod.set_user_github_mode(c, user_id, kw["mode"])
            return auth_mod.get_user_github(c, user_id)

    def set_sync_minutes(self, minutes: int) -> dict:
        minutes = max(1, min(int(minutes), 1440))
        self.sync_minutes = minutes
        self.memory.db.meta_set("sync_minutes", str(minutes))
        return {"sync_minutes": minutes}

    def clear_database(self) -> dict:
        """Wipe local incidents + sync state. Memory re-syncs from GitHub."""
        db = self.memory.db
        with db._lock, db._conn() as c:
            c.execute("DELETE FROM incidents")
            c.execute("DELETE FROM github_sync")
            c.execute("DELETE FROM investigations")
        return {"cleared": True, "incidents": db.count()}

    def get_settings(self) -> dict:
        db = self.memory.db
        return {
            "github_repo": self.github_repo,
            "repo_url": f"https://github.com/{self.github_repo}",
            "repos": self.github_repos,
            "access_mode": self.github_access_mode(),
            "github_token_configured": bool(self.github_token),
            "sync_minutes": self.sync_minutes,
            "last_sync_at": db.meta_get("github_last_sync_at"),
            "memory_backend": self.backend_name,
            "hindsight_bank": BANK_ID if self.backend_name == "hindsight" else None,
            "incidents_remembered": db.count(),
            "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
            "google_client_id": GOOGLE_CLIENT_ID,
            "github_oauth_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
        }

    def sync_github_now(self, repo: str | None = None,
                        user_id: int | None = None) -> dict:
        """One GitHub sync pass for one repo; safe to call from any thread."""
        gh = self.gh_for(user_id)
        repo = repo or (gh["repos"] or [None])[0]
        if not repo:
            return {"error": "no repo connected"}
        if self.sync_status.get("running"):
            return {"error": "sync already running",
                    **(self.sync_status.get("last") or {})}
        self.sync_status["running"] = True
        try:
            result = gh_sync.sync_github(
                self.memory, self.memory.db,
                repo, gh["token"],
                investigate_fn=lambda alert: self.agent.investigate(alert),
            )
            self.sync_status["last"] = result
            return result
        finally:
            self.sync_status["running"] = False

    def sync_all_repos(self, user_id: int | None = None) -> dict:
        """Sync every connected repo for one user; returns per-repo results."""
        out = {}
        for repo in self.gh_repos_for(user_id):
            try:
                out[repo] = self.sync_github_now(repo, user_id=user_id)
            except Exception as e:
                out[repo] = {"error": str(e)[:120]}
        return out


    # ---- plugins ------------------------------------------------------
    def plugins_list(self) -> list:
        return _list_plugins(self.memory.db)

    def plugin_toggle(self, plugin_id: str, enabled: bool) -> dict:
        return _set_plugin_enabled(self.memory.db, plugin_id, enabled)

    def plugins_status(self, user_id: int | None = None) -> dict:
        db = self.memory.db
        gh = self.gh_for(user_id)
        repo = (gh["repos"] or [None])[0]
        return {
            "plugins": self.plugins_list(),
            "sentinel": {
                "enabled": _plugin_enabled(db, "sentinel"),
                "interval_minutes": _sentinel.scan_interval_minutes(db),
                "last_run": db.meta_get("sentinel_last_run"),
                "last_result": _sentinel.last_result(db),
                "running": bool(self.sentinel_status.get("running")),
            },
            "autofix": {
                "enabled": _plugin_enabled(db, "autofix"),
                "last": db.meta_get("autofix_last"),
            },
            "github_repo": repo,
            "repo_url": f"https://github.com/{repo}" if repo else "",
            "github_connection": {**_gh_api.test_connection(gh["token"]),
                "repo_permissions": _gh_api.repo_permissions(repo, gh["token"]) if repo else {}},
            "oauth_connected": bool(gh["token"]),
            "oauth_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
            "repos": gh["repos"],
            "access_mode": gh["access_mode"],
        }

    def set_sentinel_minutes(self, minutes: int) -> dict:
        minutes = max(5, min(int(minutes), 1440))
        _set_plugin_setting(self.memory.db, "sentinel_minutes", str(minutes))
        return {"sentinel_minutes": minutes}

    def sentinel_scan_now(self, user_id: int | None = None) -> dict:
        """One sentinel pass + auto-fix attempts; safe from any thread.

        When user_id is given, scans THAT user's repos with THEIR token
        (per-user view); otherwise the legacy global view."""
        if self.sentinel_status.get("running"):
            return {"error": "sentinel scan already running"}
        self.sentinel_status["running"] = True
        try:
            state = _UserState(self, user_id) if user_id else self
            result = _sentinel.scan_once(state)
            fixes = []
            for p in result.get("problems", []):
                try:
                    fixes.append(_autofix.attempt_fix(state, p))
                except Exception as e:
                    fixes.append({"error": str(e)[:120]})
            result["autofix"] = fixes
            return result
        finally:
            self.sentinel_status["running"] = False

    def github_status(self, user_id: int | None = None) -> dict:
        db = self.memory.db
        gh = self.gh_for(user_id)
        repo = (gh["repos"] or [None])[0]
        counts = db.github_sync_counts(repo) if repo else {}
        return {
            "repo": repo,
            "repo_url": f"https://github.com/{repo}" if repo else "",
            "token_configured": bool(gh["token"]),
            "oauth_connected": bool(gh["token"]),
            "repos": gh["repos"],
            "access_mode": gh["access_mode"],
            "last_sync_at": db.meta_get("github_last_sync_at"),
            "sync_interval_minutes": self.sync_minutes,
            "running": self.sync_status.get("running", False),
            "last_result": self.sync_status.get("last"),
            **counts,
        }


class _UserState:
    """Per-user view of the global State, for background plugins.

    Delegates everything to the real State except the GitHub settings,
    which come from this user's own connection (their token, their repos,
    their read/write mode)."""
    def __init__(self, state, user_id):
        object.__setattr__(self, "_s", state)
        object.__setattr__(self, "_gh", state.gh_for(user_id))

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_s"), name)

    @property
    def github_token(self):
        return object.__getattribute__(self, "_gh")["token"]

    @property
    def github_repos(self):
        return object.__getattribute__(self, "_gh")["repos"]

    @property
    def github_repo(self):
        repos = object.__getattribute__(self, "_gh")["repos"]
        return repos[0] if repos else ""

    def gh_mode_for(self, user_id=None):
        return object.__getattribute__(self, "_gh")["access_mode"]


STATE = State()


def _github_user_ids() -> list:
    """User ids with a GitHub token connected (for background loops)."""
    try:
        db = STATE.memory.db
        with db._lock, db._conn() as c:
            return auth_mod.users_with_github(c)
    except Exception:
        return []


def _sync_loop():
    """Background: sync on boot, then every SYNC_MINUTES (per user)."""
    for uid in _github_user_ids():
        try:
            STATE.sync_all_repos(user_id=uid)
        except Exception as e:
            print(f"[sync] user {uid} boot sync failed: {e}")
    while True:
        time.sleep(max(STATE.sync_minutes, 1) * 60)
        for uid in _github_user_ids():
            try:
                STATE.sync_all_repos(user_id=uid)
            except Exception as e:
                print(f"[sync] user {uid} sync failed: {e}")


def _sentinel_loop():
    """Background: repo health scan every N minutes, even with site closed.

    Scans each connected user's repos with their own token."""
    import time as _t
    _t.sleep(60)  # let boot settle
    while True:
        try:
            if _plugin_enabled(STATE.memory.db, "sentinel"):
                for uid in _github_user_ids():
                    try:
                        STATE.sentinel_scan_now(user_id=uid)
                    except Exception as e:
                        print(f"[sentinel] user {uid} scan failed: {e}")
        except Exception as e:
            print(f"[sentinel] scan failed: {e}")
        try:
            mins = _sentinel.scan_interval_minutes(STATE.memory.db)
        except Exception:
            mins = 15
        _t.sleep(max(mins, 5) * 60)


class Handler(BaseHTTPRequestHandler):
    server_version = "TraceMind/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url: str):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    # Canonical domain: only tracemind.run.place serves the site. The old
    # onrender.com host (and only it) 308-redirects here, preserving path,
    # method and body. localhost keeps working for local dev.
    CANONICAL_HOST = "tracemind.run.place"
    LEGACY_HOSTS = {"tracemind-szuq.onrender.com"}

    def _force_canonical(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host in self.LEGACY_HOSTS:
            self.send_response(308)
            self.send_header("Location", "https://" + self.CANONICAL_HOST + self.path)
            self.end_headers()
            return True
        return False

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def _uid(self):
        """Logged-in TraceMind user id from the Bearer token, or None."""
        h = self.headers.get("Authorization") or ""
        tok = h[7:] if h.startswith("Bearer ") else ""
        if not tok:
            return None
        try:
            return auth_mod.verify_token(tok)
        except Exception:
            return None

    def _require_uid(self):
        uid = self._uid()
        if not uid:
            self._send(401, {"error": "login required"})
            return None
        # presence: mark the user as seen (throttled to 1/min in SQL)
        try:
            db = STATE.memory.db
            with db._lock, db._conn() as c:
                auth_mod.touch_seen(c, uid)
        except Exception:
            pass
        return uid

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For") or ""
        if fwd:
            return fwd.split(",")[0].strip()
        return self.client_address[0]

    def _require_admin(self):
        """Logged-in user id, only if their email is in ADMIN_EMAILS."""
        uid = self._require_uid()
        if not uid:
            return None
        try:
            db = STATE.memory.db
            with db._lock, db._conn() as c:
                user = auth_mod.get_user(c, uid)
        except Exception:
            user = None
        if not user or (user.get("email") or "").lower() not in ADMIN_EMAILS:
            self._send(403, {"error": "admin only"})
            return None
        return uid

    def do_GET(self):
        if self._force_canonical():
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/github/oauth/start":
            if not (GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET):
                return self._send(500, {"error": "GitHub OAuth not configured"})
            # Canonical callback: every host uses the primary domain's callback
            # (registered on the GitHub OAuth App), so a login that starts on
            # another host finishes here.
            cb = "https://tracemind.run.place/api/github/oauth/callback"
            qs0 = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            login_mode = (qs0.get("mode") or [""])[0] == "login"
            nonce = (qs0.get("nonce") or [""])[0]
            if login_mode:
                state = "login"
            elif nonce:
                state = "connect:" + nonce
            else:
                # legacy connect without a logged-in user: no per-user binding
                state = "connect"
            q = urllib.parse.urlencode({
                "client_id": GITHUB_CLIENT_ID,
                "redirect_uri": cb,
                "scope": "repo user:email",
                "state": state,
            })
            return self._redirect("https://github.com/login/oauth/authorize?" + q)
        if path == "/api/github/oauth/callback":
            qs = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [""])[0]
            state = (qs.get("state") or [""])[0]
            if not code:
                _oauth_dbg("callback: no code (github error=%s)" % (qs.get("error") or [""])[0])
                return self._redirect("/?github=error")
            try:
                data = urllib.parse.urlencode({
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                }).encode()
                req = urllib.request.Request(
                    "https://github.com/login/oauth/access_token",
                    data=data, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    tok = json.load(r)
                access = tok.get("access_token", "")
                if not access:
                    _oauth_dbg("callback: token exchange failed state=%s err=%s" % (state, tok.get("error")))
                    return self._redirect("/?github=error")
                if state == "login":
                    # "Login with GitHub": also sign the user into TraceMind,
                    # and keep THEIR token on THEIR account (per-user).
                    try:
                        db = STATE.memory.db
                        with db._lock, db._conn() as c:
                            out = auth_mod.github_login(c, access)
                            try:
                                auth_mod.set_user_github_token(
                                    c, out["user"]["id"], access)
                            except Exception:
                                pass
                            try:
                                auth_mod.record_login(
                                    c, out["user"]["id"], "github",
                                    self._client_ip())
                            except Exception:
                                pass
                        return self._redirect("/?github=login&code=" + _issue_oauth_code(out["token"]))
                    except Exception as e:
                        _oauth_dbg("callback: github_login failed: %s" % e)
                        return self._redirect("/?github=error")
                if state.startswith("connect:"):
                    # "Connect repo": bind this GitHub token to the logged-in
                    # user who started the flow (via the nonce).
                    try:
                        db = STATE.memory.db
                        with db._lock, db._conn() as c:
                            uid = auth_mod.consume_github_nonce(
                                c, state[len("connect:"):])
                            if uid:
                                auth_mod.set_user_github_token(c, uid, access)
                            else:
                                _oauth_dbg("callback: connect nonce invalid/expired")
                    except Exception as e:
                        _oauth_dbg("callback: connect failed: %s" % e)
                    return self._redirect("/?github=connected")
                if state == "connect":
                    # Legacy connect without a nonce: no logged-in user to
                    # bind the token to. Don't silently drop it — tell the
                    # user to log in first.
                    _oauth_dbg("callback: legacy connect without nonce")
                    return self._redirect("/?github=nologin")
                _oauth_dbg("callback: unknown state=%s" % state)
                return self._redirect("/?github=error")
            except Exception as e:
                _oauth_dbg("callback: unexpected error: %s" % e)
                return self._redirect("/?github=error")
        if path == "/api/health":
            m = STATE.memory
            return self._send(200, {
                "ok": True, "backend": STATE.backend_name,
                "database": _db_label(DB_PATH),
                "memory_size": m.count(),
                "db_size": m.db.count(),
                "github": {
                    "repo": STATE.github_repo,
                    "last_sync_at": STATE.memory.db.meta_get("github_last_sync_at"),
                },
            })
        if path == "/api/incidents":
            # real incidents, open first then most recent
            incs = STATE.memory.db.list(limit=50)
            incs.sort(key=lambda i: (i.get("outcome") == "open",
                                     i.get("started_at") or ""), reverse=True)
            return self._send(200, {"incidents": [
                {"id": i["id"], "title": i.get("title"),
                 "service": i.get("service"), "severity": i.get("severity"),
                 "outcome": i.get("outcome"), "started_at": i.get("started_at"),
                 "github": (i.get("github_issue") or {})}
                for i in incs
            ]})
        if path == "/api/memory":
            m = STATE.memory
            recent = m.db.recent(5)
            return self._send(200, {
                "backend": STATE.backend_name,
                "size": m.count(),
                "recent": [{"id": r["id"], "title": r["title"]} for r in recent],
            })
        if path == "/api/integrations/github":
            return self._send(200, STATE.github_status(self._uid()))
        if path == "/api/plugins":
            return self._send(200, {"plugins": STATE.plugins_list()})
        if path == "/api/plugins/status":
            return self._send(200, STATE.plugins_status(self._uid()))
        if path == "/api/settings":
            return self._send(200, STATE.get_settings())
        if path == "/api/db/stats":
            db = STATE.memory.db
            s = db.stats()
            s["database"] = "sqlite"
            return self._send(200, s)
        if path == "/api/db/incidents":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                limit = min(int(qs.get("limit", ["50"])[0]), 200)
            except ValueError:
                limit = 50
            try:
                offset = max(int(qs.get("offset", ["0"])[0]), 0)
            except ValueError:
                offset = 0
            service = (qs.get("service", [None])[0] or None)
            db = STATE.memory.db
            return self._send(200, {
                "total": db.count(),
                "incidents": db.list(limit=limit, offset=offset, service=service),
            })
        if path.startswith("/api/db/incident/"):
            inc_id = urllib.parse.unquote(path[len("/api/db/incident/"):])
            inc = STATE.memory.db.get(inc_id)
            if inc:
                return self._send(200, {"incident": inc})
            return self._send(404, {"error": "incident not found"})
        if path == "/api/db/investigations":
            return self._send(200, {
                "investigations": STATE.memory.db.recent_investigations(20),
            })
        if path == "/api/auth/me":
            bearer = (self.headers.get("Authorization") or "")
            uid = auth_mod.verify_token(bearer[7:] if bearer.startswith("Bearer ") else "")
            db = STATE.memory.db
            with db._lock, db._conn() as c:
                user = auth_mod.get_user(c, uid) if uid else None
            if user:
                user["is_admin"] = ((user.get("email") or "").lower()
                                    in ADMIN_EMAILS)
                return self._send(200, {"user": user})
            return self._send(401, {"error": "not logged in"})
        if path == "/api/admin/stats":
            # Admin-only: site-wide logins, providers, online members.
            if not self._require_admin():
                return
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    stats = auth_mod.admin_stats(c)
                return self._send(200, stats)
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/admin/restore" and self.command == "POST":
            # Admin-only, one-time: re-import a login snapshot (users + login
            # history) after moving to a fresh/persistent database. A meta
            # flag makes it refuse to run twice so history can't be duplicated.
            # Password accounts can't be restored (hashes never leave the DB),
            # so only google/github users are re-created; they log back in
            # with their provider as usual.
            if not self._require_admin():
                return
            try:
                body = self._read_json() or {}
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    if db.meta_get("admin_restore_done"):
                        return self._send(409, {"error": "restore already done"})
                    auth_mod.ensure_schema(c)
                    email_to_uid = {}
                    restored_users = restored_events = skipped = 0
                    for u in body.get("users", []) or []:
                        email = (u.get("email") or "").strip().lower()
                        if not email:
                            continue
                        row = c.execute(
                            "SELECT id FROM users WHERE email=?", (email,)).fetchone()
                        if row:
                            email_to_uid[email] = row[0]
                            continue
                        provider = (u.get("provider") or "").strip() or "google"
                        if provider == "password":
                            skipped += 1
                            continue
                        sentinel = ("google-oauth" if provider == "google"
                                    else "github-oauth")
                        cur = c.execute(
                            "INSERT INTO users(name,email,pw_hash,provider,created_at,last_seen)"
                            " VALUES(?,?,?,?," 
                            "COALESCE(?,strftime('%Y-%m-%dT%H:%M:%SZ','now')),"
                            "COALESCE(?,strftime('%Y-%m-%dT%H:%M:%SZ','now')))",
                            (u.get("name") or email.split("@")[0], email, sentinel,
                             provider, u.get("created_at"), u.get("last_seen")))
                        email_to_uid[email] = cur.lastrowid
                        restored_users += 1
                    for e in body.get("login_events", []) or []:
                        email = (e.get("email") or "").strip().lower()
                        uid = email_to_uid.get(email)
                        if not uid:
                            continue
                        dup = c.execute(
                            "SELECT id FROM login_events WHERE email=? AND created_at=?",
                            (email, e.get("created_at"))).fetchone()
                        if dup:
                            continue
                        c.execute(
                            "INSERT INTO login_events(user_id,email,provider,ip,created_at)"
                            " VALUES(?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%SZ','now')))",
                            (uid, email, e.get("provider") or "", e.get("ip") or "",
                             e.get("created_at")))
                        restored_events += 1
                    db.meta_set("admin_restore_done", "1")
                return self._send(200, {"restored_users": restored_users,
                                        "restored_events": restored_events,
                                        "skipped_password_users": skipped})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/profile":
            uid = self._uid()
            if not uid:
                return self._send(401, {"error": "login required"})
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    prof = auth_mod.get_profile(c, uid)
                    repos = auth_mod.get_user_github(c, uid).get("repos", [])
                if not prof:
                    return self._send(404, {"error": "no profile"})
                try:
                    stats = db.stats()
                except Exception:
                    stats = {}
                prof["stats"] = {
                    "incidents": stats.get("incidents", 0),
                    "investigations": stats.get("investigations", 0),
                }
                prof["repos"] = repos
                try:
                    prof.update(auth_mod.follow_counts(c, uid))
                except Exception:
                    prof.update({"followers": 0, "following": 0})
                return self._send(200, {"profile": prof})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/profile/public":
            # Shareable profile page: ?u=<username>. No email, no auth needed.
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            username = (qs.get("username") or [""])[0].strip().lower()
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    row = c.execute(
                        "SELECT id FROM users WHERE lower(username)=?",
                        (username,)).fetchone() if username else None
                    if not row:
                        return self._send(404, {"error": "no such profile"})
                    prof = auth_mod.get_profile(c, row[0])
                    repos = auth_mod.get_user_github(c, row[0]).get("repos", [])
                pub = {k: prof[k] for k in (
                    "name", "username", "bio", "avatar_url",
                    "socials", "created_at")}
                try:
                    stats = db.stats()
                except Exception:
                    stats = {}
                pub["stats"] = {
                    "incidents": stats.get("incidents", 0),
                    "investigations": stats.get("investigations", 0),
                }
                pub["repos"] = repos
                try:
                    pub.update(auth_mod.follow_counts(c, row[0]))
                except Exception:
                    pub.update({"followers": 0, "following": 0})
                pub["is_self"] = False
                pub["is_following"] = False
                try:
                    viewer = self._uid()
                    if viewer:
                        pub["is_self"] = (viewer == row[0])
                        pub["is_following"] = auth_mod.is_following(
                            c, viewer, row[0])
                except Exception:
                    pass
                return self._send(200, {"profile": pub})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        # static files
        rel = path.lstrip("/") or "index.html"
        fpath = os.path.normpath(os.path.join(FRONTEND_DIR, rel))
        if not fpath.startswith(os.path.abspath(FRONTEND_DIR)):
            return self._send(403, {"error": "forbidden"})
        if os.path.isdir(fpath):
            fpath = os.path.join(fpath, "index.html")
        if os.path.exists(fpath):
            ext = os.path.splitext(fpath)[1]
            with open(fpath, "rb") as f:
                return self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._force_canonical():
            return
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json()
        if path == "/api/github/oauth/nonce":
            # Logged-in user starts "Connect with GitHub": mint a one-time
            # nonce so the OAuth redirect binds the token back to them.
            uid = self._require_uid()
            if not uid:
                return
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    nonce = auth_mod.create_github_nonce(c, uid)
                return self._send(200, {"nonce": nonce})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/profile":
            uid = self._require_uid()
            if not uid:
                return
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    prof = auth_mod.update_profile(
                        c, uid,
                        name=body.get("name") if "name" in body else None,
                        username=body.get("username") if "username" in body else None,
                        bio=body.get("bio") if "bio" in body else None,
                        avatar_url=body.get("avatar_url") if "avatar_url" in body else None,
                        socials=body.get("socials") if "socials" in body else None,
                    )
                return self._send(200, {"profile": prof})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/chat":
            # Plain conversation with Trace (not an incident): answered by the
            # LLM, grounded in what TraceMind is and does. No alert is fired.
            msg = (body.get("message") or "").strip()
            if not msg:
                return self._send(400, {"error": "empty message"})
            key = os.environ.get("GROQ_API_KEY")
            if key:
                try:
                    from backend.llm.groq import groq_chat, CHAT_SYSTEM
                    reply = groq_chat(key, CHAT_SYSTEM, msg[:2000])
                    if not reply:
                        raise RuntimeError("empty reply")
                    return self._send(200, {"reply": reply, "via": "groq"})
                except Exception:
                    pass  # fall through to the offline fallback below
            return self._send(200, {
                "reply": ("I'm Trace \u2014 I turn your repo's incidents into organizational "
                          "memory. Paste an alert, an error, or a stack trace and I'll "
                          "investigate it: break it down, search past incidents, and "
                          "suggest a fix. You can also connect a GitHub repo and I'll "
                          "watch its CI runs for you."),
                "via": "fallback",
            })
        if path == "/api/chat/plan-edit":
            # Autonomous code edit: the user describes a change in plain words.
            # Trace picks the repo + file, generates the new content, and returns
            # a diff for approval. The actual commit goes through /api/repo/commit
            # (new branch + PR, never main).
            uid = self._require_uid()
            if not uid:
                return
            try:
                import json as _json
                import difflib as _difflib
                token = self.gh_token_for(uid)
                repos = self.gh_repos_for(uid)
                if not token:
                    return self._send(400, {"error": "connect_github"})
                if not repos:
                    return self._send(400, {"error": "no_repos"})
                msg = (body.get("message") or "").strip()
                if not msg:
                    return self._send(400, {"error": "empty message"})
                key = os.environ.get("GROQ_API_KEY")
                if not key:
                    return self._send(500, {"error": "AI is not configured right now"})
                from backend.llm.groq import groq_chat

                def _plan(system, user):
                    raw = groq_chat(key, system, user[:4000], max_tokens=300).strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
                    try:
                        return _json.loads(raw)
                    except Exception:
                        m = re.search(r"\{.*\}", raw, re.S)
                        return _json.loads(m.group(0)) if m else {}

                # 1) pick the repo
                repo = None
                ml = msg.lower()
                for r in repos:
                    if r.lower() in ml or r.split("/")[-1].lower() in ml:
                        repo = r
                        break
                if not repo and len(repos) == 1:
                    repo = repos[0]
                if not repo:
                    pick = _plan(
                        "You pick which GitHub repo the user means. "
                        "Output ONLY JSON: {\"repo\": \"owner/name\"} or "
                        "{\"clarify\": \"question for the user\"}.",
                        "Repos: " + ", ".join(repos) + "\nRequest: " + msg)
                    if pick.get("clarify"):
                        return self._send(200, {"clarify": pick["clarify"]})
                    repo = pick.get("repo") if pick.get("repo") in repos else None
                    if not repo:
                        return self._send(200, {"clarify":
                            "Which repo should I change? (" + ", ".join(repos) + ")"})
                # 2) pick the file
                meta = _gh_api.get_repo(repo, token)
                base = meta.get("default_branch") or "main"
                try:
                    tree = _gh_api.repo_tree(repo, base, token)
                except Exception:
                    tree = []
                if not tree:
                    return self._send(500, {"error": "could not read that repo's files"})
                plan = _plan(
                    "You are a code-edit planner. Output ONLY JSON, no other text: "
                    "{\"path\": \"path/to/file\", \"change\": \"one-sentence description\", "
                    "\"new_file\": false} or {\"clarify\": \"question\"}. "
                    "new_file=true only if the user wants a brand-new file. "
                    "Choose only from the listed files.",
                    "Repo: " + repo + "\nFiles:\n" + "\n".join(tree) +
                    "\n\nRequest: " + msg)
                if plan.get("clarify") or not plan.get("path"):
                    return self._send(200, {"clarify": plan.get("clarify") or
                        "Which file should I change?"})
                fpath = plan["path"].strip().lstrip("/")
                if fpath not in tree and not plan.get("new_file"):
                    return self._send(200, {"clarify":
                        "I couldn't find that file — which file should I change?"})
                # 3) generate the new content
                old_content = ""
                if not plan.get("new_file"):
                    f = _gh_api.get_file(repo, fpath, base, token)
                    old_content = (f or {}).get("content") or ""
                new_content = groq_chat(
                    key,
                    "You are a code editor. Apply the requested change to the file. "
                    "Output ONLY the complete new file content — no explanations, "
                    "no code fences, no markdown.",
                    "Requested change: " + plan.get("change", msg) +
                    "\nFile: " + fpath +
                    ("\n\nCurrent content:\n" + old_content[:12000]
                     if old_content else "\n\nCreate this new file from scratch."),
                    max_tokens=4000).strip()
                if new_content.startswith("```"):
                    new_content = new_content.split("\n", 1)[1].rsplit("```", 1)[0]
                if not new_content:
                    return self._send(500, {"error": "the AI came back empty — try again"})
                diff = "\n".join(_difflib.unified_diff(
                    old_content.splitlines(), new_content.splitlines(),
                    fromfile="before", tofile="after", lineterm=""))[:6000]
                return self._send(200, {
                    "repo": repo, "path": fpath,
                    "change": plan.get("change", msg),
                    "new_file": bool(plan.get("new_file")),
                    "diff": diff, "new_content": new_content,
                    "suggested_message": (plan.get("change") or "Update " + fpath)[:120],
                })
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if path in ("/api/profile/follow", "/api/profile/unfollow"):
            uid = self._require_uid()
            if not uid:
                return
            username = (body.get("username") or "").strip().lower()
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    row = c.execute(
                        "SELECT id FROM users WHERE lower(username)=?",
                        (username,)).fetchone() if username else None
                    if not row:
                        return self._send(404, {"error": "no such profile"})
                    if path.endswith("/follow"):
                        counts = auth_mod.follow(c, uid, row[0])
                    else:
                        counts = auth_mod.unfollow(c, uid, row[0])
                counts["is_following"] = path.endswith("/follow")
                return self._send(200, counts)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/investigate":
            alert = body.get("alert", {})
            try:
                result = STATE.agent.investigate(alert)
                return self._send(200, result)
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/resolve":
            a = STATE.agent
            try:
                result = a.resolve(
                    draft=body.get("draft", {}),
                    root_cause=body.get("root_cause", ""),
                    fix=body.get("fix", ""),
                    engineer=body.get("engineer", "on-call"),
                    mttr_minutes=int(body.get("mttr_minutes", 0)),
                    investigation_steps=body.get("investigation_steps", []),
                    commands_used=body.get("commands_used", []),
                )
                return self._send(200, result)
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/integrations/github/sync":
            uid = self._require_uid()
            if not uid:
                return
            try:
                return self._send(200, STATE.sync_github_now(
                    None, user_id=uid))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/settings":
            try:
                if "github_repo" in body:
                    r = STATE.set_github_repo(body["github_repo"])
                    if r.get("error"):
                        return self._send(400, r)
                if "sync_minutes" in body:
                    STATE.set_sync_minutes(body["sync_minutes"])
                return self._send(200, STATE.get_settings())
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path.startswith("/api/plugins/toggle/"):
            try:
                pid = path[len("/api/plugins/toggle/"):]
                return self._send(200, STATE.plugin_toggle(
                    pid, bool(body.get("enabled"))))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/plugins/scan":
            try:
                return self._send(200, STATE.sentinel_scan_now(
                    self._uid()))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/repos/add":
            uid = self._require_uid()
            if not uid:
                return
            try:
                repo = (body.get("repo", "") or "").strip()
                if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo):
                    return self._send(400, {"error": "repo must look like owner/name"})
                s = STATE.gh_for(uid)
                repos = s["repos"]
                if repo not in repos:
                    repos.append(repo)
                    s = STATE._gh_write(uid, repos=repos)
                return self._send(200, {"repos": s["repos"]})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/repos/remove":
            uid = self._require_uid()
            if not uid:
                return
            try:
                repo = (body.get("repo", "") or "").strip()
                s = STATE.gh_for(uid)
                repos = [r for r in s["repos"] if r != repo]
                s = STATE._gh_write(uid, repos=repos)
                return self._send(200, {"repos": s["repos"]})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/disconnect":
            uid = self._require_uid()
            if not uid:
                return
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    auth_mod.clear_user_github(c, uid)
                return self._send(200, {"disconnected": True})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/mode":
            uid = self._require_uid()
            if not uid:
                return
            try:
                s = STATE._gh_write(uid, mode=body.get("mode", "read"))
                return self._send(200, {"access_mode": s["access_mode"]})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/repo/file":
            # Read a file from one of the user's connected repos.
            uid = self._require_uid()
            if not uid:
                return
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            repo = (qs.get("repo") or [""])[0].strip()
            fpath = (qs.get("path") or [""])[0].strip().lstrip("/")
            try:
                token = self.gh_token_for(uid)
                if not token:
                    return self._send(400, {"error": "GitHub not connected"})
                if not repo or not fpath or ".." in fpath.split("/"):
                    return self._send(400, {"error": "repo and a valid path required"})
                meta = _gh_api.get_repo(repo, token)
                ref = (qs.get("ref") or [""])[0].strip() or meta.get("default_branch") or "main"
                f = _gh_api.get_file(repo, fpath, ref, token)
                if not f:
                    return self._send(404, {"error": "file not found"})
                return self._send(200, {"repo": repo, "ref": ref, "path": f["path"],
                                       "sha": f["sha"], "content": f["content"]})
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if path == "/api/repo/commit":
            # Commit file changes to the user's repo. ALWAYS creates a new
            # branch and opens a pull request — never pushes to main directly.
            uid = self._require_uid()
            if not uid:
                return
            try:
                token = self.gh_token_for(uid)
                if not token:
                    return self._send(400, {"error": "GitHub not connected"})
                repo = (body.get("repo") or "").strip()
                files = body.get("files") or []
                message = (body.get("message") or "").strip() or "Update via TraceMind"
                if not repo or not files:
                    return self._send(400, {"error": "repo and files required"})
                if len(files) > 10:
                    return self._send(400, {"error": "max 10 files per commit"})
                clean = []
                for f in files:
                    fp = (f.get("path") or "").strip().lstrip("/")
                    if not fp or ".." in fp.split("/"):
                        return self._send(400, {"error": f"bad path: {f.get('path')}"})
                    clean.append({"path": fp, "content": f.get("content") or ""})
                meta = _gh_api.get_repo(repo, token)
                base = meta.get("default_branch") or "main"
                head_commit = _gh_api.latest_commit(repo, base, token)
                branch = "tracemind-edit-" + time.strftime("%Y%m%d-%H%M%S")
                _gh_api.create_branch(repo, branch, head_commit["sha"], token)
                committed = []
                for f in clean:
                    existing = _gh_api.get_file(repo, f["path"], branch, token)
                    r = _gh_api.update_file(repo, f["path"], f["content"], message,
                                            branch, existing["sha"] if existing else None,
                                            token)
                    committed.append({"path": f["path"],
                                      "url": (r.get("content") or {}).get("html_url")})
                pr = _gh_api.open_pr(repo, message,
                                     "Committed from TraceMind. Review and merge when ready.",
                                     branch, base, token)
                return self._send(200, {"repo": repo, "branch": branch, "base": base,
                                       "files": committed,
                                       "pr_url": pr.get("html_url"),
                                       "pr_number": pr.get("number")})
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if path == "/api/plugins/interval":
            try:
                return self._send(200, STATE.set_sentinel_minutes(
                    body.get("minutes", 15)))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/settings/clear-db":
            try:
                return self._send(200, STATE.clear_database())
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path in ("/api/auth/signup", "/api/auth/login"):
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    if path.endswith("signup"):
                        out = auth_mod.signup(c, body.get("name", ""),
                                              body.get("email", ""),
                                              body.get("password", ""))
                    else:
                        out = auth_mod.login(c, body.get("email", ""),
                                             body.get("password", ""))
                    try:
                        auth_mod.record_login(
                            c, out["user"]["id"], "password",
                            self._client_ip())
                    except Exception:
                        pass
                return self._send(200, out)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/auth/logout":
            return self._send(200, {"ok": True})
        if path == "/api/auth/oauth/consume":
            # Exchange a single-use OAuth login code for the token.
            token = _consume_oauth_code(body.get("code", ""))
            if not token:
                return self._send(400, {"error": "login expired — try again"})
            uid = auth_mod.verify_token(token)
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    user = auth_mod.get_user(c, uid) if uid else None
            except Exception:
                user = None
            if not user:
                return self._send(401, {"error": "login expired — try again"})
            user["is_admin"] = ((user.get("email") or "").lower()
                                in ADMIN_EMAILS)
            return self._send(200, {"token": token, "user": user})
        if path == "/api/auth/google":
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    out = auth_mod.google_login(c, body.get("credential", ""),
                                                GOOGLE_CLIENT_ID)
                    try:
                        auth_mod.record_login(
                            c, out["user"]["id"], "google",
                            self._client_ip())
                    except Exception:
                        pass
                return self._send(200, out)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _migrate_global_github():
    """One-time: move legacy global github_repos to the first user, so
    existing setups survive the switch to per-user GitHub connections.
    The global token is NOT migrated (it may belong to another login)."""
    try:
        db = STATE.memory.db
        raw = db.meta_get("github_repos")
        if not raw:
            return
        import json as _j
        repos = _j.loads(raw)
        if not isinstance(repos, list) or not repos:
            return
        with db._lock, db._conn() as c:
            auth_mod.ensure_schema(c)
            first = c.execute(
                "SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if not first:
                return
            cur = auth_mod.get_user_github(c, first[0])
            if not cur["repos"]:
                auth_mod.set_user_github_repos(c, first[0], repos)
                print(f"[github] migrated {len(repos)} repo(s) to user {first[0]}")
        db.meta_set("github_repos", "")
        db.meta_set("github_repo", "")
    except Exception as e:
        print(f"[github] migration skipped: {e}")


def main():
    _migrate_global_github()
    threading.Thread(target=_sync_loop, daemon=True,
                     name="github-sync").start()
    threading.Thread(target=_sentinel_loop, daemon=True,
                     name="repo-sentinel").start()
    port = int(os.environ.get("PORT", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TraceMind on http://localhost:{port} "
          f"(backend={STATE.backend_name}, database={_db_label(DB_PATH)}, "
          f"github={STATE.github_repo}, bank={BANK_ID})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
