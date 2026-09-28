"""Hindsight-backed memory store — the real organizational memory.

Uses the official ``hindsight-client`` SDK (``pip install hindsight-client``)
against Hindsight Cloud (https://api.hindsight.vectorize.io) or a
self-hosted instance.

Mapping:
  incident  -> retain() as a document (document_id="incident-<id>",
               idempotent: re-retaining replaces)
  search    -> recall() over world/experience/observation facts, ranked by
               Hindsight's TEMPR engine (semantic + BM25 + graph + temporal)
  reflect   -> available via client.reflect for evidence-grounded briefings

Scores: Hindsight returns ranking scores (scores.final), not probabilities,
so this adapter reports them as *relevance* normalized to the top hit —
never as a fake "similarity %". The UI labels them accordingly.
"""
from __future__ import annotations

import json
from typing import Any

from .base import MemoryStore, incident_to_text

BANK_ID = "incident-memory"

BANK_MISSION = (
    "Record production incidents for this engineering organization: "
    "error signatures, symptoms, timelines, deployments, root causes, "
    "investigation steps, commands used, fixes, and MTTR. This bank is the "
    "organization's incident memory — every resolved incident must make the "
    "next similar incident faster to diagnose."
)

REFLECT_DIRECTIVE = (
    "Frame every recommendation as a similarity hypothesis grounded in "
    "specific past incidents — cite incident IDs and their relevance. "
    "Never present a root cause as guaranteed: similar symptoms can have "
    "different root causes. Recommend investigation steps drawn from what "
    "worked before, ordered by evidence strength."
)


def _postmortem_text(incident: dict[str, Any]) -> str:
    dep = incident.get("deployment", {}) or {}
    lines = [
        f"Incident {incident.get('id')}: {incident.get('title')}",
        f"Service: {incident.get('service')} | Severity: {incident.get('severity')}",
        f"Error signature: {incident.get('error_signature')}",
        "Symptoms: " + "; ".join(incident.get("symptoms", [])),
        f"Deployment at incident time: {dep.get('version')} (deployed {dep.get('deployed_at')})",
        f"Root cause: {incident.get('root_cause')}",
        "Investigation steps: " + "; ".join(incident.get("investigation_steps", [])),
        "Commands used: " + "; ".join(incident.get("commands_used", [])),
        f"Fix: {incident.get('fix')}",
        f"Resolved by {incident.get('engineer')} in {incident.get('mttr_minutes')} minutes.",
    ]
    return "\n".join(lines)


class HindsightMemoryStore(MemoryStore):
    """MemoryStore backed by a real Hindsight instance."""

    score_label = "relevance"

    def __init__(
        self,
        url: str = "https://api.hindsight.vectorize.io",
        api_key: str | None = None,
        bank_id: str = BANK_ID,
    ):
        from hindsight_client import Hindsight

        # api_key is optional: Hindsight Cloud requires one, but a
        # self-hosted instance may run without auth.
        kwargs: dict[str, Any] = {"base_url": url, "timeout": 60.0}
        if api_key:
            kwargs["api_key"] = api_key
        self.client = Hindsight(**kwargs)
        self.bank_id = bank_id
        self._ensure_bank()

    # -- setup ---------------------------------------------------------
    def _ensure_bank(self) -> None:
        try:
            self.client.create_bank(
                bank_id=self.bank_id,
                name="Incident Memory",
                mission=BANK_MISSION,
                reflect_mission=REFLECT_DIRECTIVE,
            )
        except Exception as e:
            # Bank probably already exists — make sure the directive is set.
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                try:
                    self.client.update_bank_config(
                        self.bank_id, reflect_mission=REFLECT_DIRECTIVE
                    )
                except Exception:
                    pass
            else:
                raise

    # -- writes ----------------------------------------------------------
    def store_incident(self, incident: dict[str, Any]) -> str:
        inc_id = incident.get("id") or f"INC-{self.count() + 1:04d}"
        incident = dict(incident)
        incident["id"] = inc_id
        self.client.retain(
            bank_id=self.bank_id,
            content=_postmortem_text(incident),
            context="production incident",
            timestamp=incident.get("resolved_at"),
            document_id=f"incident-{inc_id}",
            metadata={
                "incident_json": json.dumps(incident),
                "service": str(incident.get("service", "")),
                "severity": str(incident.get("severity", "")),
            },
            tags=[
                f"service:{incident.get('service', 'unknown')}",
                f"severity:{incident.get('severity', 'unknown')}",
            ],
            retain_async=False,  # synchronous: demo-safe, no ingestion lag
        )
        return inc_id

    # -- reads -----------------------------------------------------------
    def search_similar(
        self,
        query_text: str,
        top_k: int = 3,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        # recall() rejects queries over ~500 tokens — keep it tight
        query = query_text[:1500]
        tags = [f"service:{service}"] if service else None
        resp = self.client.recall(
            bank_id=self.bank_id,
            query=query,
            types=["world", "experience", "observation"],
            budget="high",
            prefer_observations=True,
            tags=tags,
            tags_match="any" if tags else "any",
        )
        results = list(resp.results or [])[:top_k]
        max_final = 0.0
        finals = []
        for r in results:
            f = None
            try:
                f = float(r.scores.final) if r.scores and r.scores.final is not None else None
            except (TypeError, ValueError):
                f = None
            finals.append(f if f is not None else 0.0)
        max_final = max(finals) if finals else 0.0

        out = []
        for r, final in zip(results, finals):
            meta = r.metadata or {}
            incident = None
            if meta.get("incident_json"):
                try:
                    incident = json.loads(meta["incident_json"])
                except (TypeError, ValueError):
                    incident = None
            if incident is None:
                # fall back to a lightweight card from the recalled fact
                incident = {
                    "id": (r.document_id or "").replace("incident-", "") or r.id,
                    "title": (r.text or "")[:120],
                    "service": meta.get("service", ""),
                    "severity": meta.get("severity", ""),
                    "root_cause": r.text or "",
                    "fix": "",
                }
            score = (final / max_final) if max_final > 0 else 0.0
            out.append({"incident": incident, "score": round(score, 4)})
        return out

    def get(self, incident_id: str) -> dict[str, Any] | None:
        try:
            resp = self.client.list_memories(
                self.bank_id, search_query=f"incident-{incident_id}", limit=10
            )
            units = getattr(resp, "items", None) or []
            for u in units:
                meta = getattr(u, "metadata", None) or {}
                if meta.get("incident_json"):
                    try:
                        inc = json.loads(meta["incident_json"])
                    except (TypeError, ValueError):
                        continue
                    if inc.get("id") == incident_id:
                        return inc
        except Exception:
            pass
        return None

    def count(self) -> int:
        try:
            resp = self.client.list_memories(self.bank_id, limit=1000)
            units = getattr(resp, "items", None) or []
            docs = {getattr(u, "document_id", None) for u in units}
            docs.discard(None)
            return len(docs)
        except Exception:
            return 0

    # -- reflect: evidence-grounded briefing -------------------------------
    def briefing(self, query: str) -> str:
        """One-shot evidence-grounded synthesis via Hindsight reflect."""
        resp = self.client.reflect(bank_id=self.bank_id, query=query, budget="mid")
        return getattr(resp, "text", "") or ""
