#!/usr/bin/env python3
"""
Shared client for the balldontlie NFL API (https://nfl.balldontlie.io).

Why this is a module and not copied into each script
----------------------------------------------------
The house style in scripts/ is a self-contained file that copies its own
`curl_fetch`, and that duplication is deliberate where it matters: the copy in
fetch_nfl_schedule.py carries a docstring saying it must NOT have the browser
User-Agent its sibling fetch_nfl_weekly.py cannot work without. Divergence there
is the whole point.

Nothing like that is true here. Four scripts share one keyed, cursor-paginated,
rate-limited client with a record/replay layer, and the invariants that layer
depends on -- cassette key derivation, cursor-advance guarding, rate-limit
accounting -- are exactly the kind that break silently when copied. The
precedent is scripts/outright_common.py, imported by the four parse_*_outrights
scripts; the import shape below is copied from them.

Each caller still copies the trivial helpers (repo_path, the dotenv block)
inline, because those are the ones worth duplicating.

Record / replay
---------------
The paid endpoints (/stats, /team_stats at ALL-STAR; /plays, /odds,
/player_props at GOAT) are reachable only while a subscription or the 48-hour
trial is live. Every response this module fetches is therefore written to a
cassette under cache/bdl/, and every caller can re-run itself from those
cassettes afterwards with --replay, offline, forever, at zero cost. That is what
makes the dry-run examples reproducible after the trial expires.

    auto     replay if a cassette exists, else fetch live and record  (default)
    record   always fetch live, always overwrite the cassette
    replay   never touch the network; a gap raises CassetteMiss
    live     fetch live, write nothing

Output goes to cache/, never data/ -- cache/ is gitignored, and none of this is
shaped for the CDN. Nothing here is invoked by build.py or vercel.json, and it
must stay that way: no deploy may ever require a live API key.

Setup:
    1. Sign up at https://app.balldontlie.io/signup
    2. Add to .env (gitignored):  BALLDONTLIE_API_KEY=<key>
"""

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read .env by absolute path rather than by search, so callers work from any
# working directory. Environment variables already set win, as they should.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

API_BASE = "https://api.balldontlie.io/nfl/v1"
CASSETTE_DIR = os.path.join(ROOT, "cache", "bdl")

# One JSON object per line rather than one JSON array, because bdl_latency.py
# appends ~3,000 rows over a single game and rewriting a growing array on every
# request is the kind of quadratic that only shows up once it is too late to fix.
INDEX_PATH = os.path.join(CASSETTE_DIR, "_index.jsonl")

SETUP_HINT = """BALLDONTLIE_API_KEY is not set.

  1. Sign up at https://app.balldontlie.io/signup
  2. Copy the API key from the dashboard
  3. Add this line to .env (it is gitignored):

       BALLDONTLIE_API_KEY=<paste the key>

Or run with --replay to work entirely from previously recorded cassettes."""

# Published rate limits, requests per minute. The default below is deliberately
# half of GOAT's 600: the ceiling is shared with anything else using the key, and
# the whole workload peaks at ~9.4 req/min anyway (see
# docs/research/nfl-live-data-apis.md). Override with BDL_RATE_LIMIT -- set it to
# 5 when working on a free key and the limiter handles the 12-second spacing.
TIER_RATE = {"free": 5, "allstar": 60, "goat": 600}
DEFAULT_RATE = 300

# Politeness floor between requests, matching the time.sleep(0.15) habit of the
# other fetchers in this directory.
MIN_INTERVAL = 0.1

# Which tier each endpoint needs. This exists for one reason: balldontlie
# answers an under-tier request with a bare 401, the same status it uses for a
# missing or wrong key. Without this table every "your subscription does not
# cover /plays" would be reported as "check your API key", and after the trial
# expires that is the wrong thing to tell someone.
MIN_TIER = {
    "/teams": "free",
    "/players": "free",
    "/games": "free",
    "/players/active": "allstar",
    "/stats": "allstar",
    "/season_stats": "allstar",
    "/team_stats": "allstar",
    "/team_season_stats": "allstar",
    "/standings": "allstar",
    "/player_injuries": "allstar",
    "/plays": "goat",
    "/odds": "goat",
    "/player_props": "goat",
    "/player_designations": "goat",
    "/advanced_stats": "goat",
    "/dfs": "goat",
    "/fantasy": "goat",
}


class BdlError(RuntimeError):
    """Base. Message is written to be shown to the user verbatim."""


class AuthError(BdlError):
    """401 on a free-tier path: the key is missing, wrong, or revoked."""


class TierError(BdlError):
    """401 on a path above the key's tier. Not the same problem as AuthError."""


class RateLimited(BdlError):
    """429 that survived the retry ladder."""


class ServerError(BdlError):
    """5xx, or a gateway HTML page served with a 200."""


class CassetteMiss(BdlError):
    """--replay was asked for a request that was never recorded."""


def api_key(required=True):
    key = (os.environ.get("BALLDONTLIE_API_KEY") or "").strip()
    if not key and required:
        raise AuthError(SETUP_HINT)
    return key


def rate_limit():
    raw = (os.environ.get("BDL_RATE_LIMIT") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    tier = (os.environ.get("BDL_TIER") or "").strip().lower()
    return TIER_RATE.get(tier, DEFAULT_RATE)


def min_tier(path):
    """Longest-prefix match, so /odds/opening resolves through /odds."""
    best = None
    for prefix, tier in MIN_TIER.items():
        if path == prefix or path.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, tier)
    return best[1] if best else "free"


def build_url(path, params=None):
    """The array parameters are literally named `seasons[]`, `game_ids[]`. Keep
    the brackets unencoded -- percent-encoded they are a differently-named key,
    and the API answers by ignoring the filter rather than by erroring, which
    looks exactly like a data problem."""
    if not params:
        return API_BASE + path
    clean = {k: v for k, v in params.items() if v is not None}
    q = urllib.parse.urlencode(clean, doseq=True, safe="[]")
    return f"{API_BASE}{path}?{q}" if q else API_BASE + path


# --------------------------------------------------------------------------
# Cassettes
# --------------------------------------------------------------------------

def _slug(params):
    if not params:
        return "none"
    parts = []
    for k in sorted(params):
        v = params[k]
        if isinstance(v, (list, tuple)):
            v = "-".join(str(x) for x in v)
        parts.append(f"{k}-{v}")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", "__".join(parts))
    return s[:80].strip("-") or "none"


def cassette_path(path, params=None):
    """cache/bdl/<endpoint>/<params>__<hash>.json

    Readable on purpose -- these get opened by hand while working out what an
    endpoint actually returns. The hash disambiguates the truncated slug."""
    url = build_url(path, params)
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    endpoint = path.strip("/").replace("/", "-") or "root"
    return os.path.join(CASSETTE_DIR, endpoint, f"{_slug(params)}__{digest}.json")


def _log_index(row):
    os.makedirs(CASSETTE_DIR, exist_ok=True)
    with open(INDEX_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")


def read_index():
    if not os.path.exists(INDEX_PATH):
        return []
    rows = []
    with open(INDEX_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

_SENT = collections.deque()
_LAST = [0.0]


def _throttle():
    limit = rate_limit()
    now = time.time()
    while _SENT and now - _SENT[0] > 60:
        _SENT.popleft()
    if len(_SENT) >= limit:
        wait = 60 - (now - _SENT[0]) + 0.05
        if wait > 0:
            print(f"  rate limit ({limit}/min): sleeping {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)
        now = time.time()
        while _SENT and now - _SENT[0] > 60:
            _SENT.popleft()
    gap = time.time() - _LAST[0]
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _SENT.append(time.time())
    _LAST[0] = time.time()


def _parse_headers(stderr_text):
    """The x-ratelimit-* header names are undocumented, so capture whatever
    arrives rather than looking for specific ones."""
    out = {}
    for line in (stderr_text or "").splitlines():
        if ":" not in line or line.startswith("HTTP/"):
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        if k:
            out[k] = v.strip()
    return out


def _curl(url, key, timeout=30):
    cmd = [
        "curl", "-s", "--max-time", str(timeout),
        "-w", "\n%{http_code} %{time_total}",
        "-D", "/dev/stderr",
        "-H", f"Authorization: {key}",
        "-H", "Accept: application/json",
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ServerError(f"curl failed ({r.returncode}) for {url}: {r.stderr.strip()[:200]}")
    body, _, tail = r.stdout.rpartition("\n")
    bits = tail.split()
    status = bits[0] if bits else "000"
    elapsed_ms = int(float(bits[1]) * 1000) if len(bits) > 1 else None
    return body, status, elapsed_ms, _parse_headers(r.stderr)


def _raise_for_status(status, path, body, headers):
    if status == "401":
        tier = min_tier(path)
        if tier == "free":
            raise AuthError(
                f"401 Unauthorized on {path}, which is a free-tier endpoint -- so this is "
                f"the key, not the plan.\n\n{SETUP_HINT}")
        raise TierError(
            f"401 on {path}, which needs the {tier.upper()} tier.\n"
            f"Either the subscription lapsed (the 48-hour trial expires) or the key is "
            f"on a lower plan.\nRe-run with --replay to work from recorded cassettes instead.")
    if status == "429":
        raise RateLimited(f"429 rate limited on {path}. retry-after="
                          f"{headers.get('retry-after', 'unset')}")
    if status in ("500", "502", "503", "504"):
        raise ServerError(f"HTTP {status} from {path}")
    if status != "200":
        raise BdlError(f"HTTP {status} from {path}: {body[:200]}")


def _fetch_live(path, params, key, timeout):
    """Retry ladder. 429 honours Retry-After when it is sent; 5xx backs off
    blind. Any other 4xx is a bug in the request and is not retried."""
    url = build_url(path, params)
    delays_429 = [1, 2, 4, 8, 16]
    delays_5xx = [1, 2, 4]
    attempt_429 = attempt_5xx = 0
    while True:
        _throttle()
        body, status, elapsed_ms, headers = _curl(url, key, timeout)
        if status == "200":
            stripped = body.lstrip()
            if stripped[:1] == "<":
                # A gateway error page served with a 200. Treat as retryable 5xx.
                status = "502"
            else:
                try:
                    return json.loads(body), elapsed_ms, headers, url
                except ValueError:
                    raise BdlError(f"non-JSON 200 from {path}: {body[:200]}")
        if status == "429" and attempt_429 < len(delays_429):
            wait = delays_429[attempt_429]
            try:
                wait = max(wait, int(headers.get("retry-after", 0)))
            except ValueError:
                pass
            print(f"  429 on {path}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            attempt_429 += 1
            continue
        if status in ("500", "502", "503", "504") and attempt_5xx < len(delays_5xx):
            wait = delays_5xx[attempt_5xx]
            print(f"  HTTP {status} on {path}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            attempt_5xx += 1
            continue
        _raise_for_status(status, path, body, headers)


def bdl_get(path, params=None, mode="auto", timeout=30, quiet=False):
    """-> (payload, meta). meta = {status, elapsed_ms, replayed, cassette, url}."""
    if mode not in ("auto", "record", "replay", "live"):
        raise ValueError(f"unknown mode {mode!r}")
    cpath = cassette_path(path, params)
    url = build_url(path, params)

    if mode in ("auto", "replay") and os.path.exists(cpath):
        with open(cpath) as f:
            rec = json.load(f)
        meta = {"status": rec["response"]["status"], "elapsed_ms": rec.get("elapsed_ms"),
                "replayed": True, "cassette": cpath, "url": url}
        if not quiet:
            print(f"  replay  {path} ({os.path.basename(cpath)})")
        return rec["response"]["body"], meta

    if mode == "replay":
        raise CassetteMiss(
            f"No cassette for {path} {params or ''}\n"
            f"  expected: {os.path.relpath(cpath, ROOT)}\n"
            f"  record it with the same command minus --replay (needs a live key).")

    payload, elapsed_ms, headers, url = _fetch_live(path, params, api_key(), timeout)
    if not quiet:
        n = len(payload.get("data", [])) if isinstance(payload, dict) else "?"
        print(f"  live    {path}  {elapsed_ms}ms  rows={n}")

    if mode in ("auto", "record"):
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        with open(cpath, "w") as f:
            json.dump({
                "request": {"path": path, "params": params or {}, "url": url},
                "response": {"status": "200", "headers": headers, "body": payload},
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "recorded_ts": int(time.time()),
                "elapsed_ms": elapsed_ms,
                "bytes": len(json.dumps(payload)),
            }, f)

    _log_index({
        "path": path, "params": params or {}, "status": "200",
        "elapsed_ms": elapsed_ms, "bytes": len(json.dumps(payload)),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cassette": os.path.relpath(cpath, ROOT), "replayed": False,
    })
    return payload, {"status": "200", "elapsed_ms": elapsed_ms, "replayed": False,
                     "cassette": cpath, "url": url}


def paginate(path, params=None, per_page=100, max_pages=200, mode="auto", quiet=False):
    """Yield every row across the cursor pages.

    The guard matters more than it looks: a next_cursor equal to the one just
    used is an infinite loop, and on a metered key an infinite loop is an
    expensive one."""
    params = dict(params or {})
    params["per_page"] = per_page
    cursor = None
    seen_cursors = set()
    pages = 0
    while True:
        page_params = dict(params)
        if cursor is not None:
            page_params["cursor"] = cursor
        payload, _ = bdl_get(path, page_params, mode=mode, quiet=quiet)
        for row in payload.get("data") or []:
            yield row
        pages += 1
        nxt = (payload.get("meta") or {}).get("next_cursor")
        if not nxt:
            return
        if nxt in seen_cursors or nxt == cursor:
            raise BdlError(f"cursor did not advance on {path} (cursor={nxt!r})")
        if pages >= max_pages:
            raise BdlError(f"{path}: hit max_pages={max_pages}; refusing to keep paging")
        seen_cursors.add(nxt)
        cursor = nxt


# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

def teams(mode="auto"):
    """-> list of the 32 team objects. Static; the cassette is written once."""
    payload, _ = bdl_get("/teams", mode=mode)
    rows = payload.get("data") or []
    if len(rows) != 32:
        raise BdlError(f"/teams returned {len(rows)} teams, expected 32")
    return rows


def team_index(mode="auto"):
    """-> (by_abbr, by_id).

    The abbreviations are used verbatim: they were compared against the 32 in
    data/nfl_schedule_2026.json and match exactly, including WSH (not WAS), JAX
    (not JAC) and LAR. scripts/primary/oven-config.js maps WSH->WAS downstream
    and keeps working untouched."""
    rows = teams(mode=mode)
    return ({t["abbreviation"]: t for t in rows}, {t["id"]: t for t in rows})


def latency_summary(rows=None, paths=None):
    """-> {path: {n, p50, p90, max}} in ms, over live (not replayed) requests."""
    rows = read_index() if rows is None else rows
    buckets = collections.defaultdict(list)
    for r in rows:
        if r.get("replayed") or r.get("elapsed_ms") is None:
            continue
        if paths and r.get("path") not in paths:
            continue
        buckets[r["path"]].append(r["elapsed_ms"])
    out = {}
    for path, vals in sorted(buckets.items()):
        vals.sort()
        out[path] = {"n": len(vals), "p50": percentile(vals, 50),
                     "p90": percentile(vals, 90), "max": vals[-1]}
    return out


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if lo == hi:
        return sorted_vals[lo]
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo), 1)


def add_mode_args(ap):
    """The flag set every caller in this family shares."""
    ap.add_argument("--mode", choices=["auto", "record", "replay", "live"], default="auto",
                    help="auto: replay a cassette if one exists, else fetch and record")
    ap.add_argument("--replay", action="store_true",
                    help="shorthand for --mode replay: never touch the network")
    ap.add_argument("--record", action="store_true",
                    help="shorthand for --mode record: always fetch live and overwrite")


def resolve_mode(args):
    if getattr(args, "replay", False) and getattr(args, "record", False):
        raise SystemExit("--replay and --record are mutually exclusive")
    if getattr(args, "replay", False):
        return "replay"
    if getattr(args, "record", False):
        return "record"
    return args.mode
