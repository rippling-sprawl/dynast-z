#!/usr/bin/env python3
"""
One-time seed: move the notes that came from the "NFL 2026-27" Google Doc out of
data/nfl_projections_2026.json and into the Supabase `bun_notes` table (see
scripts/sql/bun_notes.sql), so that every note on /football/bakers-buns — the
seeded ones included — can be edited from the page instead of only the ones
added since.

The JSON file is left alone. It stays the offline fallback the page renders when
/api/bun-notes cannot be reached.

Ids are deterministic (seed_<ABBR>_<kind>_<i>), so re-running upserts the same
rows rather than duplicating them. Notes an admin has since edited are
overwritten back to the doc's wording — that is the point of a re-run, but it is
worth knowing before you do one.

    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/seed_bun_notes.py --dry-run
    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/seed_bun_notes.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = "data/nfl_projections_2026.json"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def build_rows():
    """One row per doc note, plus one per team's schedule blurb.

    Everything lands on week "all": the doc was written before the season, so
    none of it is about a particular week. `order` keeps the doc's ordering
    within a team, since every row is inserted in the same transaction and
    created_at cannot break the tie.
    """
    data = json.load(open(os.path.join(ROOT, SOURCE)))
    stamp = datetime.now(timezone.utc).isoformat()
    rows = []

    for team in data.get("teams", []):
        abbr = team.get("abbr")
        if not abbr:
            continue
        notes = team.get("notes") or {}

        items = [("note", i, text)
                 for i, text in enumerate(notes.get("notes") or [])]
        if notes.get("schedule"):
            items.append(("schedule", 0, notes["schedule"]))

        for kind, i, text in items:
            text = (text or "").strip()
            if not text:
                continue
            note_id = f"seed_{abbr}_{kind}_{i}"
            rows.append({
                "id": note_id,
                "team": abbr,
                "week": "all",
                "data": {
                    "id": note_id,
                    "team": abbr,
                    "week": "all",
                    "kind": kind,
                    "text": text,
                    "authorId": None,
                    "createdAt": stamp,
                    "updatedAt": stamp,
                    "order": i,
                    "seeded": True,
                },
                "updated_at": "now()",
            })

    return rows


def main():
    dry_run = "--dry-run" in sys.argv
    rows = build_rows()

    kinds = {}
    for r in rows:
        kinds[r["data"]["kind"]] = kinds.get(r["data"]["kind"], 0) + 1
    teams = len({r["team"] for r in rows})
    print(f"{len(rows)} rows across {teams} teams "
          f"({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))})")

    if dry_run:
        for r in rows:
            print(f"  {r['id']:<24} {r['data']['text'][:70]}")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("Set SUPABASE_URL and SUPABASE_KEY first.")

    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/bun_notes?on_conflict=id",
        data=json.dumps(rows).encode(), method="POST")
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req) as resp:
        print("Seeded bun_notes:", resp.status)


if __name__ == "__main__":
    main()
