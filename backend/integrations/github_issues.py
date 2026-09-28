"""GitHub Issues as TraceMind's real incident source.

This is the live data pipeline — no demo data. Every issue in the
connected repo becomes an incident in TraceMind's memory:

  * new issue        -> new open incident (stored in SQLite + retained to Hindsight)
  * updated issue    -> incident fields refreshed
  * closed issue     -> incident resolved; the closing state becomes the post-mortem

Public repos need no token to read (60 req/hr unauthenticated is plenty
for a 5-minute poll). Set GITHUB_TOKEN for private repos, higher rate
limits, and for TraceMind to post its recommendations as issue comments.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any

API = "https://api.github.com"

_LABEL_SEV = [
    ("critical", "critical"), ("p0", "critical"), ("sev0", "critical"),
    ("sev1", "critical"),
    ("high", "high"), ("p1", "high"), ("sev2", "high"),
    ("medium", "medium"), ("p2", "medium"),
    ("low", "low"), ("p3", "low"), ("sev3", "low"),
]
_SVC_RE = re.compile(r"^(?:service|svc|area|component)\s*[:=]\s*(.+)$", re.I)


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


def fetch_issues(repo: str, token: str | None = None,
                 per_page: int = 100, max_pages: int = 10) -> list[dict[str, Any]]:
    """All issues (open + closed) for repo, newest activity first. Skips PRs."""
    issues: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = (f"{API}/repos/{repo}/issues?state=all&per_page={per_page}"
               f"&page={page}&sort=updated&direction=desc")
        batch = _get(url, token)
        if not isinstance(batch, list) or not batch:
            break
        issues.extend(i for i in batch if "pull_request" not in i)
        if len(batch) < per_page:
            break
    return issues


def post_comment(repo: str, number: int, token: str, body: str) -> dict[str, Any]:
    """Post a comment on an issue. Requires GITHUB_TOKEN."""
    url = f"{API}/repos/{repo}/issues/{number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(token),
                                 method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def list_comments(repo: str, number: int, token: str | None) -> list[dict[str, Any]]:
    url = f"{API}/repos/{repo}/issues/{number}/comments?per_page=100"
    try:
        data = _get(url, token)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _severity(labels: list[str]) -> str:
    low = {l.lower() for l in labels}
    for key, sev in _LABEL_SEV:
        if key in low or any(key == part for l in low for part in re.split(r"[\s_-]+", l)):
            return sev
    if "bug" in low:
        return "high"
    return "medium"


def _service(labels: list[str], repo: str) -> str:
    for l in labels:
        m = _SVC_RE.match(l.strip())
        if m:
            return m.group(1).strip().lower().replace(" ", "-")
    return repo.split("/")[-1]


def _mttr_minutes(created: str, closed: str | None) -> int | None:
    if not closed:
        return None
    try:
        c = datetime.fromisoformat(created.replace("Z", "+00:00"))
        e = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        return max(1, int((e - c).total_seconds() // 60))
    except Exception:
        return None


def issue_to_incident(issue: dict[str, Any], repo: str) -> dict[str, Any]:
    """Map a GitHub issue to a TraceMind incident dict."""
    labels = [l.get("name", "") for l in issue.get("labels", [])]
    body = (issue.get("body") or "").strip()
    closed_at = issue.get("closed_at")
    symptoms = [body[:500]] if body else [issue.get("title", "")]
    incident = {
        "id": f"GH-{issue.get('number')}",
        "title": issue.get("title", f"Issue #{issue.get('number')}"),
        "service": _service(labels, repo),
        "severity": _severity(labels),
        "error_signature": "",
        "symptoms": symptoms,
        "logs_snippet": "",
        "deployment": {},
        "started_at": issue.get("created_at"),
        "resolved_at": closed_at,
        "outcome": "resolved" if closed_at else "open",
        "engineer": (issue.get("closed_by") or {}).get("login", "")
                     if closed_at else (issue.get("user") or {}).get("login", ""),
        "mttr_minutes": _mttr_minutes(issue.get("created_at", ""), closed_at),
        "root_cause": "",
        "fix": "",
        "investigation_steps": [],
        "commands_used": [],
        "source": "github",
        "github_issue": {
            "repo": repo,
            "number": issue.get("number"),
            "url": issue.get("html_url"),
            "state": issue.get("state"),
            "labels": labels,
            "updated_at": issue.get("updated_at"),
            "author": (issue.get("user") or {}).get("login", ""),
        },
    }
    return incident


def env_repo() -> str:
    return os.environ.get("GITHUB_REPO", "ozrehan/recall-sre")


def env_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or None
