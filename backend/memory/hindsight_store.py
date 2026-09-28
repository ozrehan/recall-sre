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

import asyncio
import json
import threading
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


class _HindsightBridge:
    """Own the SDK client on one dedicated thread + event loop.

    The SDK caches a single aiohttp session bound to the event loop that
    created it. Our server handles each request on a different thread, so
    calling the SDK straight from request threads reuses that session on
    the wrong loop — aiohttp then raises
    "Timeout context manager should be used inside a task".
    This bridge creates the client on its own loop and marshals every
    call to it via run_coroutine_threadsafe, using the SDK's async API.
    """

    def __init__(self, url: str, api_key: str | None, bank_id: str):
        self._url = url
        self._api_key = api_key
        self._bank_id = bank_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name="hindsight-io", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("Hindsight bridge thread failed to start")
        if self._error is not None:
            raise self._error

    # -- runs on the bridge thread -------------------------------------
    def _serve(self) -> None:
        try:
            from hindsight_client import Hindsight

            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            kwargs: dict[str, Any] = {"base_url": self._url, "timeout": 60.0}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            # Sync constructor is fine here: the loop isn't running yet, so
            # the SDK's internal run_until_complete works.
            self._client = Hindsight(**kwargs)
            self._loop.run_until_complete(self._ensure_bank())
        except BaseException as e:  # noqa: BLE001 — surfaced to the caller
            self._error = e
        finally:
            self._ready.set()
        if self._client is not None and self._loop is not None:
            self._loop.run_forever()

    async def _ensure_bank(self) -> None:
        try:
            await self._client.acreate_bank(
                bank_id=self._bank_id,
                name="Incident Memory",
                mission=BANK_MISSION,
                reflect_mission=REFLECT_DIRECTIVE,
            )
        except Exception as e:
            # Bank probably already exists — make sure the directive is set.
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                try:
                    await self._client.aupdate_bank_config(
                        self._bank_id, reflect_mission=REFLECT_DIRECTIVE
                    )
                except Exception:
                    pass
            else:
                raise

    # -- called from any thread ----------------------------------------
    def call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Run an async SDK method on the bridge loop; return its result."""
        assert self._loop is not None and self._client is not None

        async def _invoke() -> Any:
            return await getattr(self._client, method_name)(*args, **kwargs)

        future = asyncio.run_coroutine_threadsafe(_invoke(), self._loop)
        return future.result(timeout=180)


class HindsightMemoryStore(MemoryStore):
    """MemoryStore backed by a real Hindsight instance."""

    score_label = "relevance"

    def __init__(
        self,
        url: str = "https://api.hindsight.vectorize.io",
        api_key: str | None = None,
        bank_id: str = BANK_ID,
    ):
        # api_key is optional: Hindsight Cloud requires one, but a
        # self-hosted instance may run without auth.
        self.bank_id = bank_id
        self._bridge = _HindsightBridge(url, api_key, bank_id)

    # -- writes ----------------------------------------------------------
    def store_incident(self, incident: dict[str, Any]) -> str:
        inc_id = incident.get("id") or f"INC-{self.count() + 1:04d}"
        incident = dict(incident)
        incident["id"] = inc_id
        self._bridge.call(
            "aretain",
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
        # NOTE: prefer_observations must stay False. With True, recall returns
        # consolidated "observation" results that carry no document_id and no
        # incident_json metadata, so they degrade into junk lightweight cards
        # (UUID ids, truncated summary text) instead of real incident matches.
        # Raw world/experience facts carry document_id + incident_json.
        resp = self._bridge.call(
            "arecall",
            bank_id=self.bank_id,
            query=query,
            types=["world", "experience", "observation"],
            budget="high",
            prefer_observations=False,
            tags=tags,
            tags_match="any" if tags else "any",
        )
        # fetch extra: dedup by incident below can collapse several facts
        # from the same incident into one card
        results = list(resp.results or [])[: max(top_k * 3, top_k)]
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
        seen_ids: set[str] = set()
        for r, final in zip(results, finals):
            meta = r.metadata or {}
            doc_id = r.document_id or ""
            if not doc_id and not meta.get("incident_json"):
                # Unattributable result (e.g. a consolidated observation with
                # no source document link) — cannot become an incident match.
                continue
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
            inc_key = str(incident.get("id") or "")
            if inc_key in seen_ids:
                # multiple recalled facts can belong to the same incident —
                # keep only the highest-scoring card per incident
                continue
            seen_ids.add(inc_key)
            score = (final / max_final) if max_final > 0 else 0.0
            out.append({"incident": incident, "score": round(score, 4)})
            if len(out) >= top_k:
                break
        return out

    def get(self, incident_id: str) -> dict[str, Any] | None:
        try:
            resp = self._bridge.call(
                "alist_memories",
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
        """Number of distinct incidents remembered (via metadata.incident_json)."""
        try:
            seen: set[str] = set()
            offset = 0
            while True:
                resp = self._bridge.call(
                    "alist_memories", self.bank_id, limit=100, offset=offset
                )
                units = getattr(resp, "items", None) or []
                if not units:
                    break
                for u in units:
                    meta = getattr(u, "metadata", None) or {}
                    raw = meta.get("incident_json")
                    if raw:
                        try:
                            inc = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        if inc.get("id"):
                            seen.add(inc["id"])
                total = getattr(resp, "total", 0) or 0
                offset += len(units)
                if offset >= total or len(units) < 100:
                    break
            if seen:
                return len(seen)
            # fall back to raw unit count so the number is never misleadingly 0
            return total
        except Exception:
            return 0

    # -- reflect: evidence-grounded briefing -------------------------------
    def briefing(self, query: str) -> str:
        """One-shot evidence-grounded synthesis via Hindsight reflect."""
        resp = self._bridge.call(
            "areflect", bank_id=self.bank_id, query=query, budget="mid"
        )
        return getattr(resp, "text", "") or ""
