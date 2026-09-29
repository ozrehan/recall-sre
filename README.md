# TraceMind

**Live:** https://tracemind.run.place

**Turn incidents into insight.**

An AI incident memory & response agent for SaaS engineering teams. TraceMind
watches your GitHub repos' issues, treats them as live incidents, and
investigates each one against your organization's incident history in
[Hindsight](https://hindsight.vectorize.io) — past error signatures, root
causes, fixes, commands, MTTR — recommending investigation steps drawn from
what actually worked before.

> **Every production incident teaches the agent how to handle the next one.**

## Features

**Investigate**
- 4-step guided flow: Fire an incident → Search memory → Get recommendations → Resolve & teach
- Day 1 / Day 120 time-travel, ranked past-incident matches with relevance bars
- Numbered investigation steps, confidence/honesty box, memory stats + growth chart
- The agent never claims certainty — matches are reported as *"87% similar to
  GH-1042"* with next investigation steps, because similar symptoms can have
  different root causes. That honesty is the product.

**Trace chat agent**
- Conversational assistant over your incidents, memory, and repos
- **Autonomous code edits:** type *"change the button color to red"* — Trace
  plans the change, shows a unified diff, and opens a pull request on Apply
- **Push code:** pick a repo, edit any file in the panel, commit & open a PR
  (always on a new `tracemind-edit-*` branch — main is never pushed directly)

**GitHub integration**
- Real OAuth connect (`repo` + `user:email` scopes), multi-repo support
- Read-only vs read-and-write mode pills (verified against real token permissions)
- **Repo Sentinel** (on by default): scans CI every 15 minutes, files failing
  builds as incidents automatically — works with the site closed
- **Auto-Fix** (opt-in): Groq diagnoses failing builds and opens PRs on
  `tracemind-autofix-*` branches
- Issue sync: open issues become incidents, closed ones resolve with MTTR

**Accounts**
- Sign up / log in with password, Google, or GitHub
- Profiles: editable name/bio, photo upload, social links (GitHub, LinkedIn,
  LeetCode, X, Instagram, website), animated doodle avatar, followers/following
- Recents & pinned chats reopen saved transcripts

**Admin (owner only)**
- Full-screen dashboard: member count, live-online members, logins (24h / 7d /
  total), logins by provider, all members, recent login history (email,
  provider, IP, time)
- ⋮ menu exports the data to PDF or Excel
- Access is gated by the `ADMIN_EMAILS` env var — the button and the API are
  invisible to everyone else

## How it works (real pipeline, no demo data)

```
GitHub issue opened ──sync──▶ TraceMind incident ──recall──▶ similar past incidents
        │                                                        │
        │ closed on GitHub                                       ▼
        └──────────▶ resolved + post-mortem learned ──retain──▶ Hindsight memory
```

1. **Sync** — every few minutes TraceMind polls connected repos. New issues
   become open incidents; closed issues become resolved incidents with MTTR.
2. **Investigate** — pick an open issue (or describe your own incident) and the
   agent searches Hindsight memory for similar past incidents, ranked by
   relevance, with the fixes that worked before.
3. **Recommend** — likely causes + ordered investigation steps, phrased as
   evidence-backed hypotheses. With `GITHUB_TOKEN` set, the recommendation is
   also posted as a comment on the issue.
4. **Resolve & teach** — store the root cause + fix; it's retained to memory,
   so the next similar incident starts smarter.

| Agent step | Hindsight operation |
|---|---|
| New incident arrives | `recall()` — TEMPR engine (semantic + BM25 + graph + temporal) finds similar past incidents |
| Recommend a fix | `reflect()`-style synthesis, constrained by the bank's mission: *"frame as similarity hypotheses, never guaranteed root causes"* |
| Engineer resolves | `retain()` — the post-mortem becomes a new memory, `document_id="incident-<id>"` (idempotent) |
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

Connect a repo in the GitHub panel, hit **Sync now** — issues appear as live
incidents. Investigate one, resolve it with a root cause + fix, and watch the
memory counter grow.

## Configuration

| Env var | Purpose |
|---|---|
| `GITHUB_REPO` | default repo whose issues become incidents (`owner/name`) |
| `GITHUB_SYNC_MINUTES` | poll interval (default 5) |
| `GITHUB_TOKEN` | private repos + post recommendations as issue comments |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth app (connect + login) |
| `GOOGLE_CLIENT_ID` | Google sign-in |
| `HINDSIGHT_API_KEY` | Hindsight Cloud (URL defaults to Cloud when key is set) |
| `HINDSIGHT_BANK_ID` | memory bank for real incidents |
| `GROQ_API_KEY` | optional LLM-synthesized briefings (free tier at groq.com) |
| `AUTH_SECRET` | signs login tokens |
| `ADMIN_EMAILS` | comma-separated owner emails for the admin dashboard |
| `DB_PATH` | SQLite database of record (default `backend/data/tracemind.db`) |

Settings changed in the UI (repo, sync interval) persist in SQLite.

## API (highlights)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | `{ok, backend, memory_size, github{...}}` |
| GET | `/api/incidents` | incidents from the database, open first |
| POST | `/api/investigate` | `{alert}` → `{incident, matches, recommendation}` |
| POST | `/api/resolve` | store post-mortem → `{id, memory_size}` |
| POST | `/api/chat` | talk to Trace (includes code-edit planning) |
| POST | `/api/chat/plan-edit` | natural-language request → file pick + unified diff |
| GET/POST | `/api/repo/file`, `/api/repo/commit` | read a repo file / commit & open a PR |
| POST | `/api/auth/signup`, `/api/auth/login`, `/api/auth/google` | account auth |
| GET | `/api/auth/me` | current user (`is_admin` flag included) |
| GET | `/api/admin/stats` | admin-only login/member analytics |
| GET | `/api/github/oauth/start` | begin GitHub OAuth (connect or login) |

## Project structure

```
recall-sre/
├── backend/
│   ├── server.py              # stdlib HTTP server + JSON API (no deps)
│   ├── auth.py                # accounts, tokens, login events, admin stats
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
│   ├── vendor/wheels/         # vendored wheels — builds need no PyPI
│   └── data/incidents.json    # seed incidents (28)
├── frontend/                  # chat UI, admin page, profiles, GitHub panel
└── render.yaml                # Render blueprint
```

## Deploy notes

- Hosted on Render (free tier, Singapore); `tracemind.run.place` is the
  canonical domain (free 1-year registration, expires 2027-09-29). The legacy
  `*.onrender.com` host 308-redirects to it.
- Render's disk is ephemeral: SQLite reseeds from `incidents.json` on each
  deploy; Hindsight Cloud is the durable memory. Users and login history live
  in SQLite and reset on redeploy.
- Safe-deploy rule for this repo: pause auto-deploy → push the complete tree
  → trigger one manual deploy → verify live → restore auto-deploy. Code edits
  via the agent always go through branches + PRs, never direct to main.

## Tech

Python 3 (stdlib-only server), vanilla JS frontend, SQLite, Hindsight (memory
layer), Groq (optional LLM synthesis), GitHub OAuth + API.
