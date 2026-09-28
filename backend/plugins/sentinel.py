"""Repo Sentinel: server-side repo health watcher.

Runs in a background thread on the cloud server, so it keeps scanning even
when nobody has the TraceMind site open. Each pass:

  1. reads the connected repo's default branch + latest commit
  2. checks CI status (check runs + recent workflow runs)
  3. turns NEW problems into TraceMind incidents (deduplicated)

Never raises: all failures are captured into the scan result.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import github_api as gh
from . import get_setting, is_enabled

SCAN_KEY_PREFIX = "sentinel_seen:"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seen(db, key: str) -> bool:
    return bool(db.meta_get(SCAN_KEY_PREFIX + key))


def _mark_seen(db, key: str) -> None:
    db.meta_set(SCAN_KEY_PREFIX + key, _now())


def _file_incident(repo: str, kind: str, title: str, symptoms: str,
                   severity: str, ref: str) -> dict[str, Any]:
    return {
        "id": f"SENTINEL-{kind}-{ref}",
        "title": title,
        "service": repo,
        "severity": severity,
        "symptoms": symptoms,
        "started_at": _now(),
        "outcome": "open",
        "engineer": "trace-sentinel",
        "github_issue": {"repo": repo, "kind": f"sentinel/{kind}",
                         "ref": ref},
    }


def scan_repo(state, repo: str) -> dict[str, Any]:
    """Scan one repo. Returns a summary dict; never raises."""
    db = state.memory.db
    token = state.github_token
    result: dict[str, Any] = {
        "at": _now(), "repo": repo, "problems": [], "error": None,
    }
    try:
        info = gh.get_repo(repo, token)
        branch = info.get("default_branch") or "main"
        head = gh.latest_commit(repo, branch, token)
        sha = head.get("sha", "")[:7]
        result["branch"] = branch
        result["commit"] = sha

        # --- CI check runs on the latest commit ---------------------------
        failing: list[str] = []
        try:
            for cr in gh.check_runs(repo, head["sha"], token):
                if (cr.get("conclusion") or "") == "failure":
                    failing.append(cr.get("name") or "check")
        except Exception:
            pass
        try:
            st = gh.combined_status(repo, head["sha"], token)
            if (st.get("state") or "") == "failure":
                for s in st.get("statuses", []):
                    name = s.get("context") or "status"
                    if name not in failing:
                        failing.append(name)
        except Exception:
            pass

        if failing:
            key = f"ci:{sha}"
            names = ", ".join(failing[:5])
            if not _seen(db, key):
                _mark_seen(db, key)
                inc = _file_incident(
                    repo, "ci",
                    f"CI failing on {branch} ({sha})",
                    f"Failing checks: {names}. Commit: "
                    f"{(head.get('commit', {}).get('message') or '')[:120]}",
                    "high", key)
                state.memory.store_incident(inc)
                result["problems"].append(
                    {"kind": "ci", "title": inc["title"], "ref": key})
        else:
            result["ci"] = "passing"

        # --- recent failed workflow runs ----------------------------------
        try:
            for run in gh.recent_workflow_runs(repo, token, per_page=5):
                if (run.get("conclusion") or "") != "failure":
                    continue
                rid = str(run.get("id"))
                key = f"wf:{rid}"
                if _seen(db, key):
                    continue
                _mark_seen(db, key)
                inc = _file_incident(
                    repo, "workflow",
                    f"Workflow failed: {run.get('name')}",
                    f"Run #{run.get('run_number')} on {run.get('head_branch')} "
                    f"failed at {run.get('updated_at')}.",
                    "medium", key)
                state.memory.store_incident(inc)
                result["problems"].append(
                    {"kind": "workflow", "title": inc["title"], "ref": key,
                     "run_id": run.get("id")})
        except Exception as e:
            result["workflow_error"] = str(e)[:120]

    except Exception as e:
        result["error"] = f"github api: {e}"[:200]

    db.meta_set("sentinel_last_run", result["at"])
    db.meta_set("sentinel_last_result", json.dumps(result)[:4000])
    return result


def last_result(db) -> dict[str, Any] | None:
    raw = db.meta_get("sentinel_last_result")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def sentinel_enabled(db) -> bool:
    return is_enabled(db, "sentinel")


def scan_interval_minutes(db) -> int:
    try:
        return max(5, min(int(get_setting(db, "sentinel_minutes", "15")),
                          1440))
    except ValueError:
        return 15

def scan_once(state) -> dict[str, Any]:
    """One scan pass over ALL connected repos. Never raises."""
    combined: dict[str, Any] = {
        "at": _now(), "problems": [], "repos": {}, "error": None}
    for repo in state.github_repos:
        try:
            r = scan_repo(state, repo)
            combined["repos"][repo] = {
                "problems": len(r.get("problems", [])),
                "error": r.get("error"),
            }
            combined["problems"].extend(r.get("problems", []))
        except Exception as e:
            combined["repos"][repo] = {"problems": 0,
                                       "error": str(e)[:120]}
    db = state.memory.db
    db.meta_set("sentinel_last_run", combined["at"])
    import json as _json
    db.meta_set("sentinel_last_result", _json.dumps(combined)[:4000])
    return combined
