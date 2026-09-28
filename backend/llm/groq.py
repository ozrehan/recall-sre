"""Optional Groq-backed briefing synthesizer.

When GROQ_API_KEY is set, the agent's recommendation body is written by an
LLM grounded in the recalled incidents (IDs, root causes, fixes, MTTR are
injected into the prompt — the model explains, it never invents history).
Without a key, the agent falls back to template briefings; the demo never
breaks.

Stdlib only: calls the Groq OpenAI-compatible chat API via urllib.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

MODEL = "qwen/qwen3-32b"  # fast, generous free tier; swap via GROQ_MODEL
API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = (
    "You are TraceMind, an SRE assistant. You MUST ground every claim in the "
    "past incidents provided. Cite incident IDs. Frame recommendations as "
    "hypotheses, never certainties: explicitly warn that similar symptoms can "
    "have different root causes. Keep it under 120 words, plain language, "
    "no markdown headers."
)


def _prompt(draft: dict[str, Any], matches: list[dict[str, Any]]) -> str:
    lines = [
        f"New incident: {draft.get('title')} on {draft.get('service')} "
        f"({draft.get('severity')}).",
        f"Error signature: {draft.get('error_signature')}",
        "Symptoms: " + "; ".join(draft.get("symptoms", [])[:6]),
        "",
        "Similar past incidents from organizational memory:",
    ]
    for m in matches[:3]:
        inc = m["incident"]
        lines.append(
            f"- {inc.get('id')} ({m['score']:.0%} relevance): {inc.get('title')}. "
            f"Root cause was: {inc.get('root_cause')}. "
            f"Fixed by: {inc.get('fix')}. MTTR {inc.get('mttr_minutes')} min."
        )
    lines.append("")
    lines.append(
        "Write the recommendation body: what the evidence suggests the cause "
        "is, and the single most useful next investigation step, with the "
        "honesty warning."
    )
    return "\n".join(lines)


class GroqBriefing:
    def __init__(self, api_key: str, model: str = MODEL):
        self.api_key = api_key
        self.model = model

    def synthesize_briefing(
        self, draft: dict[str, Any], matches: list[dict[str, Any]]
    ) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": _prompt(draft, matches)},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            }
        ).encode()
        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return (
                data["choices"][0]["message"]["content"].strip()
                or "LLM returned an empty briefing."
            )
        except Exception as e:
            return f"(LLM briefing unavailable: {e})"
