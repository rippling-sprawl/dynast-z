#!/usr/bin/env python3
"""Build the Action Network book as a page model and push it.

This is the data half of what used to be scripts/render_futures.py. That script
read cache/an_picks.json and wrote twenty committed HTML files under
views/football/; this one writes a small JSON model per page, pushes it to
Supabase, and lets api/action.py render it per request out of one shell template
and the three board builders in api/_action/render.py.

    cache/an_picks.json ─┐
    nfl_schedule.json ───┤ build_action.py ─┬─> PUT /api/action-ingest ─> Supabase
    static.sprtactn.co ──┘                  └─> assets/action/<sha8>.png (committed)

TWO CADENCES, AND THE GAP BETWEEN THEM

Bet data goes live on a push, in seconds, without a deploy. Artwork does not: it
is committed, content-addressed files served straight off the CDN as immutable,
so a brand-new headshot is not live until you commit assets/action/ and push. In
between, that row renders with the placeholder thumb() already draws for art it
could not fetch -- it degrades rather than breaking, and this script prints the
list of new files at the end so it is never a surprise.

That is the deliberate trade for not stuffing base64 into a database: the
artwork almost never changes and the data changes daily, so they are cached on
completely different terms and a stale image costs one deploy rather than
re-sending 1.5 MB of it on every page load, which is what the generated files did.

WHY THE MODEL IS TRIMMED

cache/an_picks.json is 28 MB and carries far more per pick than the board shows.
trim_pick() keeps exactly the fields api/_action/render.py reads, which is what
makes a week's page a few KB of JSON instead of a slice of the whole export.

USAGE

    python3 scripts/build_action.py                  build, report, write nothing
    python3 scripts/build_action.py --out DIR        dump the page models to DIR
    python3 scripts/build_action.py --push           PUT to /api/action-ingest
    python3 scripts/build_action.py --seed           write straight to Supabase
    python3 scripts/build_action.py --standalone     the offline/Artifact copies
    python3 scripts/build_action.py --prune-images   drop unreferenced artwork

--push needs ADMIN_USER_ID (a users.id with role 'admin'); --seed needs
SUPABASE_URL and SUPABASE_KEY. Both read .env if it is there.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The render half lives under api/ because Vercel will not bundle scripts/**
# with a serverless function. Importing it the other way round is safe: this
# script only ever runs locally.
sys.path.insert(0, os.path.join(ROOT, "api"))
from _action import render as R  # noqa: E402

SOURCE = os.path.join(ROOT, "cache", "an_picks.json")
IMG_CACHE = os.path.join(ROOT, "cache", "an_images")
ASSET_DIR = os.path.join(ROOT, "assets", "action")
OUT_DIR = os.path.join(ROOT, "cache", "action")
IMG_PX = 72

SEASON = 2026
SCHEDULE = os.path.join(ROOT, "data", f"nfl_schedule_{SEASON}.json")

INGEST_URL = os.environ.get("ACTION_INGEST_URL",
                            "https://www.dynastz.com/api/action-ingest")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/147.0.0.0 Safari/537.36")


def load_env():
    """Read .env the way the other scripts here do -- no dependency for it."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# ---- images ----------------------------------------------------------------
#
# Content-addressed: the file name IS the hash of the bytes, so a changed image
# is a new file and a stale URL is impossible. That is what earns the immutable
# Cache-Control on /assets/action/* in vercel.json without any of build.py's
# ?v= machinery.

NEW_IMAGES = []


def write_image(url):
    """Download once, downscale, commit as assets/action/<sha8>.png -> sha8.

    Returns "" when the art cannot be had, which render.thumb() reads as "no
    mark for this row" and draws the placeholder for. The download cache under
    cache/an_images/ is keyed by URL and the asset by content, so a re-run is
    offline and writes nothing."""
    if not url:
        return ""
    os.makedirs(IMG_CACHE, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cached = os.path.join(IMG_CACHE, f"{key}.png")

    if not os.path.exists(cached):
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-A", USER_AGENT, url],
            capture_output=True)
        if result.returncode != 0 or not result.stdout:
            return ""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
            img.thumbnail((IMG_PX, IMG_PX), Image.LANCZOS)
            img.save(cached, "PNG", optimize=True)
        except Exception:
            return ""

    with open(cached, "rb") as f:
        blob = f.read()
    sha = hashlib.sha256(blob).hexdigest()[:8]
    os.makedirs(ASSET_DIR, exist_ok=True)
    asset = os.path.join(ASSET_DIR, f"{sha}.png")
    if not os.path.exists(asset):
        with open(asset, "wb") as f:
            f.write(blob)
        NEW_IMAGES.append(f"{sha}.png")
    return sha


def inline_images(shas):
    """{key: data: URI} for the standalone copy, read back off the committed PNGs.

    The Artifact runtime blocks every external host, so that copy cannot link
    /assets/action/*. It is the only reason the inlining code still exists."""
    out = {}
    for key, sha in (shas or {}).items():
        path = os.path.join(ASSET_DIR, f"{sha}.png") if sha else ""
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                out[key] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        else:
            out[key] = ""
    return out


# ---- the league calendar ---------------------------------------------------
#
# A game bet is filed by the week it plays in, and the week is not something the
# book records: Action Network stamps a kickoff on a ticket and nothing else. So
# it comes from the schedule instead -- data/nfl_schedule_2026.json, the
# committed ESPN pull, which carries a window per week. Matching on game id is
# not an option: ESPN's ids and Action Network's are unrelated numbers.


def load_weeks():
    """The season as [{week, start, end, first, last}], in UTC, contiguous.

    ESPN's own week windows leave a two-day hole between the Tuesday a week
    closes and the Thursday the next one opens, so a game flexed into it would
    belong to no week at all. Each week is therefore stretched to run until the
    next one starts, which files a Tuesday make-up under the week it was moved
    out of. `first`/`last` are the real kickoffs, which is what the slate runs
    between -- the window itself opens on the Wednesday and would misreport it.

    Returns [] if the file is missing; the board still renders, with every game
    bet in one undated block rather than in a week."""
    try:
        with open(SCHEDULE) as f:
            weeks = json.load(f)["weeks"]
    except (OSError, ValueError, KeyError):
        return []

    weeks = sorted(weeks, key=lambda w: w["start"])
    spans = []
    for i, week in enumerate(weeks):
        start = R.parse_ts(week["start"])
        end = R.parse_ts(weeks[i + 1]["start"] if i + 1 < len(weeks)
                         else week["end"])
        if not (start and end):
            continue
        kicks = sorted(k for k in (R.parse_ts(g.get("kickoff"))
                                   for g in week.get("games") or []) if k)
        spans.append({"week": week["week"], "start": start, "end": end,
                      "first": kicks[0] if kicks else start,
                      "last": kicks[-1] if kicks else end})
    return spans


def span_label(week):
    """"Thu 10 - Mon 14 Sep" -- the days a week's slate runs between."""
    first = week["first"].astimezone(R.EASTERN)
    last = week["last"].astimezone(R.EASTERN)
    if first.date() == last.date():
        return first.strftime("%a %-d %b")
    head = first.strftime("%a %-d" if first.month == last.month else "%a %-d %b")
    return f"{head} – {last.strftime('%a %-d %b')}"


# Sort keys for the blocks that are not a numbered week. Preseason leads the
# season, the postseason follows week 18, and anything the calendar does not
# cover at all -- another league, an exhibition -- lands after both.
PRESEASON, POSTSEASON, UNSCHEDULED = 0, 99, 100

# order -> (slug, strip label) for the blocks that are not a numbered week.
OFF_CALENDAR = {PRESEASON: ("preseason", "Pre"),
                POSTSEASON: ("postseason", "Post"),
                UNSCHEDULED: ("other", "Other")}


def slate_of(ticket, weeks):
    """(order, label, span) -- the block a non-futures ticket is filed under.

    A ticket is filed by when it plays rather than by when it was placed, so
    the stamp is the earliest kickoff among its legs and only falls back to the
    ticket's own when it has none. Anything off the regular-season calendar
    keeps a block of its own rather than being forced into a week it is not in.
    """
    starts = sorted(s for s in (leg.get("starts_at") for leg in R.legs_of(ticket))
                    if s)
    stamp = R.parse_ts(starts[0] if starts else ticket.get("starts_at"))
    league = (ticket.get("league") or "nfl").lower()

    if stamp and weeks and league == "nfl":
        for week in weeks:
            if week["start"] <= stamp < week["end"]:
                return week["week"], f"Week {week['week']}", span_label(week)
        if stamp < weeks[0]["start"]:
            return PRESEASON, "Preseason", ""
        return POSTSEASON, "Postseason", ""
    return UNSCHEDULED, "Other", ""


def is_live(ticket, now):
    ends = (R.parse_ts(ticket["raw"].get("ends_at"))
            or R.parse_ts(ticket.get("starts_at")))
    if ends and ends < now:
        return False
    return not any(leg.get("result") == "loss" for leg in R.legs_of(ticket))


def build_slates(live, weeks):
    """Every page of the game book, in calendar order, empty weeks included."""
    pages = {}
    for week in weeks:
        pages[week["week"]] = {
            "slug": f"week-{week['week']}", "label": f"Week {week['week']}",
            "short": str(week["week"]), "span": span_label(week),
            "multis": [], "singles": []}

    for ticket in live:
        order, label, span = slate_of(ticket, weeks)
        slug, short = OFF_CALENDAR.get(order, (f"week-{order}", str(order)))
        page = pages.setdefault(order, {"slug": slug, "label": label,
                                        "short": short, "span": span,
                                        "multis": [], "singles": []})
        page["singles" if ticket["_kind"] == "straight" else "multis"].append(ticket)

    out = []
    for order in sorted(pages):
        page = pages[order]
        page["tickets"] = page["multis"] + page["singles"]
        out.append(page)
    return out


# ---- the page model --------------------------------------------------------
#
# Exactly the fields api/_action/render.py reads, and nothing else. Keeping this
# in step with the renderer is the one real maintenance cost of the split, so
# the lists below name the reader for each field.

# thumb(), market_of(), split_pick(), ticket_tag(), render_leg()
LEG_FIELDS = ("play", "odds", "units", "image", "game_id", "starts_at",
              "result", "side_id")
# render_pick(), render_ticket(), won(), ticket_tag(), render_stale()
PICK_FIELDS = ("description", "odds", "units", "stake", "to_win", "starts_at",
               "matchup", "league", "_kind")
RAW_FIELDS = ("image", "side_id", "game_id", "ends_at")


def trim_meta(meta):
    """market_of() reads description; render_ticket() reads tease."""
    meta = meta or {}
    out = {}
    if meta.get("description"):
        out["description"] = meta["description"]
    if meta.get("tease") is not None:
        out["tease"] = meta["tease"]
    return out


def trim_leg(leg):
    out = {k: leg[k] for k in LEG_FIELDS if leg.get(k) is not None}
    meta = trim_meta(leg.get("meta"))
    if meta:
        out["meta"] = meta
    return out


def trim_pick(pick):
    raw = pick.get("raw") or {}
    out = {k: pick[k] for k in PICK_FIELDS if pick.get(k) is not None}
    trimmed = {k: raw[k] for k in RAW_FIELDS if raw.get(k) is not None}
    meta = trim_meta(raw.get("meta"))
    if meta:
        trimmed["meta"] = meta
    for key in ("picks", "custom_picks"):
        legs = raw.get(key)
        if legs:
            trimmed[key] = [trim_leg(leg) for leg in legs]
    out["raw"] = trimmed
    return out


def image_keys(picks):
    """Every image key the given tickets will ask for, logos included.

    All 32 club marks ride along because the futures ledger draws a row per club
    whether or not anything is on it, and a sha is 8 bytes where the data: URI
    it replaced was several KB."""
    keys = set()
    for pick in picks:
        raw = pick.get("raw") or {}
        if raw.get("image"):
            keys.add(raw["image"])
        for leg in R.legs_of(pick):
            if leg.get("image"):
                keys.add(leg["image"])
    return keys


def games_for(picks, games):
    """The subset of the game-id -> matchup map these tickets actually use."""
    out = {}
    for pick in picks:
        for leg in R.legs_of(pick):
            gid = leg.get("game_id")
            if gid and games.get(gid):
                out[str(gid)] = games[gid]
    return out


def etag_of(page):
    """The page's HTTP validator: a hash of exactly what will be rendered."""
    canonical = json.dumps(page, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def push(pages, user_id):
    body = json.dumps({"pages": pages}).encode()
    req = urllib.request.Request(INGEST_URL, data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-User-Id", user_id)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def seed(pages, url, key):
    """Write straight to Supabase, so the first fill needs no live endpoint."""
    rows = [{"slug": slug, "data": page["data"], "etag": page["etag"],
             "updated_at": "now()"} for slug, page in pages.items()]
    req = urllib.request.Request(
        f"{url}/rest/v1/action_pages?on_conflict=slug",
        data=json.dumps(rows).encode(), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req) as resp:
        resp.read()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", metavar="DIR",
                        help="write the page models to DIR as JSON")
    parser.add_argument("--push", action="store_true",
                        help="PUT the book to /api/action-ingest")
    parser.add_argument("--seed", action="store_true",
                        help="write the book straight to Supabase")
    parser.add_argument("--standalone", action="store_true",
                        help="also write the offline copies to cache/action/")
    parser.add_argument("--prune-images", action="store_true",
                        help="delete assets/action/*.png nothing references")
    args = parser.parse_args()

    load_env()

    if not os.path.exists(SOURCE):
        print(f"{SOURCE} not found -- run scripts/fetch_action_network.py first.",
              file=sys.stderr)
        return 1

    data = json.load(open(SOURCE))
    pending = [p for p in data["futures"]["pending"] if p.get("league") == "nfl"]
    if not pending:
        print("No pending NFL futures in the export.", file=sys.stderr)
        return 1

    pending.sort(key=lambda p: -(p["stake"] if isinstance(p["stake"], (int, float)) else 0))
    print(f"{len(pending)} pending NFL futures")

    # Everything else still open. `_kind` is stamped here rather than inferred
    # downstream because the export's own bucketing is the only place a teaser
    # is told apart from a parlay -- both carry group_pick_type "parlay" on
    # some rows, and a teaser's tease points live in meta, not in its type.
    now = datetime.now(timezone.utc)
    others = []
    for kind in ("parlays", "teasers", "straight"):
        for pick in data.get(kind, []):
            if pick.get("result") == "pending":
                others.append(dict(pick, _kind=kind))
    live = [t for t in others if is_live(t, now)]
    stale = [t for t in others if not is_live(t, now)]
    print(f"{len(live)} other pending tickets live, "
          f"{len(stale)} decided but ungraded (listed, not totalled)")

    # A parlay every leg of which is a season future is a futures ticket,
    # whatever bucket the book files it in, so it goes on the futures page
    # beside the other markets whose field is the whole league. What is left is
    # the game book, and that is filed by the week it plays in.
    fut_multis, rest = [], []
    for ticket in live:
        wager = (fut_multis if ticket["_kind"] != "straight"
                 and R.is_season_futures(ticket) else rest)
        wager.append(ticket)

    weeks = load_weeks()
    if weeks:
        print(f"{len(weeks)} weeks of the {SEASON} schedule loaded -- "
              f"{len(fut_multis)} live tickets are season-futures parlays and "
              f"go on the futures page, {len(rest)} into a week")
    else:
        print(f"WARNING: {SCHEDULE} not found -- game bets cannot be grouped "
              f"by week and all land on the 'other' page. Run "
              f"scripts/fetch_nfl_schedule.py --season {SEASON}.",
              file=sys.stderr)

    # game id -> "Away @ Home". Parlay legs keep a game id but the fetcher
    # strips the game record off them, so the label has to be borrowed from a
    # straight bet on the same game. Built off the whole export, settled
    # included, which is what gets the coverage up.
    games = {}
    for bucket in (data["futures"]["pending"], data["futures"]["settled"],
                   data.get("parlays", []), data.get("teasers", []),
                   data.get("straight", [])):
        for pick in bucket:
            gid = pick["raw"].get("game_id")
            if gid and pick.get("matchup"):
                games[gid] = pick["matchup"]

    scopes = [R.attribute(p)[0] for p in pending]
    print(f"Attribution: {scopes.count('team')} to a team, "
          f"{scopes.count('division')} to a division, "
          f"{scopes.count('league')} to a league-wide market, "
          f"{scopes.count('other')} to neither")

    # Every distinct image on the board, downscaled and committed once.
    urls = image_keys(pending + live + stale)
    print(f"Resolving {len(urls)} pick images + 32 team marks ...")
    shas = {}
    for url in sorted(urls):
        shas[url] = write_image(url)
    for abbr in R.TEAMS_BY_ABBR:
        shas[f"logo:{abbr}"] = write_image(R.LOGOS[abbr])
    missing = sorted(u for u in urls if not shas[u])
    if missing:
        print(f"  {len(missing)} image(s) could not be fetched -- placeholder shown")

    # The futures page is a page of the book like any week, so it carries the
    # same record: it leads the strip and the grid, and its span is the season.
    futures = {"slug": "futures", "label": "Futures", "short": "Futures",
               "span": f"{SEASON} season", "lead": True,
               "tickets": pending + fut_multis, "multis": [], "singles": []}
    slates = [futures] + build_slates(rest, weeks)

    # The strip and the grid, precomputed. This is what lets week 3 be rendered
    # without loading week 12: a page carries the shape of the whole book but
    # none of the other pages' tickets.
    nav = [{"slug": p["slug"], "label": p["label"], "short": p["short"],
            "span": p["span"], "lead": bool(p.get("lead")),
            "count": len(p["tickets"]), "risk": R.staked(p["tickets"]),
            "win": R.won(p["tickets"])} for p in slates]

    generated = now.strftime("%d %b %Y")
    all_tickets = [t for p in slates for t in p["tickets"]]
    weeks_live = sum(1 for p in slates if p["tickets"] and not p.get("lead"))

    def shell(slug, kind, title, head, label):
        return {"kind": kind, "slug": slug, "title": title, "head": head,
                "label": label, "generated": generated, "nav": nav}

    models = {}

    index = shell("index", "index", "Action", "Action Network", "Action")
    index["stale"] = [trim_pick(t) for t in stale]
    index["images"] = {}          # render_stale draws no marks
    index["totals"] = {"count": len(all_tickets), "risk": R.staked(all_tickets),
                       "win": R.won(all_tickets)}
    index["weeks_live"] = weeks_live
    models["index"] = index

    for page in slates:
        if page["slug"] == "futures":
            model = shell("futures", "futures", "NFL Futures", "NFL Futures",
                          "Futures")
            model["pending"] = [trim_pick(p) for p in pending]
            model["fut_multis"] = [trim_pick(t) for t in fut_multis]
            board = pending + fut_multis
        else:
            model = shell(page["slug"], "slate", page["label"], page["label"],
                          page["label"])
            model["span"] = page["span"]
            model["multis"] = [trim_pick(t) for t in page["multis"]]
            model["singles"] = [trim_pick(t) for t in page["singles"]]
            board = page["tickets"]
        keys = image_keys(board) | {f"logo:{a}" for a in R.TEAMS_BY_ABBR}
        model["images"] = {k: shas.get(k, "") for k in sorted(keys)}
        model["games"] = games_for(board, games)
        models[model["slug"]] = model

    payload = {slug: {"data": model, "etag": etag_of(model)}
               for slug, model in models.items()}
    sizes = {slug: len(json.dumps(p["data"])) for slug, p in payload.items()}
    print(f"\n{len(payload)} pages, {sum(sizes.values()) / 1024:.0f} KB of JSON "
          f"in all, largest {max(sizes.values()) / 1024:.0f} KB "
          f"({max(sizes, key=sizes.get)})")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for slug, page in payload.items():
            with open(os.path.join(args.out, f"{slug}.json"), "w") as f:
                json.dump(page, f, indent=2)
        print(f"Wrote {len(payload)} page models to {args.out}/")

    if args.standalone:
        os.makedirs(OUT_DIR, exist_ok=True)
        css = open(os.path.join(ROOT, "styles", "football", "action.css")).read()
        tpl = R.load_template("standalone").replace("%%CSS%%", css)
        for slug, page in payload.items():
            model = dict(page["data"])
            model["images"] = inline_images(model["images"])
            html = R.render_page(model, href=lambda s: f"{s}.html", template=tpl)
            with open(os.path.join(OUT_DIR, f"{slug}.html"), "w") as f:
                f.write(html)
        print(f"Wrote {len(payload)} standalone pages to "
              f"{os.path.relpath(OUT_DIR, ROOT)}/")

    if args.seed:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
        if not (url and key):
            print("SUPABASE_URL and SUPABASE_KEY are required for --seed",
                  file=sys.stderr)
            return 1
        print(f"Seeded {seed(payload, url, key)} rows into action_pages")

    if args.push:
        user_id = os.environ.get("ADMIN_USER_ID")
        if not user_id:
            print("ADMIN_USER_ID is required for --push", file=sys.stderr)
            return 1
        try:
            result = push(payload, user_id)
        except urllib.error.HTTPError as e:
            print(f"Push failed: {e.code} {e.read().decode()[:300]}",
                  file=sys.stderr)
            return 1
        print(f"Pushed to {INGEST_URL}: {len(result.get('changed', []))} changed"
              f", {result.get('unchanged', 0)} unchanged"
              f", {len(result.get('removed', []))} removed")
        for slug in result.get("changed", []):
            print(f"  changed  {slug}")
        for slug in result.get("removed", []):
            print(f"  removed  {slug}")

    referenced = {sha for sha in shas.values() if sha}
    if args.prune_images and os.path.isdir(ASSET_DIR):
        dropped = 0
        for name in sorted(os.listdir(ASSET_DIR)):
            if name.endswith(".png") and name[:-4] not in referenced:
                os.remove(os.path.join(ASSET_DIR, name))
                dropped += 1
        print(f"Pruned {dropped} unreferenced image(s) from assets/action/")

    if NEW_IMAGES:
        print(f"\n{len(NEW_IMAGES)} NEW image(s) in assets/action/ -- commit and "
              "push them,\n  or those rows render as a placeholder until you do. "
              "Data is live either way.")
        for name in NEW_IMAGES[:20]:
            print(f"  {name}")
        if len(NEW_IMAGES) > 20:
            print(f"  ... and {len(NEW_IMAGES) - 20} more")
    elif args.push or args.seed:
        print("\nNo new artwork -- nothing to commit, the push is the whole update.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
