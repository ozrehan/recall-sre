# I built an SRE agent with a memory — here's what changed

*How we turned every production incident into organizational memory using Hindsight.*

## The problem nobody talks about

Ask any backend engineer about their worst on-call night and you'll hear the
same subplot: the team had solved this exact incident before — three months
ago, by someone who has since left — and nobody could find the post-mortem.
So they re-derived the diagnosis from scratch, at 3am, while the error rate
climbed.

Companies don't have an alerting problem. They have a **remembering problem**.
Runbooks go stale, Slack threads scroll away, and the most valuable debugging
knowledge lives in people's heads. When those people leave, the knowledge
leaves with them.

## The idea: incident memory as a product

For the Hindsight hackathon I built **RecallSRE**, an incident response agent
whose entire value proposition is persistent memory. The pitch is one line:

> **Every production incident teaches the agent how to handle the next one.**

The loop is deliberately small — one workflow, one persona (the on-call
engineer):

1. **New incident** → the agent analyzes symptoms and searches Hindsight
   memory for similar past incidents (error signatures, services, deployments).
2. **Recommend** → it surfaces the closest matches with similarity scores,
   their root causes, the exact commands that worked, and MTTR — framed as
   *investigation steps*, never as certainty.
3. **Resolve** → the engineer logs the post-mortem, and it's retained back
   into memory. The next similar incident is smarter.

## Why memory is the star, not a feature

Most "AI for DevOps" demos bolt a vector database onto a chatbot. I did the
opposite: the memory layer *is* the product, and the demo proves it with a
time-travel toggle.

- **Day 1 (blank memory):** the agent is honest about having no history. It
  gives generic triage steps and says it will remember this incident.
- **Day 120 (trained memory):** the same incident returns ranked historical
  matches — "87% similar to INC-0047" — with the root cause, the fix, and the
  commands that resolved it last time.

Same input, dramatically different output. That before/after *is* the Hindsight
story: `retain()` turns post-mortems into structured memories, `recall()`
finds them with hybrid semantic + keyword + temporal search, and a bank-level
mission enforces the positioning: *"frame recommendations as similarity
hypotheses with supporting evidence — never as guaranteed root causes."*

## The credibility decision

Early on I almost shipped the tagline "never debug the same incident twice."
It's punchy — and dishonest. Similar symptoms can have different root causes,
and any SRE knows it. So the agent reports similarity scores and recommends
*next steps to investigate*, citing the incident IDs behind each hypothesis.
In the demo, a deliberately novel incident (websocket drops with no
historical match) shows the agent's honest low-confidence path. Trust is the
feature.

## What I'd do with more time

Real integrations: webhooks from PagerDuty/Opsgenie for incident intake,
GitHub deployment correlation, Slack thread ingestion via Hindsight's
conversation-threading retain. And `reflect()`-generated draft post-mortems
after each resolution. The architecture already supports all of it — the
memory interface is the seam.

## Try it

Repo: https://github.com/ozrehan/recall-sre — `python3 backend/server.py`,
zero dependencies, and the demo runs entirely offline. Point it at Hindsight
Cloud with one API key to use the real memory backend.

*Built for the Hindsight hackathon. Memory isn't a feature — it's the product.*
