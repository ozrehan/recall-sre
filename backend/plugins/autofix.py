"""Auto-Fix: turns Sentinel findings into pull requests with repairs.

When Sentinel reports a failing build and this plugin is enabled, Trace:
  1. pulls the failure details (failed check output / workflow job)
  2. asks the LLM to diagnose and write a minimal fix
  3. opens a PR on a `tracemind-autofix-*` branch — never pushes to main

Requires GITHUB_TOKEN and the Groq LLM. Every step is defensive: any
failure is recorded and the scan simply moves on.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

from . import github_api as gh
from . import is_enabled

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3-32b"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _groq_fix(prompt: str, api_key: str) -> dict | None:
    """Ask Groq for a JSON fix plan: {diagnosis, files:[{path, content}]}."""
    system = (
        "You are Trace, a senior engineer fixing a broken CI build. "
        "Reply with ONLY a JSON object: "
        '{"diagnosis": "<one sentence>", '
        '"files": [{"path": "<repo-relative path>", '
        '"content": "<complete new file content>"}]}. '
        "Keep fixes minimal and safe. If you cannot fix it confidently, "
        'reply {"diagnosis": "<reason>", "files": []}.'
    )
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt[:6000]},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
    }).encode()
    req = urllib.request.Request(
        GROQ_URL, data=payload,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        # tolerate code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        plan = json.loads(text)
        if isinstance(plan.get("files"), list):
            return plan
    except Exception as e:
        print(f"[autofix] groq failed: {e}")
    return None


def _failure_context(repo: str, problem: dict, token: str | None) -> str:
    """Gather the most useful failure text for the LLM."""
    parts = [f"Repository: {repo}",
             f"Problem: {problem.get('title')}"]
    run_id = problem.get("run_id")
    if run_id and token:
        try:
            jobs = gh.failed_jobs(repo, run_id, token)
            for j in jobs[:2]:
                parts.append(f"Failed job: {j.get('name')}")
                for s in (j.get("steps") or [])[-6:]:
                    if (s.get("conclusion") or "") == "failure":
                        parts.append(f"  failed step: {s.get('name')}")
        except Exception as e:
            parts.append(f"(could not fetch jobs: {e})")
    return "\n".join(parts)


def _candidate_files(repo: str, branch: str, token: str | None) -> dict:
    """Fetch a few likely-relevant files for context."""
    paths = ["render.yaml", "requirements.txt", "backend/server.py",
             "package.json", ".github/workflows"]
    out = {}
    for p in paths:
        f = gh.get_file(repo, p, branch, token)
        if f:
            out[p] = f["content"][:3000]
    return out


def attempt_fix(state, problem: dict) -> dict[str, Any]:
    """Try to fix one sentinel problem via a PR. Returns outcome dict."""
    db = state.memory.db
    repo = state.github_repo
    token = state.github_token
    out: dict[str, Any] = {"at": _now(), "problem": problem.get("title"),
                           "fixed": False}
    if not is_enabled(db, "autofix"):
        out["skipped"] = "autofix disabled"
        return out
    # per-user access mode: read-only connections never push code
    try:
        _mode = state.gh_mode_for(None)
    except Exception:
        _mode = db.meta_get("github_access_mode") or "write"
    if _mode != "write":
        out["skipped"] = "GitHub is in read-only mode"
        return out
    if not token:
        out["skipped"] = "GITHUB_TOKEN not configured"
        return out
    import os
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        out["skipped"] = "GROQ_API_KEY not configured"
        return out

    try:
        info = gh.get_repo(repo, token)
        branch = info.get("default_branch") or "main"
        head = gh.latest_commit(repo, branch, token)
        sha = head["sha"]

        context = _failure_context(repo, problem, token)
        files = _candidate_files(repo, branch, token)
        ctx_files = "\n\n".join(f"--- {p} ---\n{c}"
                                for p, c in files.items())
        plan = _groq_fix(
            f"{context}\n\nRepo files for context:\n{ctx_files}",
            groq_key)
        if not plan or not plan.get("files"):
            out["skipped"] = (plan or {}).get("diagnosis",
                                              "LLM could not produce a fix")
            return out

        fix_branch = ("tracemind-autofix-"
                      + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
        gh.create_branch(repo, fix_branch, sha, token)
        changed = []
        for f in plan["files"][:5]:
            path = (f.get("path") or "").lstrip("/")
            content = f.get("content") or ""
            if not path or not content or ".." in path:
                continue
            existing = gh.get_file(repo, path, branch, token)
            gh.update_file(repo, path, content,
                           f"TraceMind auto-fix: {plan['diagnosis'][:72]}",
                           fix_branch,
                           existing["sha"] if existing else None, token)
            changed.append(path)
        if not changed:
            out["skipped"] = "no safe file changes produced"
            return out
        pr = gh.open_pr(
            repo,
            f"[TraceMind Auto-Fix] {plan['diagnosis'][:80]}",
            f"Automated fix by TraceMind's Auto-Fix plugin.\n\n"
            f"**Diagnosis:** {plan['diagnosis']}\n\n"
            f"**Triggered by:** {problem.get('title')}\n"
            f"**Changed files:** {', '.join(changed)}\n\n"
            f"_Please review before merging._",
            fix_branch, branch, token)
        out.update({"fixed": True, "pr": pr.get("html_url"),
                    "diagnosis": plan["diagnosis"], "files": changed})
        db.meta_set("autofix_last", json.dumps(out)[:2000])
    except Exception as e:
        out["error"] = str(e)[:200]
        print(f"[autofix] failed: {e}")
    return out
