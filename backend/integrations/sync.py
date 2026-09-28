"""GitHub -> TraceMind sync: the live incident pipeline.

Runs on boot (when the database is empty) and every few minutes after.
Each sync:

  1. pulls all issues from the connected repo (open + closed)
  2. new issues        -> stored as open incidents (SQLite + Hindsight)
  3. changed issues    -> incident fields refreshed
  4. newly closed ones -> resolved with a post-mortem, retained to memory
  5. (with GITHUB_TOKEN) posts TraceMind's recommendation as a comment on
     new open issues that don't have one yet

A resolution made inside TraceMind always wins: if an incident already
has a root cause + fix learned here, closing the issue on GitHub won't
overwrite it.
"""
from __future__ import annotations

from typing import Any, Callable

from . import github_issues as gh
from backend.memory.db import IncidentDB

TRACEMIND_COMMENT_MARKER = "<!-- tracemind-recommendation -->"


def recommendation_comment(incident: dict[str, Any],
                           recommendation: dict[str, Any]) -> str:
    gi = incident.get("github_issue", {})
    lines = [
        TRACEMIND_COMMENT_MARKER,
        "## 🧠 TraceMind investigation",
        "",
        f"**{recommendation.get('headline', '')}**",
        "",
        (recommendation.get("body") or "").strip(),
        "",
    ]
    causes = recommendation.get("likely_causes") or []
    if causes:
        lines.append("**Likely causes (seen before):**")
        lines += [f"- {c[:200]}" for c in causes[:3]]
        lines.append("")
    steps = recommendation.get("suggested_steps") or []
    if steps:
        lines.append("**Suggested investigation steps:**")
        lines += [f"{i + 1}. {s[:200]}" for i, s in enumerate(steps[:5])]
        lines.append("")
    lines.append(f"_Investigated against {gi.get('repo', '')} organizational memory. "
                 "Verify before acting._")
    return "\n".join(lines)


def sync_github(store: Any, db: IncidentDB, repo: str,
                token: str | None = None,
                investigate_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                post_recommendations: bool = True) -> dict[str, Any]:
    """One sync pass. Returns {repo, issues_seen, new, updated, resolved,
    comments_posted, error}."""
    stats = {"repo": repo, "issues_seen": 0, "new": 0, "updated": 0,
             "resolved": 0, "comments_posted": 0, "error": None}
    try:
        issues = gh.fetch_issues(repo, token)
    except Exception as e:
        stats["error"] = f"github api: {e}"
        return stats

    for issue in issues:
        stats["issues_seen"] += 1
        number = issue.get("number")
        inc_id = f"GH-{number}"
        incident = gh.issue_to_incident(issue, repo)
        existing = db.get(inc_id)
        issue_updated = (issue.get("updated_at") or "")[:19]

        if existing is None:
            store.store_incident(incident)
            db.record_github_sync(repo, number, inc_id,
                                  issue_updated, issue.get("state", ""))
            stats["new"] += 1
        else:
            # TraceMind's own resolution wins over GitHub state changes.
            learned = bool(existing.get("root_cause") or existing.get("fix"))
            row = db.get_github_sync(repo, number)
            prev_updated = (row or {}).get("issue_updated_at", "")
            if not learned and issue_updated > prev_updated:
                merged = dict(existing)
                for k in ("title", "service", "severity", "symptoms",
                          "started_at", "resolved_at", "outcome",
                          "engineer", "mttr_minutes"):
                    merged[k] = incident[k]
                merged["github_issue"] = incident["github_issue"]
                store.store_incident(merged)
                db.record_github_sync(repo, number, inc_id,
                                      issue_updated, issue.get("state", ""))
                if merged.get("outcome") == "resolved":
                    stats["resolved"] += 1
                else:
                    stats["updated"] += 1
            elif row is None or row.get("issue_state") != issue.get("state"):
                db.record_github_sync(repo, number, inc_id,
                                      max(issue_updated, prev_updated),
                                      issue.get("state", ""))

        # Recommend on fresh open issues (token-gated, once per issue).
        if (post_recommendations and token and investigate_fn
                and issue.get("state") == "open"):
            try:
                comments = gh.list_comments(repo, number, token)
                if not any(TRACEMIND_COMMENT_MARKER in (c.get("body") or "")
                           for c in comments):
                    alert = {
                        "title": incident["title"],
                        "service": incident["service"],
                        "severity": incident["severity"],
                        "error_signature": "",
                        "symptoms": incident["symptoms"],
                        "logs_snippet": "",
                        "deployment": {},
                    }
                    result = investigate_fn(alert)
                    body = recommendation_comment(
                        incident, result.get("recommendation", {}))
                    gh.post_comment(repo, number, token, body)
                    stats["comments_posted"] += 1
            except Exception as e:
                print(f"[sync] comment failed on #{number}: {e}")

    db.meta_set(f"github_last_sync:{repo}", "1")  # marker; timestamp below
    from datetime import datetime, timezone
    db.meta_set("github_last_sync_at",
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    db.meta_set("github_last_sync_repo", repo)
    return stats
