"""TraceMind agent core: the incident memory loop.

    NEW INCIDENT
         ↓
    analyze symptoms → build search query
         ↓
    search Hindsight memory → similar past incidents (with scores)
         ↓
    recommend → likely causes + investigation steps (never false certainty)
         ↓
    engineer resolves → post-mortem stored back to memory
         ↓
    NEXT INCIDENT = SMARTER

The agent NEVER claims certainty. It reports similarity scores and
recommends *investigation steps* drawn from what worked before, phrased as
"Incident #47 had the same signature; its root cause was X. Recommended
next step: inspect Y." — credible, not oracular.
"""
from __future__ import annotations

from typing import Any

from backend.memory.base import MemoryStore, incident_to_text


class IncidentAgent:
    def __init__(self, memory: MemoryStore, llm=None):
        self.memory = memory
        self.llm = llm  # optional Groq-backed synthesizer; None => templates

    # -- 1. analyze ------------------------------------------------------
    def analyze(self, alert: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw alert into a structured incident draft."""
        query_parts = [
            alert.get("title", ""),
            f"service {alert.get('service', '')}",
            alert.get("error_signature", ""),
            " ".join(alert.get("symptoms", [])),
            (alert.get("logs_snippet", "") or "")[:2000],
        ]
        return {
            "draft": {
                "title": alert.get("title", "Untitled incident"),
                "service": alert.get("service", "unknown"),
                "severity": alert.get("severity", "high"),
                "error_signature": alert.get("error_signature", ""),
                "symptoms": alert.get("symptoms", []),
                "logs_snippet": alert.get("logs_snippet", ""),
                "deployment": alert.get("deployment", {}),
            },
            "query_text": "\n".join(p for p in query_parts if p),
        }

    # -- 2 & 3. search + recommend ---------------------------------------
    def investigate(self, alert: dict[str, Any], top_k: int = 3) -> dict[str, Any]:
        """Full assist flow for a new incident: analyze, recall, recommend."""
        analyzed = self.analyze(alert)
        draft = analyzed["draft"]
        matches = self.memory.search_similar(analyzed["query_text"], top_k=top_k)
        recommendation = self._recommend(draft, matches)
        return {
            "incident": draft,
            "score_label": self.memory.score_label,
            "matches": [
                {
                    "id": m["incident"]["id"],
                    "title": m["incident"]["title"],
                    "service": m["incident"]["service"],
                    "score": m["score"],
                    "score_pct": round(m["score"] * 100),
                    "root_cause": m["incident"].get("root_cause", ""),
                    "fix": m["incident"].get("fix", ""),
                    "mttr_minutes": m["incident"].get("mttr_minutes"),
                    "resolved_at": m["incident"].get("resolved_at"),
                }
                for m in matches
            ],
            "recommendation": recommendation,
            "memory_size": self.memory.count(),
        }

    def _recommend(
        self, draft: dict[str, Any], matches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not matches:
            return {
                "mode": "cold_start",
                "headline": "No similar incidents in memory yet.",
                "body": (
                    "I don't have enough historical context for this signature. "
                    "Possible areas to check: database connectivity, recent "
                    "deployments, dependency health. Resolve this incident and "
                    "I'll remember it — the next similar one will get a "
                    "memory-backed recommendation."
                ),
                "suggested_steps": [
                    "Check service dashboards for error rate / latency spikes",
                    "Correlate incident start time with recent deployments",
                    "Inspect downstream dependency health",
                ],
                "confidence_note": "Cold start — no historical data.",
            }

        top = matches[0]
        top_inc = top["incident"]
        causes = []
        steps: list[str] = []
        seen_cmds: set[str] = set()
        for m in matches:
            inc = m["incident"]
            rc = inc.get("root_cause", "")
            if rc and rc not in causes:
                causes.append(rc)
            for s in inc.get("investigation_steps", [])[:2]:
                if s not in steps:
                    steps.append(s)
            for c in inc.get("commands_used", [])[:2]:
                if c not in seen_cmds:
                    seen_cmds.add(c)
                    steps.append(f"`{c}`")

        if self.llm:
            body = self.llm.synthesize_briefing(draft, matches)
        else:
            body = self._memory_briefing(draft) or (
                f"Incident {top_inc['id']} had the same error signature and "
                f"similar symptoms. Its root cause was: {top_inc.get('root_cause', 'unknown')}. "
                f"It was resolved in {top_inc.get('mttr_minutes', '?')} minutes by: "
                f"{top_inc.get('fix', 'unknown')}."
            )

        return {
            "mode": "memory_match",
            "headline": (
                f"{top['score']:.0%} {self.memory.score_label} to {top_inc['id']} "
                f"— {top_inc['title']}"
            ),
            "body": body,
            "likely_causes": causes[:3],
            "suggested_steps": steps[:6],
            "confidence_note": (
                f"Based on {len(matches)} similar past incident(s). "
                f"Top match similarity: {top['score']:.0%}. "
                "Verify before acting — similar symptoms can have different root causes."
            ),
        }

    def _memory_briefing(self, draft: dict[str, Any]) -> str:
        """LLM synthesis via Hindsight reflect — no extra API key needed.

        The semantic store's briefing() runs an evidence-grounded LLM over
        the incident bank (cites incident IDs, hedges like a hypothesis).
        Returns "" when unavailable (e.g. local TF-IDF mode) so the caller
        falls back to the template.
        """
        try:
            query = f"{draft.get('title', '')} {draft.get('error_signature', '')}".strip()
            text = self.memory.briefing(query)
            return (text or "").strip()
        except Exception as e:
            print(f"[agent] memory briefing unavailable ({e})")
            return ""

    # -- 4. learn ----------------------------------------------------------
    def resolve(
        self,
        draft: dict[str, Any],
        root_cause: str,
        fix: str,
        engineer: str,
        mttr_minutes: int,
        investigation_steps: list[str] | None = None,
        commands_used: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store the post-mortem back to memory. This is the learning step."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        incident = {
            **draft,
            "root_cause": root_cause,
            "fix": fix,
            "engineer": engineer,
            "mttr_minutes": mttr_minutes,
            "investigation_steps": investigation_steps or [],
            "commands_used": commands_used or [],
            "resolved_at": now,
            "outcome": "resolved",
        }
        inc_id = self.memory.store_incident(incident)
        return {"id": inc_id, "memory_size": self.memory.count()}
