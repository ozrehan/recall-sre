"""Extended GitHub API helpers for the plugin system.

Read-only repo health (works without a token for public repos); write
operations (branches, commits, PRs) require GITHUB_TOKEN.
"""
from __future__ import annotations

import base64
import json
import urllib.request
from typing import Any

API = "https://api.github.com"


def _headers(token: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TraceMind/1.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, token: str | None) -> Any:
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _post(url: str, token: str, data: dict) -> Any:
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_headers(token),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _put(url: str, token: str, data: dict) -> Any:
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_headers(token),
                                 method="PUT")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def test_connection(token: str | None) -> dict:
    """Verify the token: who it is and what it can do. Never exposes it."""
    if not token:
        return {"connected": False, "reason": "no token configured"}
    try:
        req = urllib.request.Request(f"{API}/user", headers=_headers(token))
        with urllib.request.urlopen(req, timeout=20) as r:
            user = json.load(r)
            scopes = r.headers.get("x-oauth-scopes", "")
        out = {
            "connected": True,
            "user": user.get("login"),
            "scopes": [x.strip() for x in scopes.split(",") if x.strip()],
            "can_write": any(x in scopes for x in ("repo", "public_repo")),
        }
        return out
    except Exception as e:
        return {"connected": False, "reason": str(e)[:120]}


def repo_permissions(repo: str, token: str | None) -> dict:
    """What the token can do on this repo (admin/push/pull)."""
    if not token:
        return {"push": False, "reason": "no token"}
    try:
        data = _get(f"{API}/repos/{repo}", token)
        perms = data.get("permissions", {})
        return {"admin": bool(perms.get("admin")),
                "push": bool(perms.get("push")),
                "pull": bool(perms.get("pull"))}
    except Exception as e:
        return {"push": False, "reason": str(e)[:120]}


# ---- read-only health -----------------------------------------------------

def get_repo(repo: str, token: str | None) -> dict:
    """Repo metadata incl. default_branch. Raises on 404."""
    return _get(f"{API}/repos/{repo}", token)


def latest_commit(repo: str, branch: str, token: str | None) -> dict:
    return _get(f"{API}/repos/{repo}/commits/{branch}?per_page=1", token)


def check_runs(repo: str, sha: str, token: str | None) -> list[dict]:
    """Combined check runs for a commit (CI status)."""
    data = _get(f"{API}/repos/{repo}/commits/{sha}/check-runs", token)
    return data.get("check_runs", [])


def combined_status(repo: str, sha: str, token: str | None) -> dict:
    return _get(f"{API}/repos/{repo}/commits/{sha}/status", token)


def recent_workflow_runs(repo: str, token: str | None,
                         per_page: int = 5) -> list[dict]:
    data = _get(f"{API}/repos/{repo}/actions/runs?per_page={per_page}", token)
    return data.get("workflow_runs", [])


def failed_jobs(repo: str, run_id: int, token: str | None) -> list[dict]:
    data = _get(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs", token)
    return [j for j in data.get("jobs", [])
            if (j.get("conclusion") or "") == "failure"]


def get_file(repo: str, path: str, ref: str,
             token: str | None) -> dict | None:
    """Return {path, sha, content(str)} or None if missing."""
    try:
        data = _get(f"{API}/repos/{repo}/contents/{path}?ref={ref}", token)
    except Exception:
        return None
    if isinstance(data, list) or data.get("type") != "file":
        return None
    try:
        content = base64.b64decode(data["content"]).decode(
            "utf-8", errors="replace")
    except Exception:
        return None
    return {"path": path, "sha": data["sha"], "content": content}


# ---- write operations (token required) ------------------------------------

TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss",
            ".json", ".yml", ".yaml", ".toml", ".md", ".txt", ".sh", ".sql",
            ".xml", ".svg", ".env", ".gitignore", ".dockerignore", "dockerfile"}
SKIP_DIRS = ("node_modules/", ".git/", "dist/", "build/", "__pycache__/",
             ".next/", "vendor/wheels/", ".venv/", "venv/")


def repo_tree(repo: str, branch: str, token: str | None,
              limit: int = 400) -> list:
    """Editable text-file paths in the repo (filtered tree). Raises on error."""
    data = _get(f"{API}/repos/{repo}/git/trees/{branch}?recursive=1", token)
    out = []
    for t in data.get("tree", []):
        if t.get("type") != "blob":
            continue
        p = t.get("path", "")
        if any(p.startswith(d) for d in SKIP_DIRS):
            continue
        low = p.lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov",
                         ".zip", ".tar", ".gz", ".whl", ".pdf", ".ico",
                         ".woff", ".woff2", ".ttf", ".eot")):
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def create_branch(repo: str, branch: str, sha: str, token: str) -> dict:
    return _post(f"{API}/repos/{repo}/git/refs", token,
                 {"ref": f"refs/heads/{branch}", "sha": sha})


def update_file(repo: str, path: str, content: str, message: str,
                branch: str, sha: str | None, token: str) -> dict:
    data = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if sha:
        data["sha"] = sha
    return _put(f"{API}/repos/{repo}/contents/{path}", token, data)


def open_pr(repo: str, title: str, body: str, head: str, base: str,
            token: str) -> dict:
    return _post(f"{API}/repos/{repo}/pulls", token,
                 {"title": title, "body": body, "head": head, "base": base})
