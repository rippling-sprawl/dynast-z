#!/usr/bin/env python3
"""Shape the Action Network export into the Action Ledger's row set and push it.

    cache/an_picks.json ─> build_action_ledger.py ─> PUT /api/action-ledger ─> Supabase

/football/action-ledger is every tracked bet in one filterable list, admin-only.
The export it reads is 28 MB and lives in cache/ because it is personal betting
history (see fetch_action_network.py), so the page cannot fetch it as a static
file -- this script trims it to one compact row per ticket and stores the set in
Supabase `action_pages` under the slug `ledger`, where api/action-ledger.py
serves it to admins only.

The `ledger` row shares action_pages with the Action book but is not part of it:
api/action-ingest.py leaves it out of its manifest, so a book push neither
reports nor deletes it.

ROW SHAPE (short keys: ~11k rows, so every byte is paid eleven thousand times)

    id   pick id (straight/future) or group id (parlay/teaser)
    k    kind: straight | future | parlay | teaser
    t    bet type: Spread, Moneyline, Total, Prop, Future, Custom, Parlay, ...
    sub  prop market, when t is Prop ("Anytime TD", "Receiving Yards")
    d    description, as entered
    lg   league slug, or "" when Action Network has none
    tm   team nicknames the ticket touches (both sides of every game in it)
         -- absent when none are known, as is any other field that would be null
    m    "Away @ Home", single-game tickets only
    o    American odds
    s    stake ($)
    w    to win ($)
    n    net ($), null while pending
    r    win | loss | push | pending | void
    st / en / pl / se   starts_at / ends_at / placed (created_at) / settled_at
    legs [{d, m, r}] for parlays and teasers

USAGE

    python3 scripts/build_action_ledger.py            build and report, write nothing
    python3 scripts/build_action_ledger.py --out F    dump the payload to F
    python3 scripts/build_action_ledger.py --push     PUT to /api/action-ledger
    python3 scripts/build_action_ledger.py --seed     write straight to Supabase

--push needs ADMIN_USER_ID; --seed needs SUPABASE_URL and SUPABASE_KEY. Both
read .env, as build_action.py does. Run fetch_action_network.py first.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "cache", "an_picks.json")
SLUG = "ledger"
INGEST_URL = os.environ.get("ACTION_LEDGER_URL",
                            "https://www.dynastz.com/api/action-ledger")

CORE_RE = re.compile(r"^core_bet_type_\d+_(.+)$")

# Market slugs Action Network spells out that read better shortened.
PROP_NAMES = {
    "anytime_touchdown_scorer": "Anytime TD",
    "first_touchdown_scorer": "First TD",
    "to_score_2_or_more_touchdowns": "2+ TDs",
    "3fgm": "3PM",
}


def load_env():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def bet_type(pick, kind):
    """(type, sub) for one ticket. Kind wins first: a parlay of spreads is a
    parlay, and a futures ticket is a future whatever market it was entered on."""
    if kind == "parlays":
        return "Parlay", None
    if kind == "teasers":
        return "Teaser", None
    if pick.get("is_future"):
        return "Future", None
    pt = pick.get("pick_type") or (pick.get("raw") or {}).get("type") or ""
    if pt.startswith("spread"):
        return "Spread", None
    if pt.startswith("ml") or pt == "draw":
        return "Moneyline", None
    if pt in ("over", "under") or pt.endswith(("_over", "_under")) or pt.startswith("total"):
        return "Total", None
    m = CORE_RE.match(pt)
    if m:
        key = m.group(1)
        return "Prop", PROP_NAMES.get(key, key.replace("_", " ").title())
    if pt in ("free_form", "custom"):
        return "Custom", None
    if pt == "competition":
        return "Competition", None
    return "Other", None


def teams_of(matchup):
    return [t.strip() for t in matchup.split(" @ ")] if matchup else []


def legs_of(raw):
    return (raw.get("picks") or []) + (raw.get("custom_picks") or [])


def money(v):
    return None if v is None else round(float(v), 2)


def build(data):
    straight_like = (data["straight"] + data["futures"]["pending"]
                     + data["futures"]["settled"])
    # A leg carries a game_id but not the game, so its teams come from any
    # straight bet on the same game -- which covers ~87% of legs.
    games = {}
    for p in straight_like:
        gid = (p.get("raw") or {}).get("game_id")
        if gid and p.get("matchup"):
            games[gid] = p["matchup"]

    rows, seen = [], set()
    buckets = [("straight", data["straight"]), ("futures", data["futures"]["pending"]),
               ("futures", data["futures"]["settled"]), ("parlays", data["parlays"]),
               ("teasers", data["teasers"])]
    for kind, picks in buckets:
        for p in picks:
            key = (kind in ("parlays", "teasers"), p["id"])
            if key in seen:
                continue
            seen.add(key)
            raw = p.get("raw") or {}
            t, sub = bet_type(p, kind)
            row = {
                "id": p["id"],
                "k": {"straight": "future" if p.get("is_future") else "straight",
                      "futures": "future", "parlays": "parlay",
                      "teasers": "teaser"}[kind],
                "t": t, "d": p.get("description") or "", "lg": p.get("league") or "",
                "o": p.get("odds"), "s": money(p.get("stake")), "w": money(p.get("to_win")),
                "n": money(p.get("net")), "r": p.get("result") or "pending",
                "st": p.get("starts_at"), "en": raw.get("ends_at"),
                "pl": p.get("created_at"), "se": p.get("settled_at"),
            }
            if sub:
                row["sub"] = sub
            teams = set(teams_of(p.get("matchup")))
            if p.get("matchup"):
                row["m"] = p["matchup"]
            if kind in ("parlays", "teasers"):
                legs = []
                for leg in legs_of(raw):
                    m = games.get(leg.get("game_id"))
                    teams.update(teams_of(m))
                    out = {"d": leg.get("play") or "", "r": leg.get("result") or "pending"}
                    if m:
                        out["m"] = m
                    legs.append(out)
                row["legs"] = legs
                if not row["lg"]:
                    lgs = {leg.get("league_name") for leg in legs_of(raw)} - {None}
                    row["lg"] = lgs.pop() if len(lgs) == 1 else ("multi" if lgs else "")
            if teams:
                row["tm"] = sorted(teams)
            # Absent rather than null: a pending ticket has no net or settle
            # time, and eleven thousand `"n":null`s are pure weight.
            rows.append({k: v for k, v in row.items() if v is not None})
    rows.sort(key=lambda r: r["st"] or r["pl"] or "", reverse=True)
    return rows


def etag_of(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def push(body, user_id):
    req = urllib.request.Request(INGEST_URL, data=json.dumps(body).encode(), method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-User-Id", user_id)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def seed(body, url, key):
    row = {"slug": SLUG, "data": body["data"], "etag": body["etag"], "updated_at": "now()"}
    req = urllib.request.Request(f"{url}/rest/v1/action_pages?on_conflict=slug",
                                 data=json.dumps([row]).encode(), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req) as resp:
        resp.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", metavar="FILE", help="write the payload to FILE")
    parser.add_argument("--push", action="store_true", help="PUT to /api/action-ledger")
    parser.add_argument("--seed", action="store_true", help="write straight to Supabase")
    args = parser.parse_args()
    load_env()

    if not os.path.exists(SOURCE):
        print(f"{SOURCE} not found -- run scripts/fetch_action_network.py first.",
              file=sys.stderr)
        return 1
    data = json.load(open(SOURCE))
    meta_path = os.path.join(ROOT, "cache", "an_picks_meta.json")
    fetched_at = json.load(open(meta_path)).get("fetched_at") if os.path.exists(meta_path) else None

    rows = build(data)
    payload = {"rows": rows, "fetched_at": fetched_at,
               "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    body = {"data": payload, "etag": etag_of(rows)}
    size = len(json.dumps(payload, separators=(",", ":")))
    kinds = {}
    for r in rows:
        kinds[r["k"]] = kinds.get(r["k"], 0) + 1
    print(f"{len(rows)} tickets ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))}),"
          f" {size / 1e6:.2f} MB, export fetched {fetched_at}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        print(f"Wrote {args.out}")
    if args.seed:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
        if not url or not key:
            print("--seed needs SUPABASE_URL and SUPABASE_KEY", file=sys.stderr)
            return 1
        seed(body, url, key)
        print(f"Seeded action_pages/{SLUG}")
    if args.push:
        user_id = os.environ.get("ADMIN_USER_ID")
        if not user_id:
            print("--push needs ADMIN_USER_ID", file=sys.stderr)
            return 1
        result = push(body, user_id)
        print(f"Pushed to {INGEST_URL}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
