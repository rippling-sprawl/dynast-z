#!/usr/bin/env python3
"""Export your Action Network (actionnetwork.com) tracked picks, futures included.

WHY THIS SOURCE

Action Network's My Action bet tracker has no web UI: actionnetwork.com/my-action
307s to the homepage, and myaction.app/<username> 307s to a Branch deep link that
just opens the phone app. The app exports CSV, but only *settled* picks -- pending
futures, the thing worth analyzing in August, never come out.

They do not need to be scraped off the phone. The actionnetwork.com Next.js
bundles ship a client for the same backend the app talks to, reachable with the
session cookie your browser already holds:

    base      https://api.actionnetwork.com/web
    picks     GET /v1/me/picks
    profile   GET /v1/me
    books     GET /v1/books          (public; maps book_id -> display name)
    auth      header `authorization: <token>`, raw -- NOT `Bearer <token>`
    token     cookie AN_SESSION_TOKEN_V1, domain .actionnetwork.com,
              isHttpOnly:false, ~1 year expiry

FIVE THINGS THAT ARE NOT OBVIOUS, EACH LEARNED THE HARD WAY

1. A User-Agent is mandatory. curl's default UA gets a CloudFront "Request
   blocked" 403 before the request ever reaches the API. The token is a JWT whose
   `agent` claim pins the browser that minted it, so this sends that same string.

2. The response is FOUR arrays, not one: picks (straight bets), groupPicks
   (parlays/teasers), competitionPicks, and custom_picks. Reading only `picks`
   silently drops most futures, since manually-added futures land in custom_picks.

3. `meta.is_future` is the real futures flag. The web bundle's own predicate
   (`custom_pick_type` containing "futures") is NOT sufficient against live data:
   a hand-entered future like "Bears/Lions 1-2 NFC North" has
   custom_pick_type "free_form" and would be missed. is_futures() below takes the
   union of both tests -- the flag, and the app's string test as a backstop.

4. Without a date window the endpoint returns almost nothing. startDate and
   endDate are YYYYMMDD -- not ISO, not epoch. Wide ranges 504 once too many
   picks match, so fetch_window() starts wide and recursively halves on failure.

5. The window does not filter on "picks placed in this range". A pick comes back
   only when the window CONTAINS its entire [starts_at, ends_at] span. For a
   game bet that span is one evening, so chunking works. For a futures ticket it
   is the whole season -- so a future is invisible to every window narrower than
   its own event, and halving a window on timeout makes futures LESS findable,
   not more. On the account this was built against, the chunked crawl found 5
   pending futures; the sweep in fetch_futures_sweep() found 142.

   Hence two passes: chunked crawl for settled history, plus a sweep of windows
   running from a walked-back start date to the far future. Extending the end
   date is free; only the start date costs, so that is the axis that moves.

WHERE THE OUTPUT GOES

cache/, never data/. Every sibling fetch_*.py writes to data/, but data/ is
committed to git and served publicly from the CDN -- a betting history must not
go there. cache/ is already gitignored and is dev-only.

SETUP

    1. Log into actionnetwork.com in a browser.
    2. DevTools -> Application -> Cookies -> actionnetwork.com
    3. Copy the AN_SESSION_TOKEN_V1 value.
    4. Add to .env (gitignored):  ACTION_NETWORK_TOKEN=<paste>

USAGE

    python3 scripts/fetch_action_network.py                 # full history + futures report
    python3 scripts/fetch_action_network.py --incremental   # trailing window, merged on
    python3 scripts/fetch_action_network.py --merge         # full crawl, merged not replaced
    python3 scripts/fetch_action_network.py --since 2025-01 # only from that month
    python3 scripts/fetch_action_network.py --raw           # dump one window untouched
    python3 scripts/fetch_action_network.py --all           # tables for every bucket

KEEPING IT UP TO DATE

--incremental crawls only the last INCREMENTAL_WINDOW_DAYS of event dates and
merges the result onto the existing cache/an_picks.json by pick id, instead of
re-walking the account from 2019. Use it for routine refreshes; run the full
crawl when seeding the cache, or after changing how picks are shaped.

It is a client-side delta, because the API cannot express a server-side one --
there is no "changed since" parameter, and the reasoning is written out above
merge_entries() below. The saving is real but bounded: the futures sweep still
runs in full, since a future is only ever returned by a window containing its
whole event span, and no trailing window does.

--merge applies the same merge to a FULL crawl rather than a trailing one. Use
it when re-crawling everything, because a full run replaces the export and no
two full runs agree exactly: how deep the futures sweep gets before the gateway
starts timing out varies run to run, and the deep-history windows are flaky at
their edges too. Two consecutive full crawls here returned 9962 and 9959 picks,
each holding a handful the other missed. --merge keeps the union; a plain full
crawl keeps only the last run and warns about what it dropped.

IF IT BREAKS

These are undocumented internal endpoints. If a fetch starts 404ing, re-run the
discovery that produced this file: pull the _next/static/chunks/*.js bundles off
actionnetwork.com and grep them for "/v1/me" path literals.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read .env by absolute path rather than by search, so the script works from any
# working directory. Environment variables already set win, as they should.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

API_BASE = "https://api.actionnetwork.com/web"
PICKS_ENDPOINT = "/v1/me/picks"
PROFILE_ENDPOINT = "/v1/me"
BOOKS_ENDPOINT = "/v1/books"

# See note 1 in the module docstring: this is not optional, and it should match
# the `agent` claim baked into the token.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/147.0.0.0 Safari/537.36")

# See note 2: every one of these carries picks, and futures hide in custom_picks.
PICK_ARRAYS = ("picks", "groupPicks", "competitionPicks", "custom_picks")

# Action Network launched in 2017; no account predates it. Used only to sanity
# check --since and to cap how far back a full crawl will walk.
EARLIEST_SEASON = date(2017, 1, 1)

# Futures sweep tuning -- see note 5 in the module docstring. Pushing the end
# date further out is free (the server matches on containment, and nothing is
# scheduled that far ahead), so the horizon is generous. Only the START date
# costs anything, so the sweep walks it back in steps until the server gives up.
SWEEP_HORIZON_YEARS = 4
SWEEP_STEP_DAYS = 15
SWEEP_MAX_FAILS = 2
SWEEP_RETRIES = 3

# --incremental only. How far back the trailing pass-1 window reaches. Bets are
# placed on upcoming events and settle within days of them, so a window this
# wide around today catches new tickets and fresh gradings; anything older has
# already been captured by the full crawl that seeded the cache. It does NOT
# bound futures -- those come from the sweep, which still runs in full.
INCREMENTAL_WINDOW_DAYS = 45

SETUP_HINT = """
Set ACTION_NETWORK_TOKEN before running:

  1. Log into actionnetwork.com in a browser
  2. DevTools -> Application -> Cookies -> actionnetwork.com
  3. Copy the value of the AN_SESSION_TOKEN_V1 cookie
  4. Add this line to .env (it is gitignored):

       ACTION_NETWORK_TOKEN=<paste the cookie value>
""".rstrip()


def repo_path(*parts):
    return os.path.join(ROOT, *parts)


class ApiError(RuntimeError):
    """A request that failed in a way worth reporting to the user verbatim."""


class WindowTooWide(RuntimeError):
    """A 504 -- the window needs splitting, not reporting."""


def curl_json(path, token=None, timeout=60):
    """GET an api.actionnetwork.com path and return parsed JSON.

    subprocess+curl rather than requests/httpx because neither is installed
    anywhere in this repo -- see the sibling fetch_*.py scripts.

    The status code is appended on its own trailing line by -w, so an expired
    token surfaces as "your token expired" rather than a JSON parse error on the
    401 body, and a 504 raises WindowTooWide for the caller to split.
    """
    url = f"{API_BASE}{path}"
    cmd = ["curl", "-s", "--max-time", str(timeout),
           "-w", "\n%{http_code}",
           "-A", USER_AGENT,
           "-H", "Accept: application/json"]
    if token:
        cmd += ["-H", f"authorization: {token}"]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ApiError(f"curl failed for {url}: {result.stderr.strip()}")

    body, _, status = result.stdout.rpartition("\n")
    status, body = status.strip(), body.strip()

    if status == "401":
        raise ApiError(
            "401 Unauthorized -- your Action Network token is expired or was "
            "copied wrong.\nRe-copy the AN_SESSION_TOKEN_V1 cookie into .env "
            "and try again.")
    if status == "403":
        raise ApiError(
            "403 Request blocked (CloudFront, not the API).\nThis usually means "
            "the User-Agent header did not go out -- see note 1 in this file.")
    if status in ("502", "503", "504"):
        raise WindowTooWide(f"HTTP {status}")
    if status != "200":
        raise ApiError(f"HTTP {status} from {url}: {body[:200]}")
    if not body:
        raise ApiError(f"empty response for {url}")
    try:
        return json.loads(body)
    except ValueError:
        # A 200 with an HTML body is their gateway erroring under load; treat it
        # like a 504 so the window gets split rather than aborting the crawl.
        if body.lstrip().startswith("<"):
            raise WindowTooWide("non-JSON gateway response")
        raise ApiError(f"non-JSON response for {url}: {body[:200]}")


def ymd(d):
    return d.strftime("%Y%m%d")


def fetch_window(token, start, end, depth=0):
    """Fetch [start, end] inclusive, halving the window on every timeout.

    Their backend 504s on wide ranges but the threshold moves with load, so a
    fixed chunk size is either too slow or too fragile. Starting wide and
    splitting on failure costs one wasted request per split and adapts itself.
    """
    query = f"{PICKS_ENDPOINT}?startDate={ymd(start)}&endDate={ymd(end)}"
    indent = "  " * depth
    try:
        payload = curl_json(query, token)
    except WindowTooWide:
        if start >= end:
            # A single day that will not load. Report and move on rather than
            # failing the whole crawl for one bad date.
            print(f"{indent}  !! {start} timed out even as a single day -- skipped")
            return [], 1
        mid = start + (end - start) // 2
        print(f"{indent}  .. {start}..{end} too wide, splitting")
        left, l_skip = fetch_window(token, start, mid, depth + 1)
        right, r_skip = fetch_window(token, mid + timedelta(days=1), end, depth + 1)
        return left + right, l_skip + r_skip

    picks = []
    collect(payload, picks)

    if picks:
        print(f"{indent}  {start}..{end}  {len(picks)} picks")
    time.sleep(0.15)  # their gateway is visibly load-sensitive; do not hammer it
    return picks, 0


def collect(payload, into):
    """Flatten the four arrays into `into`, tagging each pick with its source."""
    added = 0
    for name in PICK_ARRAYS:
        for pick in payload.get(name) or []:
            # Which array a pick came from is real information -- groupPicks are
            # parlays, custom_picks are hand-entered -- and it is not otherwise
            # recoverable from the pick body.
            pick["_array"] = name
            into.append(pick)
            added += 1
    return added


def fetch_futures_sweep(token, today):
    """Second pass, and the only one that finds futures reliably. See note 5.

    Because the server returns a pick only when the window CONTAINS its whole
    [starts_at, ends_at] span, a long-dated future is invisible to every window
    narrower than the event itself. The date-chunked crawl therefore finds almost
    none of them -- on a real account it found 5 where this sweep finds 142.

    A window running from S to the far future captures every future whose event
    starts on or after S, so one sufficiently early S would be enough. But the
    server 504s once too many picks match, and reaching further back sweeps in
    more dense settled history. So: walk S backwards until the server refuses,
    and report how far back we got.
    """
    end = date(today.year + SWEEP_HORIZON_YEARS, 12, 31)
    picks, earliest, fails = [], None, 0
    start = today

    while fails < SWEEP_MAX_FAILS and start > EARLIEST_SEASON:
        payload = None
        for _ in range(SWEEP_RETRIES):
            try:
                payload = curl_json(
                    f"{PICKS_ENDPOINT}?startDate={ymd(start)}&endDate={ymd(end)}",
                    token, timeout=120)
                break
            except WindowTooWide:
                continue

        if payload is None:
            fails += 1
            print(f"  .. {start} is too far back for one query "
                  f"({fails}/{SWEEP_MAX_FAILS})")
        else:
            fails = 0
            earliest = start
            n = collect(payload, picks)
            print(f"  {start}..{end}  {n} picks")

        start -= timedelta(days=SWEEP_STEP_DAYS)
        time.sleep(0.15)

    return picks, earliest


def fetch_all(token, since, until):
    """Walk the whole range a year at a time, letting fetch_window split as needed."""
    all_picks, skipped = [], 0
    cursor = since
    while cursor <= until:
        year_end = min(date(cursor.year, 12, 31), until)
        picks, s = fetch_window(token, cursor, year_end)
        all_picks += picks
        skipped += s
        cursor = year_end + timedelta(days=1)

    return all_picks, skipped


def dedupe(picks):
    """Overlapping windows re-return picks. Dedupe on (array, id) -- ids are
    only unique within an array."""
    seen, unique = set(), []
    for pick in picks:
        key = (pick.get("_array"), pick.get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(pick)
    return unique, len(picks) - len(unique)


def fetch_books():
    """book_id -> display name. Public endpoint; failure here is not fatal."""
    try:
        payload = curl_json(BOOKS_ENDPOINT, timeout=30)
    except (ApiError, WindowTooWide):
        return {}
    books = payload.get("books", payload) if isinstance(payload, dict) else payload
    if not isinstance(books, list):
        return {}
    return {b.get("id"): (b.get("display_name") or b.get("name"))
            for b in books if isinstance(b, dict) and b.get("id") is not None}


# ---- classifiers -----------------------------------------------------------
# Ports of the minified predicates in chunks/pages/_app-*.js, except is_futures,
# which had to be widened -- see note 3 in the module docstring.

def is_group_pick(pick):
    """E(): parlays and teasers carry a group_pick_type; straight picks do not."""
    return pick.get("group_pick_type") is not None


def is_futures(pick):
    """The flag the data actually sets, OR the app's string test as a backstop.

    z() in the bundle is only the second half of this. Trusting it alone loses
    every hand-entered future, which are exactly the ones the CSV export also
    misses -- i.e. the whole reason this script exists.
    """
    if (pick.get("meta") or {}).get("is_future"):
        return True
    kind = pick.get("custom_pick_type")
    return isinstance(kind, str) and "futures" in kind


def is_parlay(pick):
    """G()."""
    return is_group_pick(pick) and pick.get("group_pick_type") == "parlay"


def is_teaser(pick):
    """H()."""
    return is_group_pick(pick) and pick.get("group_pick_type") == "teaser"


# ---- odds math -------------------------------------------------------------
# Ported from scripts/primary/bets.js:160-172 so the Python and JS sides agree.

def american_to_decimal(american):
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    if not a:
        return None
    return (a / 100) + 1 if a > 0 else (100 / abs(a)) + 1


def to_win_from_odds(stake, american):
    """Profit if the bet wins, from stake + american odds."""
    d = american_to_decimal(american)
    try:
        s = float(stake)
    except (TypeError, ValueError):
        return None
    if not d or not s:
        return None
    return round(s * (d - 1), 2)


def implied_probability(american):
    """Break-even win rate the price implies, vig included. 0-1."""
    d = american_to_decimal(american)
    return None if not d else 1 / d


# ---- shaping ---------------------------------------------------------------

def describe(pick):
    """A human label. `play` is what the app shows; the rest are fallbacks."""
    if pick.get("play"):
        return pick["play"]
    if is_group_pick(pick):
        legs = pick.get("picks") or []
        return f"{(pick.get('group_pick_type') or 'group').title()} ({len(legs)} legs)"
    competition = pick.get("competition") or {}
    return ((competition.get("meta") or {}).get("title")
            or pick.get("custom_pick_name")
            or "")


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def matchup(pick):
    """"Away @ Home" from the embedded game object, when there is one."""
    teams = ((pick.get("game") or {}).get("teams")) or []
    if len(teams) != 2:
        return None
    game = pick["game"]
    by_id = {t.get("id"): t.get("display_name") or t.get("full_name") for t in teams}
    away = by_id.get(game.get("away_team_id"))
    home = by_id.get(game.get("home_team_id"))
    return f"{away} @ {home}" if away and home else None


# The API embeds the entire game record, the entire competition record, and the
# rules blob for every custom pick. Keeping them verbatim turns a 1k-pick export
# into 35 MB of mostly-duplicated team metadata. Everything dropped here is
# either summarized onto the shaped pick above it or is not about the bet.
HEAVY_RAW_KEYS = ("game", "competition", "custom_pick_rules")


def slim_raw(pick):
    """Drop the heavy blobs, and recurse into a group pick's legs.

    Parlay legs are picks in their own right and each embeds its own copy of the
    game record, so skipping the recursion leaves most of the weight behind.
    """
    out = {}
    for key, value in pick.items():
        if key in HEAVY_RAW_KEYS:
            continue
        if key in ("picks", "custom_picks") and isinstance(value, list):
            out[key] = [slim_raw(leg) if isinstance(leg, dict) else leg
                        for leg in value]
        else:
            out[key] = value
    return out


def normalize(pick, now, books):
    """Flatten one pick to the fields worth analyzing.

    `money_net` is realized profit and sits at 0 while a pick is pending, so
    to_win is always computed from the price instead.
    """
    odds = pick.get("odds")
    stake = pick.get("money")
    created = parse_ts(pick.get("created_at"))
    prob = implied_probability(odds)
    pending = pick.get("result") == "pending"
    return {
        "id": pick.get("id"),
        "description": describe(pick),
        "league": pick.get("league_name"),
        "book": books.get(pick.get("book_id")) or pick.get("book_id"),
        "source": pick.get("_array"),
        "pick_type": pick.get("custom_pick_type") or pick.get("type"),
        "group_pick_type": pick.get("group_pick_type"),
        "is_future": is_futures(pick),
        "odds": odds,
        "odds_decimal": round(american_to_decimal(odds), 4) if american_to_decimal(odds) else None,
        "implied_probability": round(prob, 4) if prob is not None else None,
        "stake": stake,
        "units": pick.get("units"),
        "units_type": pick.get("units_type"),
        "to_win": to_win_from_odds(stake, odds),
        "net": None if pending else pick.get("money_net"),
        "units_net": None if pending else pick.get("units_net"),
        "result": pick.get("result"),
        "status": pick.get("status"),
        "created_at": pick.get("created_at"),
        "starts_at": pick.get("starts_at"),
        "settled_at": pick.get("settled_at"),
        "days_held": (now - created).days if pending and created else None,
        "matchup": matchup(pick),
        "raw": slim_raw(pick),
    }


def bucket_name(pick):
    """Futures first -- a futures parlay is still a future -- then by structure."""
    if is_futures(pick):
        return "futures"
    if is_parlay(pick):
        return "parlays"
    if is_teaser(pick):
        return "teasers"
    return "straight"


def assemble(entries):
    """Build the output file from (bucket, shaped) pairs.

    Split out of bucket() so --incremental can assemble a mix of freshly shaped
    picks and untouched ones carried over from the previous export.
    """
    grouped = {"futures": [], "parlays": [], "teasers": [], "straight": []}
    for name, shaped in entries:
        grouped[name].append(shaped)

    futures = grouped["futures"]
    futures.sort(key=lambda f: f.get("created_at") or "", reverse=True)
    return {
        "futures": {
            "pending": [f for f in futures if f["result"] == "pending"],
            "settled": [f for f in futures if f["result"] != "pending"],
        },
        "parlays": grouped["parlays"],
        "teasers": grouped["teasers"],
        "straight": grouped["straight"],
    }


def bucket(picks, now, books):
    return assemble([(bucket_name(p), normalize(p, now, books)) for p in picks])


# ---- incremental merge -----------------------------------------------------
# There is no "changed since" parameter on this API. I checked three ways:
# /v1/me/picks silently ignores every unknown param (60 name/format combinations
# of updatedSince/modifiedSince/since/... all returned byte-identical payloads);
# the stricter /v1/me/picks/paginated 400s on anything outside a four-name
# allowlist -- startDate, endDate, limit, pageKey -- with no time filter among
# them; and there is no ETag or Last-Modified, with If-Modified-Since ignored.
#
# The reason it cannot exist in the current shape: the only time axis you can
# query is EVENT time, while "changed" is updated_at, and the two are unrelated.
# A real row from this account -- a pick on an August 2025 game carrying
# updated_at of 2026-02-10 -- is invisible to any window drawn around when it
# changed. So the delta has to be computed here, after fetching.
#
# What that buys is still most of the cost: re-crawl a trailing window instead
# of seven years, and merge onto the previous export by id.

def entry_key(shaped):
    """Ids are only unique within their source array -- same key as dedupe()."""
    return (shaped.get("source"), shaped.get("id"))


def load_cached(path):
    """Read a previous export back into (bucket, shaped) pairs.

    Carried-over picks are kept exactly as they were written, never re-derived
    from their own `raw`: slim_raw() drops `game` and `competition`, so
    re-normalizing an old pick would null out its matchup and flatten the
    description of anything without a `play`. The bucket comes from where the
    pick was found rather than from the classifiers, for the same reason.
    """
    with open(path) as f:
        data = json.load(f)

    entries = []
    for name in ("parlays", "teasers", "straight"):
        for shaped in data.get(name) or []:
            entries.append((name, shaped))
    futures = data.get("futures") or {}
    for sub in ("pending", "settled"):
        for shaped in futures.get(sub) or []:
            entries.append(("futures", shaped))
    return entries


def has_changed(old, new):
    """Did this pick actually move, or was it just re-fetched?

    updated_at survives slim_raw and is exactly the field the API maintains for
    this, so it is the primary test. The shaped bodies cannot be compared
    wholesale: days_held is relative to now and would mark every pending pick
    dirty on every run.
    """
    old_raw, new_raw = old.get("raw") or {}, new.get("raw") or {}
    old_ts, new_ts = old_raw.get("updated_at"), new_raw.get("updated_at")
    if old_ts and new_ts:
        return old_ts != new_ts
    return any(old.get(f) != new.get(f)
               for f in ("result", "status", "settled_at", "net", "units_net",
                         "odds", "stake"))


def refresh_days_held(shaped, now):
    """days_held is measured from created_at to now, so it goes stale in the
    cache. Recompute it for carried-over pending picks; nothing else in a
    shaped pick depends on when the export ran."""
    if shaped.get("result") != "pending":
        return shaped
    created = parse_ts(shaped.get("created_at"))
    if created:
        shaped["days_held"] = (now - created).days
    return shaped


def merge_entries(cached, fresh, now):
    """Fresh picks win; everything else is carried over untouched."""
    index = {}
    for name, shaped in cached:
        index[entry_key(shaped)] = (name, refresh_days_held(shaped, now))

    added, updated = 0, 0
    for name, shaped in fresh:
        key = entry_key(shaped)
        prior = index.get(key)
        if prior is None:
            added += 1
        elif has_changed(prior[1], shaped):
            updated += 1
        index[key] = (name, shaped)

    return list(index.values()), added, updated


def warn_if_shrunk(out_path, shaped):
    """A full crawl replaces the file, so it can quietly drop picks a previous
    one found -- and verify() cannot see it, having nothing to compare against.

    This is not hypothetical. Two consecutive full crawls of the same account,
    twelve minutes apart, returned 9962 and 9959 picks: the futures sweep
    bottomed out at 2026-05-03 on the first run and 2026-05-18 on the second,
    and the five pending futures starting in between vanished from the export.
    How deep the sweep gets depends on when the gateway starts timing out, so
    any full run can come back shallower than the one before it.

    Warn rather than fail: a deliberate re-crawl after a shape change may
    legitimately produce fewer picks, and refusing to write would be wrong.
    """
    try:
        previous = load_cached(out_path)
    except (OSError, ValueError):
        return  # nothing to compare against, which is fine

    current = {entry_key(sh) for sh in
               (shaped["futures"]["pending"] + shaped["futures"]["settled"]
                + shaped["parlays"] + shaped["teasers"] + shaped["straight"])}
    dropped = [(name, sh) for name, sh in previous
               if entry_key(sh) not in current]
    if not dropped:
        return

    print(f"  warn  {len(dropped)} pick(s) in the existing export are missing "
          f"from this crawl.")
    print(f"        Most often the futures sweep did not reach as far back this "
          f"time. Re-run with --incremental to merge instead of replacing:")
    for name, sh in dropped[:5]:
        print(f"          [{name}] {(sh.get('description') or '')[:44]} "
              f"({sh.get('result')}, starts {str(sh.get('starts_at'))[:10]})")
    if len(dropped) > 5:
        print(f"          ... and {len(dropped) - 5} more")


def verify_merged(entries, cached, shaped):
    """A merged run may only ever add. Same discipline as verify(): a
    half-working fetch must not clobber an export that was fine."""
    ok = True

    if len(entries) < len(cached):
        print(f"  FAIL  merge lost picks: {len(entries)} after merge vs "
              f"{len(cached)} in the cache")
        ok = False
    else:
        print(f"  ok    {len(entries)} picks after merge, none dropped "
              f"(cache had {len(cached)})")

    total = (len(shaped["futures"]["pending"]) + len(shaped["futures"]["settled"])
             + len(shaped["parlays"]) + len(shaped["teasers"]) + len(shaped["straight"]))
    if total != len(entries):
        print(f"  FAIL  bucketing lost picks: {total} bucketed vs {len(entries)} merged")
        ok = False
    else:
        print(f"  ok    all {total} picks bucketed")

    return ok


def verify(picks, shaped):
    """Refuse to overwrite good data on a thin or malformed response.

    Same discipline as the guard at the end of fetch_nfl_schedule.py: a fetch
    that half-worked must not clobber a previous good export.
    """
    ok = True

    if not picks:
        print("  FAIL  zero picks fetched")
        print("        If the account really has no picks this is correct, but it "
              "is far more\n        likely the response is shaped differently than "
              "PICK_ARRAYS expects.\n        Re-run with --raw and look.")
        ok = False
    else:
        print(f"  ok    {len(picks)} picks fetched")

    typed = sum(1 for p in picks if p.get("type") or p.get("group_pick_type"))
    if picks and typed == 0:
        print("  FAIL  no pick carries `type` or `group_pick_type` -- the schema "
              "moved,\n        so every bucket is meaningless")
        ok = False
    elif picks:
        print(f"  ok    {typed}/{len(picks)} picks carry a type")

    total = (len(shaped["futures"]["pending"]) + len(shaped["futures"]["settled"])
             + len(shaped["parlays"]) + len(shaped["teasers"]) + len(shaped["straight"]))
    if total != len(picks):
        print(f"  FAIL  bucketing lost picks: {total} bucketed vs {len(picks)} fetched")
        ok = False
    else:
        print(f"  ok    all {total} picks bucketed")

    return ok


# ---- reporting -------------------------------------------------------------

def fmt_odds(odds):
    if odds is None:
        return "--"
    try:
        n = int(odds)
    except (TypeError, ValueError):
        return str(odds)
    return f"+{n}" if n > 0 else str(n)


def fmt_money(amount):
    if amount is None:
        return "--"
    try:
        return f"${float(amount):,.2f}"
    except (TypeError, ValueError):
        return str(amount)


def table(rows, title, limit=None):
    """Print a fixed-width table. Terminal output only -- nothing parses this."""
    print(f"\n{title}")
    print("=" * len(title))
    if not rows:
        print("(none)")
        return

    shown = rows[:limit] if limit else rows
    header = ("Description", "League", "Book", "Odds", "Stake", "To win", "Impl", "Held")
    body = []
    for r in shown:
        prob = r["implied_probability"]
        body.append((
            (r["description"] or "")[:46],
            (r["league"] or "")[:6],
            str(r["book"] or "")[:12],
            fmt_odds(r["odds"]),
            fmt_money(r["stake"]),
            fmt_money(r["to_win"]),
            f"{prob * 100:.1f}%" if prob is not None else "--",
            f"{r['days_held']}d" if r["days_held"] is not None else "--",
        ))

    widths = [max(len(header[i]), max(len(row[i]) for row in body))
              for i in range(len(header))]
    line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
    print(line)
    print("-" * len(line))
    for row in body:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    if limit and len(rows) > limit:
        print(f"... and {len(rows) - limit} more (see cache/an_picks.json)")


def num(rows, key):
    return [float(r[key]) for r in rows if isinstance(r[key], (int, float))]


def futures_summary(pending):
    staked = sum(num(pending, "stake"))
    to_win = sum(num(pending, "to_win"))
    probs = num(pending, "implied_probability")

    print(f"\nPending futures: {len(pending)}")
    print(f"  At risk:          {fmt_money(staked)}")
    print(f"  Potential profit: {fmt_money(to_win)}")
    print(f"  Potential return: {fmt_money(staked + to_win)}")
    if probs:
        print(f"  Mean implied win probability: {sum(probs) / len(probs) * 100:.1f}%")
        # Sum of implied probabilities across independent tickets is the expected
        # number of winners -- a useful gut check against "I have 30 live tickets".
        print(f"  Expected winners at market prices: {sum(probs):.1f} of {len(probs)}")

    by_league = {}
    for r in pending:
        by_league.setdefault(r["league"] or "?", []).append(r)
    if len(by_league) > 1:
        print("\n  By league:")
        for league, rows in sorted(by_league.items(), key=lambda kv: -sum(num(kv[1], "stake"))):
            print(f"    {league:<8} {len(rows):>3} tickets  "
                  f"{fmt_money(sum(num(rows, 'stake'))):>10} at risk  "
                  f"{fmt_money(sum(num(rows, 'to_win'))):>12} to win")


def settled_summary(settled, label):
    if not settled:
        return
    nets = num(settled, "net")
    staked = sum(num(settled, "stake"))
    wins = sum(1 for r in settled if r["result"] == "win")
    losses = sum(1 for r in settled if r["result"] == "loss")
    pushes = len(settled) - wins - losses
    print(f"\n{label}: {len(settled)} settled -- {wins}-{losses}-{pushes}")
    if nets and staked:
        net = sum(nets)
        print(f"  Staked {fmt_money(staked)}, net {fmt_money(net)}, "
              f"ROI {net / staked * 100:+.1f}%")


# ---- main ------------------------------------------------------------------

def parse_since(value):
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"--since {value!r}: use YYYY, YYYY-MM, or YYYY-MM-DD")


def main():
    parser = argparse.ArgumentParser(
        description="Export Action Network tracked picks, futures included.")
    parser.add_argument("--since", type=parse_since, metavar="YYYY-MM",
                        help="earliest date to crawl (default: account creation)")
    parser.add_argument("--raw", action="store_true",
                        help="dump one untouched window and exit")
    parser.add_argument("--all", action="store_true",
                        help="also print tables for straight bets, parlays, teasers")
    parser.add_argument("--incremental", action="store_true",
                        help="crawl only a trailing window and merge onto the "
                             "existing cache/an_picks.json")
    parser.add_argument("--window-days", type=int, default=INCREMENTAL_WINDOW_DAYS,
                        metavar="N",
                        help=f"how far back --incremental reaches "
                             f"(default {INCREMENTAL_WINDOW_DAYS})")
    parser.add_argument("--merge", action="store_true",
                        help="merge onto the existing export instead of "
                             "replacing it (implied by --incremental)")
    args = parser.parse_args()

    if args.window_days < 1:
        parser.error("--window-days must be at least 1")
    if args.incremental and args.since:
        parser.error("--incremental and --since both set the crawl start; pick one")

    token = os.environ.get("ACTION_NETWORK_TOKEN", "").strip()
    if not token:
        print("ACTION_NETWORK_TOKEN is not set.", file=sys.stderr)
        print(SETUP_HINT, file=sys.stderr)
        return 1

    cache_dir = repo_path("cache")
    os.makedirs(cache_dir, exist_ok=True)
    today = date.today()

    try:
        profile = curl_json(PROFILE_ENDPOINT, token)
    except (ApiError, WindowTooWide) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Signed in as {profile.get('username')} (id {profile.get('id')})")

    if args.raw:
        start = args.since or (today - timedelta(days=90))
        query = f"{PICKS_ENDPOINT}?startDate={ymd(start)}&endDate={ymd(today)}"
        print(f"Fetching {query}\n")
        try:
            payload = curl_json(query, token)
        except (ApiError, WindowTooWide) as e:
            print(f"{e}\nTry a narrower --since.", file=sys.stderr)
            return 1
        raw_path = os.path.join(cache_dir, "an_picks_raw.json")
        with open(raw_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Wrote the raw response to {os.path.abspath(raw_path)}")
        print(f"\nArray sizes: "
              f"{ {k: len(v) for k, v in payload.items() if isinstance(v, list)} }")
        flat = [p for name in PICK_ARRAYS for p in (payload.get(name) or [])]
        print(f"Futures among them: {sum(1 for p in flat if is_futures(p))}")
        if flat:
            print("\nOne sample pick:")
            print(json.dumps(flat[0], indent=2)[:2500])
        return 0

    out_path = os.path.join(cache_dir, "an_picks.json")
    meta_path = os.path.join(cache_dir, "an_picks_meta.json")

    # --incremental picks the window; --merge picks what happens to the result.
    # A full crawl can come back shallower than the last one (see
    # warn_if_shrunk), so --merge makes a re-crawl additive: it recovers the
    # deep-history picks a single run misses without dropping the futures that
    # run's sweep could not reach.
    merging = args.incremental or args.merge

    cached, prior_meta = None, {}
    if merging:
        try:
            cached = load_cached(out_path)
        except (OSError, ValueError) as e:
            flag = "--incremental" if args.incremental else "--merge"
            print(f"{flag} needs an existing export to merge onto, and "
                  f"{out_path}\ncould not be read ({e}).\nRun once with no "
                  f"flags to seed it.", file=sys.stderr)
            return 1
        try:
            with open(meta_path) as f:
                prior_meta = json.load(f)
        except (OSError, ValueError):
            # Only used to carry the original crawl's start date forward into
            # the new metadata. Not worth failing over.
            prior_meta = {}
    if args.incremental:
        since = today - timedelta(days=args.window_days)
        print(f"Incremental: {len(cached)} picks in the cache, crawling back to "
              f"{since} ({args.window_days}d)\n")
    else:
        since = args.since or (parse_ts(profile.get("created_at")) or datetime(2017, 1, 1, tzinfo=timezone.utc)).date()
        since = max(since, EARLIEST_SEASON)
        if merging:
            print(f"Merging onto {len(cached)} cached picks\n")

    print(f"Pass 1/2 -- settled history, {since} .. {today}")
    print("  (widest windows first, splitting on timeout)\n")
    try:
        history, skipped = fetch_all(token, since, today)
    except ApiError as e:
        print(str(e), file=sys.stderr)
        return 1

    # The sweep runs in full even incrementally, and is the floor on what an
    # incremental fetch costs. A future is only returned by a window containing
    # its whole span, so no trailing window can find one: on the run this was
    # built against, 8 of the 21 newly-placed picks were pending futures.
    print("\nPass 2/2 -- futures sweep, walking the start date back\n")
    try:
        swept, sweep_floor = fetch_futures_sweep(token, today)
    except ApiError as e:
        print(str(e), file=sys.stderr)
        return 1

    picks, dupes = dedupe(history + swept)

    books = fetch_books()
    now = datetime.now(timezone.utc)

    added = updated = 0
    if merging:
        fresh = [(bucket_name(pick), normalize(pick, now, books)) for pick in picks]
        entries, added, updated = merge_entries(cached, fresh, now)
        shaped = assemble(entries)
        print(f"\nMerged {len(picks)} fetched picks onto {len(cached)} cached: "
              f"{added} new, {updated} changed, "
              f"{len(picks) - added - updated} unchanged")
    else:
        entries = None
        shaped = bucket(picks, now, books)

    print("\nVerifying:")
    if skipped:
        print(f"  warn  {skipped} day-window(s) skipped after repeated timeouts")
    if dupes:
        print(f"  ok    {dupes} duplicate(s) dropped across overlapping windows")
    if sweep_floor:
        print(f"  ok    futures sweep reached back to {sweep_floor}")
    else:
        print("  warn  the futures sweep never completed a window -- pending "
              "futures are\n        almost certainly undercounted")
    if merging:
        checks_pass = verify_merged(entries, cached, shaped)
    else:
        checks_pass = verify(picks, shaped)
        warn_if_shrunk(out_path, shaped)
    if not checks_pass:
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    with open(out_path, "w") as f:
        # Indented, unlike the data/ fetchers: this file is read by a human on
        # one machine, never shipped to a page.
        json.dump(shaped, f, indent=2)
    written = len(entries) if merging else len(picks)
    print(f"\nWrote {written} picks to {os.path.abspath(out_path)} "
          f"({os.path.getsize(out_path) / 1024:.0f} KB)")

    with open(meta_path, "w") as f:
        # No token in here, ever. This file is local-only, but a credential does
        # not belong in an artifact regardless.
        json.dump({
            "source": "Action Network (My Action)",
            "endpoint": f"{API_BASE}{PICKS_ENDPOINT}",
            "username": profile.get("username"),
            # An incremental run only crawled a trailing window, but the file
            # it wrote still covers everything the seeding crawl reached, so the
            # recorded range is the original one.
            # The file keeps everything the earlier crawls reached, so when
            # merging the recorded start is the earliest of the two.
            "range": {
                "since": min(filter(None, [
                    since.isoformat(),
                    prior_meta.get("range", {}).get("since") if merging else None,
                ])),
                "until": today.isoformat(),
            },
            "mode": ("incremental" if args.incremental
                     else "full+merge" if args.merge else "full"),
            "merge": {
                "window_days": args.window_days if args.incremental else None,
                "window_start": since.isoformat(),
                "fetched": len(picks),
                "added": added,
                "updated": updated,
                "previous_fetched_at": prior_meta.get("fetched_at"),
            } if merging else None,
            "pick_count": written,
            "futures_pending": len(shaped["futures"]["pending"]),
            "futures_settled": len(shaped["futures"]["settled"]),
            "parlays": len(shaped["parlays"]),
            "teasers": len(shaped["teasers"]),
            "straight": len(shaped["straight"]),
            "windows_skipped": skipped,
            "futures_sweep_floor": sweep_floor.isoformat() if sweep_floor else None,
            "size_bytes": os.path.getsize(out_path),
            "fetched_at": now.isoformat(timespec="seconds"),
            "fetched_ts": int(time.time()),
        }, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")

    pending = shaped["futures"]["pending"]
    table(pending, "Pending futures")
    futures_summary(pending)
    if sweep_floor:
        print(f"\n  Coverage: the sweep reached {sweep_floor}. A pending future "
              f"whose event\n  STARTED before then can be missed -- the API only "
              f"returns a pick when the\n  query window contains its whole span, "
              f"and windows that early time out.")
    settled_summary(shaped["futures"]["settled"], "Futures")

    if args.all:
        table(shaped["straight"], "Straight bets", limit=40)
        table(shaped["parlays"], "Parlays", limit=40)
        table(shaped["teasers"], "Teasers", limit=40)
    else:
        print(f"\n({len(shaped['straight'])} straight, {len(shaped['parlays'])} "
              f"parlays, {len(shaped['teasers'])} teasers -- --all to see them)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
