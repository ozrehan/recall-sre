"""Hybrid memory: SQLite database of record + semantic store for recall.

TraceMind's memory has two layers, each doing what it's best at:

  * SQLite (IncidentDB, db.py) — the durable, queryable database of record.
    Every incident is stored as a structured row; every investigation is
    logged. ``get`` / ``count`` / stats read from here — fast, no network.
  * Hindsight (or the local TF-IDF fallback) — the semantic layer.
    ``search_similar`` delegates here for ranked recall of past incidents.

Writes go to BOTH layers: ``store_incident`` mirrors the incident into
SQLite and retains it into the semantic store. If the semantic layer is
temporarily unreachable, the write still lands in the database and recall
degrades to whatever the semantic layer has — the database never loses data.
"""
from __future__ import annotations

from typing import Any

from .base import MemoryStore
from .db import IncidentDB


class HybridMemoryStore(MemoryStore):
    """MemoryStore backed by SQLite + a semantic recall layer."""

    def __init__(self, semantic: MemoryStore, db_path: str):
        self.semantic = semantic
        self.db = IncidentDB(db_path)
        # instance attribute shadows the class-level score_label
        self.score_label = semantic.score_label

    # -- writes: mirror to both layers -----------------------------------
    def store_incident(self, incident: dict[str, Any]) -> str:
        inc = dict(incident)
        if not inc.get("id"):
            inc["id"] = self.db.next_id()
        # database first — it must never lose a write
        self.db.upsert_incident(inc, source=inc.get("source", "user"))
        try:
            self.semantic.store_incident(inc)
        except Exception as e:
            print(f"[memory] semantic retain failed ({e}); kept in database")
        return inc["id"]

    def seed(self, incidents: list[dict[str, Any]]) -> None:
        for inc in incidents:
            self.store_incident(dict(inc, source="seed"))

    # -- reads -----------------------------------------------------------
    def search_similar(
        self,
        query_text: str,
        top_k: int = 3,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        matches = self.semantic.search_similar(
            query_text, top_k=top_k, service=service
        )
        try:
            self.db.log_investigation(query_text, service, matches)
        except Exception as e:
            print(f"[memory] investigation log failed ({e})")
        return matches

    def get(self, incident_id: str) -> dict[str, Any] | None:
        return self.db.get(incident_id)

    def count(self) -> int:
        return self.db.count()

    def briefing(self, query: str) -> str:
        fn = getattr(self.semantic, "briefing", None)
        if callable(fn):
            return fn(query)
        raise AttributeError("semantic store has no briefing()")
