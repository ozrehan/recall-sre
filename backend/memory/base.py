"""Memory-store abstraction for RecallSRE.

The agent talks ONLY to the ``MemoryStore`` interface defined here.
Two implementations exist:

* ``LocalMemoryStore`` (local_store.py) — pure-Python TF-IDF similarity,
  zero dependencies. Used for local dev, tests, and as a demo fallback.
* ``HindsightMemoryStore`` (hindsight_store.py) — the real Hindsight
  backend (Cloud or self-hosted). Used in production / hackathon demo.

Both return similarity scores in [0, 1] so the UI can honestly present
"94% similar to INC-0047" style matches — never false certainty.
"""
from __future__ import annotations

import abc
from typing import Any


def incident_to_text(incident: dict[str, Any]) -> str:
    """Serialize an incident into searchable text for the memory layer."""
    parts = [
        incident.get("title", ""),
        f"service {incident.get('service', '')}",
        f"severity {incident.get('severity', '')}",
        incident.get("error_signature", ""),
        " ".join(incident.get("symptoms", [])),
        incident.get("root_cause", ""),
        incident.get("fix", ""),
        " ".join(incident.get("investigation_steps", [])),
    ]
    return "\n".join(p for p in parts if p)


class MemoryStore(abc.ABC):
    """Abstract organizational memory for production incidents."""

    #: How the UI should label match scores: "similarity" (true metric,
    #: e.g. cosine) or "relevance" (ranking score, e.g. Hindsight TEMPR).
    score_label = "similarity"

    @abc.abstractmethod
    def store_incident(self, incident: dict[str, Any]) -> str:
        """Persist a resolved incident. Returns its id."""
        raise NotImplementedError

    @abc.abstractmethod
    def search_similar(
        self,
        query_text: str,
        top_k: int = 3,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find past incidents similar to the query.

        Returns a list of {"incident": <incident dict>, "score": <0..1>},
        sorted by score descending.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, incident_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    # -- convenience -----------------------------------------------------
    def seed(self, incidents: list[dict[str, Any]]) -> None:
        for inc in incidents:
            self.store_incident(inc)
