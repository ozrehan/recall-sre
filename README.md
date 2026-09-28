# RecallSRE 🧠

**Live demo:** https://recall-sre.onrender.com

**Turn every production incident into organizational memory.**

An AI incident memory & response agent for SaaS engineering teams (5–50 engineers).
When a production incident fires, RecallSRE searches your organization's incident
history in [Hindsight](https://hindsight.vectorize.io) — past error signatures,
root causes, fixes, commands, MTTR — and recommends investigation steps drawn
from what actually worked before.

> **Every production incident teaches the agent how to handle the next one.**

## The core loop

```
NEW INCIDENT
     ↓
analyze symptoms → search Hindsight memory → similar past incidents (ranked)
     ↓
recommend: likely causes + investigation steps (never false certainty)
     ↓
engineer resolves → post-mortem retained back into memory
     ↓
NEXT INCIDENT = SMARTER
```

The agent **never claims certainty**. It reports matches as *"87% similar to
INC-0047"* and recommends *next investigation steps* — because similar symptoms
can have different root causes. That honesty is the product.

## How Hindsight memory is used (hackathon submission)

| Agent step | Hindsight operation |
|---|---|
| New incident arrives | `recall()` — TEMPR engine (semantic + BM25 + graph + temporal) finds similar past incidents |
| Recommend a fix | `reflect()`-style synthesis, constrained by the bank's mission: *"frame as similarity hypotheses, never guaranteed root causes"* |
| Engineer resolves | `retain()` — the post-mortem (signature, symptoms, root cause, steps, commands, fix, MTTR) becomes a new memory, `document_id="incident-<id>"` (idempotent) |
| Learning over time | Observations auto-consolidate: *"payment-api 500s after deploys → connection-pool exhaustion (3 incidents)"* |

The demo's **time-travel toggle** (Day 1 blank memory vs Day 120 trained memory)
makes the learning curve visible: same incident, generic answer vs
memory-backed recommendation. That is the 25% memory criterion, on screen.

## Quickstart (no credentials needed)

Zero dependencies — pure Python 3 stdlib. The demo runs on a local
TF-IDF memory store with the identical interface, so it works offline.

```bash
git clone https://github.com/ozrehan/recall-sre
cd recall-sre
python3 backend/server.py
# open http://localhost:8080
```

Fire an incident from the scenario picker, read the memory matches, then resolve
it with a root cause + fix — watch the memory counter grow. Flip the
🕰 time-travel toggle to compare Day 1 vs Day 120.

## Using real Hindsight (Cloud)

1. Sign up at https://ui.hindsight.vectorize.io/signup
2. In billing, apply promo code **`MEMHACK99`** for $50 in credits
3. Create an API key, then:

```bash
pip install hindsight-client
export HINDSIGHT_API_KEY="hsk_..."   # Cloud URL is the default; no HINDSIGHT_URL needed
python3 scripts/seed_hindsight.py   # loads the 28 historical incidents
python3 backend/server.py           # badge flips to "memory: hindsight"
```

Optional: `GROQ_API_KEY=<redacted> for LLM-synthesized recommendation briefings
(free tier at https://groq.com). Without it, the agent uses template briefings.

Or self-host: `docker run -p 8888:8888 -e HINDSIGHT_API_LLM_API_KEY=<key> ghcr.io/vectorize-io/hindsight:latest`
and point `HINDSIGHT_URL=http://localhost:8888` (no API key needed locally).

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | `{ok, backend, mode, memory_size}` |
| GET | `/api/incidents` | seeded incident catalog |
| POST | `/api/investigate` | `{alert}` → `{incident, matches, recommendation}` |
| POST | `/api/resolve` | store post-mortem → `{id, memory_size}` |
| POST | `/api/mode` | `{mode: "trained"‖"empty"}` — time travel |
| GET | `/api/memory` | `{backend, size, recent}` |

## Project structure

```
recall-sre/
├── backend/
│   ├── server.py            # stdlib HTTP server + JSON API (no deps)
│   ├── agent/core.py        # analyze → recall → recommend → learn loop
│   ├── memory/
│   │   ├── base.py          # MemoryStore interface (+ score_label)
│   │   ├── local_store.py   # TF-IDF fallback, zero deps
│   │   └── hindsight_store.py # real Hindsight adapter (retain/recall/reflect)
│   └── data/incidents.json  # 28 realistic synthetic incidents
├── frontend/                # dashboard: live incident, memory match, recommendation
├── scripts/
│   ├── generate_incidents.py
│   └── seed_hindsight.py
└── docs/                    # demo script, article draft, social post
```

## Tech

Python 3 (stdlib server), vanilla JS dashboard, Hindsight (memory layer),
optional Groq LLM for briefing synthesis. MIT licensed.
