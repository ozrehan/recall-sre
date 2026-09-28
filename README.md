# TraceMind

**Live:** https://tracemind-szuq.onrender.com

**Turn incidents into insight.**

An AI incident memory & response agent for SaaS engineering teams (5–50 engineers).
TraceMind watches your GitHub repo's issues, treats them as live incidents, and
investigates each one against your organization's incident history in
[Hindsight](https://hindsight.vectorize.io) — past error signatures, root
causes, fixes, commands, MTTR — recommending investigation steps drawn from
what actually worked before.

> **Every production incident teaches the agent how to handle the next one.**

## How it works (real pipeline, no demo data)

```
GitHub issue opened ──sync──▶ TraceMind incident ──recall──▶ similar past incidents
        │                                                        │
        │ closed on GitHub                                       ▼
        └──────────▶ resolved + post-mortem learned ──retain──▶ Hindsight memory
```

1. **Sync** — every few minutes TraceMind polls the connected repo
   (`GITHUB_REPO`, changeable in Settings). New issues become open incidents;
   closed issues become resolved incidents with MTTR computed from timestamps.
2. **Investigate** — pick an open issue (or describe your own incident) and the
   agent searches Hindsight memory for similar past incidents, ranked by
   relevance, with the fixes that worked before.
3. **Recommend** — likely causes + ordered investigation steps, phrased as
   evidence-backed hypotheses. With `GITHUB_TOKEN` set, the recommendation is
   also posted as a comment on the issue.
4. **Resolve & teach** — store the root cause + fix; it's retained to memory,
   so the next similar incident starts smarter. A resolution made in TraceMind
   is never overwritten by later GitHub edits.

The agent **never claims certainty**. It reports matches as *"87% similar to
GH-1042"* and recommends *next investigation steps* — because similar symptoms
can have different root causes. That honesty is the product.

## How Hindsight memory is used

| Agent step | Hindsight operation |
|---|---|
| New incident arrives | `recall()` — TEMPR engine (semantic + BM25 + graph + temporal) finds similar past incidents |
| Recommend a fix | `reflect()`-style synthesis, constrained by the bank's mission: *"frame as similarity hypotheses, never guaranteed root causes"* |
| Engineer resolves | `retain()` — the post-mortem (signature, symptoms, root cause, steps, commands, fix, MTTR) becomes a new memory, `document_id="incident-<id>"` (idempotent) |
| Learning over time | Observations auto-consolidate: *"payment-api 500s after deploys → connection-pool exhaustion (3 incidents)"* |

## Quickstart (no credentials needed)

Zero dependencies — pure Python 3 stdlib. Without a Hindsight key it runs on a
local TF-IDF memory store with the identical interface, so it works offline.

```bash
git clone https://github.com/ozrehan/recall-sre
cd recall-sre
python3 backend/server.py
# open http://localhost:8080
```

Open **Settings** (⚙) to point at your repo and hit **Sync now** — issues appear
as live incidents. Investigate one, resolve it with a root cause + fix, and
watch the memory counter grow.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GITHUB_REPO` | `ozrehan/recall-sre` | repo whose issues become incidents (`owner/name`) |
| `GITHUB_SYNC_MINUTES` | `5` | poll interval |
| `GITHUB_TOKEN` | — | private repos + post recommendations as issue comments |
| `HINDSIGHT_API_KEY` | — | Hindsight Cloud (URL defaults to Cloud when key is set) |
| `HINDSIGHT_BANK_ID` | `incident-memory-prod` | memory bank for real incidents |
| `GROQ_API_KEY` | — | optional LLM-synthesized briefings (free tier at groq.com) |
| `DB_PATH` | `backend/data/tracemind.db` | SQLite database of record |

Settings changed in the UI (repo, sync interval) persist in SQLite. A GitHub
token can also be added via `GITHUB_TOKEN` for private repos.

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | `{ok, backend, memory_size, github{...}}` |
| GET | `/api/incidents` | real incidents from the database, open first |
| POST | `/api/investigate` | `{alert}` → `{incident, matches, recommendation}` |
| POST | `/api/resolve` | store post-mortem → `{id, memory_size}` |
| GET | `/api/memory` | `{backend, size, recent}` |
| GET | `/api/settings` | current settings |
| POST | `/api/settings` | `{github_repo?, sync_minutes?}` |
| POST | `/api/settings/clear-db` | wipe local incidents (re-sync from GitHub) |
| GET | `/api/integrations/github` | sync status for the connected repo |
| POST | `/api/integrations/github/sync` | run a sync pass now |

## Project structure

```
recall-sre/
├── backend/
│   ├── server.py              # stdlib HTTP server + JSON API (no deps)
│   ├── agent/core.py          # analyze → recall → recommend → learn loop
│   ├── integrations/
│   │   ├── github_issues.py   # GitHub API client + issue→incident mapping
│   │   └── sync.py            # the live sync pipeline
│   ├── memory/
│   │   ├── base.py            # MemoryStore interface (+ score_label)
│   │   ├── db.py              # SQLite database of record + sync state
│   │   ├── hybrid_store.py    # SQLite + semantic recall as one store
│   │   ├── local_store.py     # TF-IDF fallback, zero deps
│   │   └── hindsight_store.py # real Hindsight adapter (retain/recall/reflect)
│   └── data/incidents.json    # dev fixture (not auto-loaded)
├── frontend/                  # chat UI + ChatGPT-style settings
└── render.yaml                # Render blueprint
```

## Tech

Python 3 (stdlib server), vanilla JS dashboard, Hindsight (memory layer),
GitHub Issues (incident source), optional Groq LLM for briefing synthesis.
MIT licensed.
