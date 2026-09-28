"""TraceMind plugins: server-side automation that runs even when the site is closed.

Built-in plugins:
  sentinel  Repo Sentinel — watches the connected GitHub repo for breakage
            (failing CI, broken default branch) and files TraceMind incidents.
  autofix   Auto-Fix — when Sentinel finds a failure it can repair safely,
            it opens a pull request with the fix.

Plugin on/off state and settings live in SQLite meta so they survive
server restarts. The background threads live in backend/server.py.
"""
from __future__ import annotations

PLUGINS = {
    "sentinel": {
        "name": "Repo Sentinel",
        "description": (
            "Watches your connected GitHub repo around the clock — even with "
            "the site closed. Spots failing builds, broken checks and new "
            "bug reports, and files them as TraceMind incidents."
        ),
        "default_enabled": True,
    },
    "autofix": {
        "name": "Auto-Fix",
        "description": (
            "When Sentinel catches a broken build, Trace analyzes the failure "
            "and opens a pull request with a fix — so the repo heals itself "
            "while nobody is watching."
        ),
        "default_enabled": False,
    },
}


def is_enabled(db, plugin_id: str) -> bool:
    """Read plugin on/off state (defaults from PLUGINS)."""
    if plugin_id not in PLUGINS:
        return False
    raw = db.meta_get(f"plugin_{plugin_id}_enabled")
    if raw is None:
        return bool(PLUGINS[plugin_id]["default_enabled"])
    return raw == "1"


def set_enabled(db, plugin_id: str, enabled: bool) -> dict:
    if plugin_id not in PLUGINS:
        return {"error": f"unknown plugin: {plugin_id}"}
    db.meta_set(f"plugin_{plugin_id}_enabled", "1" if enabled else "0")
    return {"plugin": plugin_id, "enabled": bool(enabled)}


def list_plugins(db) -> list[dict]:
    return [
        {
            "id": pid,
            "name": info["name"],
            "description": info["description"],
            "enabled": is_enabled(db, pid),
        }
        for pid, info in PLUGINS.items()
    ]


def get_setting(db, key: str, default: str) -> str:
    return db.meta_get(key) or default


def set_setting(db, key: str, value: str) -> None:
    db.meta_set(key, value)
