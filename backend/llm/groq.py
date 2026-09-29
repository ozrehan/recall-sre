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

# Groq retires models often; groq_chat tries each in order and uses the first
# one that answers. Swap via GROQ_MODEL env if you want to pin one.
MODELS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
]
MODEL = MODELS[0]
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


CHAT_SYSTEM = (
    "You are Trace, the friendly AI assistant inside TraceMind — a website that "
    "turns software incidents into searchable organizational memory.\n"
    "What TraceMind does:\n"
    "- Investigate: paste an alert, error, or stack trace and Trace breaks it down, "
    "searches past incidents for similar ones, and recommends a fix.\n"
    "- Organizational memory: every resolved incident is remembered and recalled "
    "for future ones, with relevance scores and honesty about uncertainty.\n"
    "- GitHub: connect repositories; a sentinel watches CI/workflow runs and files "
    "incidents automatically; optional Auto-Fix opens a pull request with a fix. "
    "Push code: the user can edit any repo file in the GitHub panel's Push code "
    "section and TraceMind commits it to a new branch and opens a pull request "
    "(never pushes to main directly).\n"
    "- Profiles: each user has a profile page with stats (repos, issues, solved), "
    "social links, and a shareable link.\n"
    "- Activity panel: a timeline of fired and resolved incidents.\n"
    "Answer the user's question directly and concisely, like a helpful AI "
    "assistant. Keep it under 120 words, plain language, no markdown headers. "
    "If they describe something broken (an error, alert, or outage), tell them "
    "to paste the error here so you can investigate it as an incident. "
    "If they ask you to change or update code in their repo, say yes — just "
    "describe the change in the chat and the site's agent will plan it, show a "
    "diff for approval, then commit it to a new branch and open a pull request. "
    "They can also edit files manually in the GitHub panel's Push code section."
)


def groq_chat(api_key: str, system: str, user: str,
              model: str | None = None, max_tokens: int = 350) -> str:
    """One-shot chat completion via Groq's OpenAI-compatible API.

    Tries each known model in order; Groq retires models often, so a 404
    (model gone) just moves to the next candidate instead of failing.
    """
    candidates = [model] if model else list(MODELS)
    last_err: Exception | None = None
    for cand in candidates:
        try:
            return _groq_chat_once(api_key, system, user, cand, max_tokens)
        except RuntimeError as e:
            msg = str(e)
            # retired model (404) or rate-limited (429): try the next model
            if "404" not in msg and "does not exist" not in msg and "429" not in msg:
                raise
            last_err = e
    raise last_err or RuntimeError("no Groq model available")


def _groq_chat_once(api_key: str, system: str, user: str,
                    model: str, max_tokens: int) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.5,
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Groq sits behind Cloudflare, which 403s Python's default
            # urllib User-Agent as a bot before auth is even checked.
            "User-Agent": "TraceMind/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        raise RuntimeError(f"Groq HTTP {e.code} model={model}: {detail}")
    return (data["choices"][0]["message"]["content"] or "").strip()


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
                # Groq sits behind Cloudflare, which 403s Python's default
                # urllib User-Agent as a bot before auth is even checked.
                "User-Agent": "TraceMind/1.0",
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
