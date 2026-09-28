"""Local (dependency-free) memory store using TF-IDF cosine similarity.

This is the offline fallback / dev implementation of the MemoryStore
interface. It gives honest, deterministic similarity scores so the demo
works with zero credentials, while the Hindsight backend is used whenever
a Hindsight instance is configured.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .base import MemoryStore, incident_to_text

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class LocalMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    # -- writes --------------------------------------------------------
    def store_incident(self, incident: dict[str, Any]) -> str:
        inc_id = incident.get("id") or f"INC-{len(self._docs) + 1:04d}"
        incident = dict(incident)
        incident["id"] = inc_id
        self._docs[inc_id] = incident
        if inc_id not in self._order:
            self._order.append(inc_id)
        return inc_id

    # -- reads ---------------------------------------------------------
    def get(self, incident_id: str) -> dict[str, Any] | None:
        return self._docs.get(incident_id)

    def count(self) -> int:
        return len(self._docs)

    def search_similar(
        self,
        query_text: str,
        top_k: int = 3,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._docs:
            return []
        # Build TF-IDF over the corpus + query
        ids = [i for i in self._order if not service or self._docs[i].get("service") == service]
        texts = [incident_to_text(self._docs[i]) for i in ids]
        q_tokens = _tokenize(query_text)
        if not q_tokens:
            return []

        doc_tokens = [_tokenize(t) for t in texts]
        # document frequency
        df: Counter[str] = Counter()
        for toks in doc_tokens:
            for tok in set(toks):
                df[tok] += 1
        n = len(doc_tokens)

        def idf(tok: str) -> float:
            return math.log((n + 1) / (df.get(tok, 0) + 1)) + 1.0

        def tfidf_vector(toks: list[str]) -> dict[str, float]:
            tf = Counter(toks)
            total = len(toks) or 1
            return {t: (c / total) * idf(t) for t, c in tf.items()}

        def norm(vec: dict[str, float]) -> float:
            return math.sqrt(sum(v * v for v in vec.values())) or 1e-9

        q_vec = tfidf_vector(q_tokens)
        q_norm = norm(q_vec)
        scored = []
        for doc_id, toks in zip(ids, doc_tokens):
            d_vec = tfidf_vector(toks)
            dot = sum(q_vec.get(t, 0.0) * d_vec.get(t, 0.0) for t in q_vec)
            score = dot / (q_norm * norm(d_vec))
            # small boost when the service matches — same-service incidents
            # are operationally more relevant
            scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {"incident": self._docs[doc_id], "score": round(score, 4)}
            for doc_id, score in scored[:top_k]
            if score > 0
        ]
