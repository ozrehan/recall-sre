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
  GITHUB_SYNC_MINUTES poll interval (default 5)
"""
from __future__ import annotations

import json
import os
import re
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
from backend.memory.db import IncidentDB
from backend.memory.hybrid_store import HybridMemoryStore
from backend.memory.local_store import LocalMemoryStore

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(HERE, "..", "frontend")
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

    def sync_github_now(self, repo: str | None = None) -> dict:
        """One GitHub sync pass for one repo; safe to call from any thread."""
        repo = repo or self.github_repo
        if self.sync_status.get("running"):
            return {"error": "sync already running",
                    **(self.sync_status.get("last") or {})}
        self.sync_status["running"] = True
        try:
            result = gh_sync.sync_github(
                self.memory, self.memory.db,
                repo, self.github_token,
                investigate_fn=lambda alert: self.agent.investigate(alert),
            )
            self.sync_status["last"] = result
            return result
        finally:
            self.sync_status["running"] = False

    def sync_all_repos(self) -> dict:
        """Sync every connected repo; returns per-repo results."""
        out = {}
        for repo in self.github_repos:
            try:
                out[repo] = self.sync_github_now(repo)
            except Exception as e:
                out[repo] = {"error": str(e)[:120]}
        return out


    # ---- plugins ------------------------------------------------------
    def plugins_list(self) -> list:
        return _list_plugins(self.memory.db)

    def plugin_toggle(self, plugin_id: str, enabled: bool) -> dict:
        return _set_plugin_enabled(self.memory.db, plugin_id, enabled)

    def plugins_status(self) -> dict:
        db = self.memory.db
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
            "github_repo": self.github_repo,
            "repo_url": f"https://github.com/{self.github_repo}",
            "github_connection": {**_gh_api.test_connection(self.github_token),
                "repo_permissions": _gh_api.repo_permissions(
                    self.github_repo, self.github_token)},
            "oauth_connected": self.github_oauth_connected,
            "oauth_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
            "repos": self.github_repos,
            "access_mode": self.github_access_mode(),
        }

    def set_sentinel_minutes(self, minutes: int) -> dict:
        minutes = max(5, min(int(minutes), 1440))
        _set_plugin_setting(self.memory.db, "sentinel_minutes", str(minutes))
        return {"sentinel_minutes": minutes}

    def sentinel_scan_now(self) -> dict:
        """One sentinel pass + auto-fix attempts; safe from any thread."""
        if self.sentinel_status.get("running"):
            return {"error": "sentinel scan already running"}
        self.sentinel_status["running"] = True
        try:
            result = _sentinel.scan_once(self)
            fixes = []
            for p in result.get("problems", []):
                try:
                    fixes.append(_autofix.attempt_fix(self, p))
                except Exception as e:
                    fixes.append({"error": str(e)[:120]})
            result["autofix"] = fixes
            return result
        finally:
            self.sentinel_status["running"] = False

    def github_status(self) -> dict:
        db = self.memory.db
        counts = db.github_sync_counts(self.github_repo)
        return {
            "repo": self.github_repo,
            "repo_url": f"https://github.com/{self.github_repo}",
            "token_configured": bool(self.github_token),
            "last_sync_at": db.meta_get("github_last_sync_at"),
            "sync_interval_minutes": self.sync_minutes,
            "running": self.sync_status.get("running", False),
            "last_result": self.sync_status.get("last"),
            **counts,
        }


STATE = State()


def _sync_loop():
    """Background: sync on boot, then every SYNC_MINUTES."""
    try:
        print(f"[sync] initial GitHub sync: {STATE.github_repo}")
        STATE.sync_github_now()
    except Exception as e:
        print(f"[sync] initial sync failed: {e}")
    while True:
        time.sleep(max(STATE.sync_minutes, 1) * 60)
        try:
            STATE.sync_all_repos()
        except Exception as e:
            print(f"[sync] periodic sync failed: {e}")


def _sentinel_loop():
    """Background: repo health scan every N minutes, even with site closed."""
    import time as _t
    _t.sleep(60)  # let boot settle
    while True:
        try:
            if _plugin_enabled(STATE.memory.db, "sentinel"):
                STATE.sentinel_scan_now()
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

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/github/oauth/start":
            if not (GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET):
                return self._send(500, {"error": "GitHub OAuth not configured"})
            host = self.headers.get("Host", "")
            cb = "https://" + host + "/api/github/oauth/callback"
            qs0 = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            login_mode = (qs0.get("mode") or [""])[0] == "login"
            q = urllib.parse.urlencode({
                "client_id": GITHUB_CLIENT_ID,
                "redirect_uri": cb,
                "scope": "repo",
                "state": "login" if login_mode else "connect",
            })
            return self._redirect("https://github.com/login/oauth/authorize?" + q)
        if path == "/api/github/oauth/callback":
            qs = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [""])[0]
            if not code:
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
                    return self._redirect("/?github=error")
                STATE.memory.db.meta_set("github_oauth_token", access)
                state = (qs.get("state") or [""])[0]
                if state == "login":
                    # "Login with GitHub": also sign the user into TraceMind
                    try:
                        db = STATE.memory.db
                        with db._lock, db._conn() as c:
                            out = auth_mod.github_login(c, access)
                        return self._redirect("/?github=login&token=" + urllib.parse.quote(out["token"], safe=""))
                    except Exception:
                        return self._redirect("/?github=error")
                return self._redirect("/?github=connected")
            except Exception:
                return self._redirect("/?github=error")
        if path == "/api/health":
            m = STATE.memory
            return self._send(200, {
                "ok": True, "backend": STATE.backend_name,
                "database": "sqlite",
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
            return self._send(200, STATE.github_status())
        if path == "/api/plugins":
            return self._send(200, {"plugins": STATE.plugins_list()})
        if path == "/api/plugins/status":
            return self._send(200, STATE.plugins_status())
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
                return self._send(200, {"user": user})
            return self._send(401, {"error": "not logged in"})
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
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json()
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
            try:
                return self._send(200, STATE.sync_github_now())
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
                return self._send(200, STATE.sentinel_scan_now())
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/repos/add":
            try:
                return self._send(200, STATE.add_github_repo(
                    body.get("repo", "")))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/repos/remove":
            try:
                return self._send(200, STATE.remove_github_repo(
                    body.get("repo", "")))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/disconnect":
            try:
                STATE.memory.db.meta_set("github_oauth_token", "")
                return self._send(200, {"disconnected": True})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/github/mode":
            try:
                return self._send(200, STATE.set_github_access_mode(
                    body.get("mode", "read")))
            except Exception as e:
                return self._send(500, {"error": str(e)})
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
                return self._send(200, out)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/auth/logout":
            return self._send(200, {"ok": True})
        if path == "/api/auth/google":
            try:
                db = STATE.memory.db
                with db._lock, db._conn() as c:
                    out = auth_mod.google_login(c, body.get("credential", ""),
                                                GOOGLE_CLIENT_ID)
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


def main():
    threading.Thread(target=_sync_loop, daemon=True,
                     name="github-sync").start()
    threading.Thread(target=_sentinel_loop, daemon=True,
                     name="repo-sentinel").start()
    port = int(os.environ.get("PORT", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TraceMind on http://localhost:{port} "
          f"(backend={STATE.backend_name}, database=sqlite:{DB_PATH}, "
          f"github={STATE.github_repo}, bank={BANK_ID})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
