#!/usr/bin/env python3
"""TraceMind demo server — stdlib only, zero dependencies.

Serves the frontend dashboard and exposes the agent API:

  GET  /api/health       -> {ok, backend, memory_size, mode}
  GET  /api/incidents    -> seeded incident catalog (scenario picker)
  POST /api/investigate  -> {alert} -> {incident, matches, recommendation}
  POST /api/resolve      -> {draft..., root_cause, fix, ...} -> {id, memory_size}
  POST /api/mode         -> {mode: "trained"|"empty"} -> {mode, memory_size}
  GET  /api/memory       -> {backend, size, recent:[...]}

The "time-travel" demo mode toggles between:
  - trained: memory seeded with 28 historical incidents (Day 120)
  - empty:   blank memory (Day 1 cold start)

Memory backend selection:
  - If HINDSIGHT_URL + HINDSIGHT_API_KEY are set and the hindsight SDK is
    importable, HindsightMemoryStore is used for semantic recall.
  - Otherwise LocalMemoryStore (TF-IDF) is used — the demo never breaks.
  - Either way, every incident is ALSO stored in a local SQLite database
    (backend/memory/db.py, DB_PATH env or backend/data/tracemind.db): the
    queryable database of record plus an investigation audit log.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent.core import IncidentAgent
from backend.memory.db import IncidentDB
from backend.memory.hybrid_store import HybridMemoryStore
from backend.memory.local_store import LocalMemoryStore

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(HERE, "..", "frontend")
DATA_FILE = os.path.join(HERE, "data", "incidents.json")
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "data", "tracemind.db"))

MIME = {
    ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
}


CLOUD_URL = "https://api.hindsight.vectorize.io"


def build_memory():
    """Semantic recall layer + SQLite database of record, as one store."""
    backend_name = "local"
    try:
        from backend.memory.hindsight_store import HindsightMemoryStore
        url = os.environ.get("HINDSIGHT_URL")
        key = os.environ.get("HINDSIGHT_API_KEY")
        if key and not url:
            # API key alone implies Hindsight Cloud.
            url = CLOUD_URL
        if url or key:
            semantic = HindsightMemoryStore(url=url or CLOUD_URL, api_key=key)
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


def load_seed():
    with open(DATA_FILE) as f:
        return json.load(f)


class State:
    def __init__(self):
        self.seed_incidents = load_seed()
        mem, backend = build_memory()
        self.backend_name = backend
        llm = build_llm()
        self.trained = mem  # HybridMemoryStore: SQLite db of record + semantic recall
        self.empty = LocalMemoryStore()
        # database of record: restore from incidents.json when the db is empty
        # (Render's disk is ephemeral, so this runs on every fresh deploy)
        if self.trained.db.count() == 0:
            for inc in self.seed_incidents:
                self.trained.db.upsert_incident(dict(inc), source="seed")
        # semantic layer: seed only if it has nothing (Hindsight upsert is
        # idempotent, but 28 retains on every boot would just add latency)
        if self.trained.semantic.count() == 0:
            self.trained.semantic.seed(self.seed_incidents)
        self.mode = "trained"
        self.agents = {
            "trained": IncidentAgent(self.trained, llm=llm),
            "empty": IncidentAgent(self.empty),
        }

    def agent(self):
        return self.agents[self.mode]

    def memory(self):
        return self.trained if self.mode == "trained" else self.empty


STATE = State()


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

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            m = STATE.memory()
            db_size = m.db.count() if hasattr(m, "db") else 0
            return self._send(200, {
                "ok": True, "backend": STATE.backend_name,
                "database": "sqlite" if hasattr(m, "db") else "none",
                "mode": STATE.mode, "memory_size": m.count(),
                "db_size": db_size,
            })
        if path == "/api/incidents":
            return self._send(200, {"incidents": STATE.seed_incidents})
        if path == "/api/memory":
            m = STATE.memory()
            if hasattr(m, "db"):
                recent = m.db.recent(5)
            else:
                recent = [m.get(i) for i in
                          list(getattr(m, "_order", []))[-5:]][::-1]
                recent = [r for r in recent if r]
            return self._send(200, {
                "backend": STATE.backend_name, "mode": STATE.mode,
                "size": m.count(),
                "recent": [{"id": r["id"], "title": r["title"]} for r in recent],
            })
        if path == "/api/db/stats":
            db = STATE.trained.db
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
            db = STATE.trained.db
            return self._send(200, {
                "total": db.count(),
                "incidents": db.list(limit=limit, offset=offset, service=service),
            })
        if path.startswith("/api/db/incident/"):
            inc_id = urllib.parse.unquote(path[len("/api/db/incident/"):])
            inc = STATE.trained.db.get(inc_id)
            if inc:
                return self._send(200, {"incident": inc})
            return self._send(404, {"error": "incident not found"})
        if path == "/api/db/investigations":
            return self._send(200, {
                "investigations": STATE.trained.db.recent_investigations(20),
            })
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
                result = STATE.agent().investigate(alert)
                return self._send(200, result)
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/resolve":
            a = STATE.agent()
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
        if path == "/api/mode":
            mode = body.get("mode", "trained")
            if mode in ("trained", "empty"):
                STATE.mode = mode
            m = STATE.memory()
            return self._send(200, {"mode": STATE.mode, "memory_size": m.count()})
        return self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    port = int(os.environ.get("PORT", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TraceMind on http://localhost:{port} "
          f"(backend={STATE.backend_name}, database=sqlite:{DB_PATH}, "
          f"memory={STATE.trained.count()})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
