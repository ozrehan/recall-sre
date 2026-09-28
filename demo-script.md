# TraceMind — 60-second demo script

## Setup (before recording)
- `python3 backend/server.py`, open http://localhost:8080
- Time-travel toggle set to **Day 1 · blank memory**

## The story (60 seconds)

**[0:00–0:10] The problem.**
"Every engineering team has lived this: production goes down at an inconvenient
hour, and someone spends 30 minutes digging through old Slack threads and
post-mortems trying to remember how the team fixed the same thing last time.
Institutional knowledge walks out the door with every engineer who leaves."

**[0:10–0:25] Day 1 — the honest cold start.**
Fire the *payment-service 500s* scenario with the toggle on **Day 1**.
"Watch what the agent does with no memory. It doesn't bluff — it says it has
no historical context, gives generic first steps, and tells you it'll remember
this incident once resolved."

**[0:25–0:40] Teach it.**
Fill the resolve form: root cause *connection pool exhaustion after deploy
v3.1.2*, fix *raised pool 100→300 + rollback*. Hit **Store in organizational
memory**. "One incident, remembered forever — error signature, root cause,
the exact commands, MTTR."

**[0:40–0:55] Day 120 — the payoff.**
Flip to **Day 120**, fire the same scenario. "Now watch. Same incident —
but the agent recalls the match, shows the similarity score, surfaces the
root cause and the exact fix from last time, and recommends investigation
steps. The longer the company uses it, the more valuable its memory becomes."

**[0:55–1:00] The line.**
"TraceMind: every production incident teaches the agent how to handle the
next one. Memory isn't a feature — it's the product."

## Backup beats (if time allows)
- Fire the *websocket* scenario: novel signature → honest low-confidence path.
  "It knows what it doesn't know."
- Show the memory strip growing with each resolution.
- Mention: Hindsight `retain` / `recall` / `reflect` under the hood; bank
  mission enforces "similarity hypotheses, never guaranteed root causes."
