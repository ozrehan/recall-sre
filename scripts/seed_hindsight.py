#!/usr/bin/env python3
"""Seed a Hindsight bank with the 28 historical incidents.

Usage:
    export HINDSIGHT_API_KEY="hsk_..."
    # optional: export HINDSIGHT_URL="https://api.hindsight.vectorize.io"
    python3 scripts/seed_hindsight.py

Idempotent: each incident is retained with document_id="incident-<id>",
so re-running replaces rather than duplicates.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.memory.hindsight_store import HindsightMemoryStore

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "backend", "data", "incidents.json")


def main():
    url = os.environ.get("HINDSIGHT_URL", "https://api.hindsight.vectorize.io")
    key = os.environ.get("HINDSIGHT_API_KEY")
    if not key:
        print("error: set HINDSIGHT_API_KEY first")
        sys.exit(1)
    incidents = json.load(open(DATA))
    mem = HindsightMemoryStore(url=url, api_key=key)
    for inc in incidents:
        mem.store_incident(inc)
        print(f"retained {inc['id']}: {inc['title'][:60]}")
    print(f"done — bank holds {mem.count()} incident documents")


if __name__ == "__main__":
    main()
