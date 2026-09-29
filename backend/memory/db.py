"""TraceMind incident database — SQLite persistence for organizational memory.

Hindsight is the *semantic* memory (retain / recall / reflect over the
incident bank). This module is the *structured* database of record sitting
underneath it: every incident — seeded or learned from a real resolution —
is stored as a queryable row, and every investigation is logged.

Storage: local SQLite by default; Turso (libSQL, SQLite-compatible) when
TURSO_DATABASE_URL is set — Turso survives Render's ephemeral filesystem,
so users, login history and learned incidents are never wiped on deploy.

Tables:
  incidents      — one row per incident (full JSON blob + indexed columns)
  investigations — audit log of /api/investigate calls (query, matches)
  users / login_events / user_github / follows — accounts (via auth.py)

Thread-safe via a write lock; short-lived connections per operation so it
works under ThreadingHTTPServer.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id            TEXT PRIMARY KEY,
  title         TEXT,
  service       TEXT,
  severity      TEXT,
  error_signature TEXT,
  root_cause    TEXT,
  fix           TEXT,
  engineer      TEXT,
  mttr_minutes  INTEGER,
  started_at    TEXT,
  resolved_at   TEXT,
  outcome       TEXT,
  source        TEXT DEFAULT 'seed',
  symptoms_json TEXT,
  investigation_steps_json TEXT,
  commands_used_json TEXT,
  deployment_json TEXT,
  git_commit    TEXT,
  logs_snippet  TEXT,
  full_json     TEXT NOT NULL,
  created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_incidents_service  ON incidents(service);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS idx_incidents_resolved ON incidents(resolved_at);

CREATE TABLE IF NOT EXISTS investigations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  query_text  TEXT,
  service     TEXT,
  matches_json TEXT,
  created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- GitHub Issues pipeline state: which issues have been synced, and when.
CREATE TABLE IF NOT EXISTS github_sync (
  repo             TEXT NOT NULL,
  issue_number     INTEGER NOT NULL,
  incident_id      TEXT NOT NULL,
  issue_updated_at TEXT DEFAULT '',
  issue_state      TEXT DEFAULT '',
  synced_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (repo, issue_number)
);

-- small key/value store (last sync time, connected repo, ...)
CREATE TABLE IF NOT EXISTS app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

_ID_RE = re.compile(r"INC-(\d+)")


def _j(v: Any) -> str:
    return json.dumps(v or [])


def _open_conn(path: str):
    """Open a database connection.

    Durable mode: when TURSO_DATABASE_URL (+ optional TURSO_AUTH_TOKEN) is
    set, connect to Turso (libSQL, SQLite-compatible) instead of the local
    file. Render's free filesystem is ephemeral — it wipes the local SQLite
    file on every deploy/restart, which used to erase users, login history
    and learned incidents. Turso keeps them permanently.

    Falls back to local sqlite3 when the env vars are absent, so local dev
    and existing setups keep working with zero config.
    """
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    if url:
        import libsql  # vendored wheel; only imported when Turso is configured
        token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
        if url.startswith("https://"):
            url = "libsql://" + url[len("https://"):]
        if token:
            return libsql.connect(url, auth_token=token)
        return libsql.connect(url)
    c = sqlite3.connect(path, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _db_label(path: str) -> str:
    if os.environ.get("TURSO_DATABASE_URL", "").strip():
        return "turso"
    return f"sqlite:{path}"


class IncidentDB:
    """SQLite store of record for incidents + investigation audit log."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return _open_conn(self.path)

    # -- incidents -------------------------------------------------------
    def upsert_incident(self, incident: dict[str, Any], source: str = "seed") -> str:
        inc_id = incident.get("id")
        if not inc_id:
            inc_id = self.next_id()
            incident = dict(incident, id=inc_id)
        row = (
            inc_id,
            incident.get("title"), incident.get("service"),
            incident.get("severity"), incident.get("error_signature"),
            incident.get("root_cause"), incident.get("fix"),
            incident.get("engineer"), incident.get("mttr_minutes"),
            incident.get("started_at"), incident.get("resolved_at"),
            incident.get("outcome"), source,
            _j(incident.get("symptoms")),
            _j(incident.get("investigation_steps")),
            _j(incident.get("commands_used")),
            json.dumps(incident.get("deployment") or {}),
            incident.get("git_commit"), incident.get("logs_snippet"),
            json.dumps(incident),
        )
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO incidents
                   (id,title,service,severity,error_signature,root_cause,fix,
                    engineer,mttr_minutes,started_at,resolved_at,outcome,source,
                    symptoms_json,investigation_steps_json,commands_used_json,
                    deployment_json,git_commit,logs_snippet,full_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, service=excluded.service,
                    severity=excluded.severity,
                    error_signature=excluded.error_signature,
                    root_cause=excluded.root_cause, fix=excluded.fix,
                    engineer=excluded.engineer, mttr_minutes=excluded.mttr_minutes,
                    started_at=excluded.started_at, resolved_at=excluded.resolved_at,
                    outcome=excluded.outcome,
                    symptoms_json=excluded.symptoms_json,
                    investigation_steps_json=excluded.investigation_steps_json,
                    commands_used_json=excluded.commands_used_json,
                    deployment_json=excluded.deployment_json,
                    git_commit=excluded.git_commit, logs_snippet=excluded.logs_snippet,
                    full_json=excluded.full_json""",
                row,
            )
        return inc_id

    def get(self, incident_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT full_json FROM incidents WHERE id=?", (incident_id,)
            ).fetchone()
        return json.loads(r["full_json"]) if r else None

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def next_id(self) -> str:
        """Next INC-#### id after the highest existing one."""
        with self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM incidents").fetchall()]
        nums = [int(m.group(1)) for i in ids if (m := _ID_RE.search(i or ""))]
        return f"INC-{max(nums, default=0) + 1:04d}"

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT full_json FROM incidents "
                "ORDER BY resolved_at DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["full_json"]) for r in rows]

    def list(self, limit: int = 50, offset: int = 0,
             service: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT full_json FROM incidents"
        args: list[Any] = []
        if service:
            q += " WHERE service=?"
            args.append(service)
        q += " ORDER BY resolved_at DESC, created_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [json.loads(r["full_json"]) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            by_service = dict(
                c.execute("SELECT service, COUNT(*) FROM incidents GROUP BY service")
                .fetchall()
            )
            by_severity = dict(
                c.execute("SELECT severity, COUNT(*) FROM incidents GROUP BY severity")
                .fetchall()
            )
            avg_mttr = c.execute(
                "SELECT AVG(mttr_minutes) FROM incidents WHERE mttr_minutes IS NOT NULL"
            ).fetchone()[0]
            inv = c.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
        return {
            "total_incidents": total,
            "by_service": by_service,
            "by_severity": by_severity,
            "avg_mttr_minutes": round(avg_mttr, 1) if avg_mttr is not None else None,
            "investigations_logged": inv,
        }

    # -- investigations audit log ----------------------------------------
    def log_investigation(self, query_text: str, service: str | None,
                          matches: list[dict[str, Any]]) -> int:
        slim = [
            {"id": m["incident"].get("id"),
             "title": m["incident"].get("title"),
             "score": m.get("score")}
            for m in (matches or [])
        ]
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO investigations (query_text, service, matches_json)"
                " VALUES (?,?,?)",
                (query_text[:4000], service, json.dumps(slim)),
            )
            return cur.lastrowid or 0

    def recent_investigations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, query_text, service, matches_json, created_at"
                " FROM investigations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r["id"], "query": r["query_text"], "service": r["service"],
             "matches": json.loads(r["matches_json"] or "[]"),
             "at": r["created_at"]}
            for r in rows
        ]

    # -- github sync state -------------------------------------------------
    def record_github_sync(self, repo: str, issue_number: int, incident_id: str,
                           issue_updated_at: str, issue_state: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO github_sync
                   (repo, issue_number, incident_id, issue_updated_at,
                    issue_state)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(repo, issue_number) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    issue_updated_at=excluded.issue_updated_at,
                    issue_state=excluded.issue_state,
                    synced_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (repo, issue_number, incident_id, issue_updated_at,
                 issue_state),
            )

    def get_github_sync(self, repo: str,
                        issue_number: int) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM github_sync WHERE repo=? AND issue_number=?",
                (repo, issue_number),
            ).fetchone()
        return dict(r) if r else None

    def github_sync_counts(self, repo: str) -> dict[str, int]:
        with self._conn() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM github_sync WHERE repo=?", (repo,)
            ).fetchone()[0]
            open_n = c.execute(
                "SELECT COUNT(*) FROM github_sync WHERE repo=? AND issue_state='open'",
                (repo,),
            ).fetchone()[0]
        return {"synced": total, "open": open_n, "closed": total - open_n}

    # -- app meta (key/value) ----------------------------------------------
    def meta_get(self, key: str) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT value FROM app_meta WHERE key=?",
                          (key,)).fetchone()
        return r["value"] if r else None

    def meta_set(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO app_meta (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
