#!/usr/bin/env python3
"""
One-time seed: push the committed data/*.json odds artifacts into the Supabase
`odds_state` table (see scripts/sql/odds_state.sql), so the new /api/odds-ingest
flow starts from today's data instead of empty.

Needs SUPABASE_URL and SUPABASE_KEY in the environment (the same vars the api/
functions use). Idempotent — re-running just overwrites the four rows.

    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/seed_odds_state.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SCORE_STATS = ["passing_yards", "passing_tds", "receiving_yards",
               "receiving_tds", "rushing_yards", "wins"]


def load(rel):
    return json.load(open(os.path.join(ROOT, rel)))


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("Set SUPABASE_URL and SUPABASE_KEY first.")

    state = {
        "fd": load("data/fd.json"),
        "dk": load("data/dk.json"),
        "outrights": load("data/outrights.json"),
        "score": {st: load(f"data/score/{st}.json") for st in SCORE_STATS},
    }
    payload = [{"data_key": k, "data": v, "updated_at": "now()"}
               for k, v in state.items()]

    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/odds_state?on_conflict=data_key",
        data=json.dumps(payload).encode(), method="POST")
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req) as resp:
        print("Seeded odds_state:", resp.status, "->", ", ".join(state.keys()))


if __name__ == "__main__":
    main()
