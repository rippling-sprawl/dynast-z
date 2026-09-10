"""
/api/game-odds — one NFL game's odds, props, box score and play log.

GET  /api/game-odds              -> {"games": {id: {...summary...}}}
GET  /api/game-odds?game=<id>    -> the full bundle for that game

Both public: this is the data /football/schedule/game/<id> renders, and that
page is public. The page route carries the id as a path segment; this endpoint
keeps it as a query parameter, because it is an API and not a page.

WHY THIS IS AN ENDPOINT AND NOT A FILE IN /data

A bundle is ~900 KB, nearly all of it player props -- 34 players x 25 markets x
6 sportsbooks, both sides of every over/under. Committing one per game would add
~15 MB a week during the season to a repo, permanently, for numbers that go
stale in minutes and are refetched anyway. So the bundles live in Supabase
`game_odds` and move on a push with no deploy, exactly as the Action Network
book does. Schema in scripts/sql/game_odds.sql.

CACHING

`etag` is the sha256 of the bundle's canonical JSON, computed by the writer, so
an unchanged game is cheap to recognise. Recognising it is done twice over,
because neither HTTP mechanism survives this deployment:

  ?known=<etag>   The one that actually works. The page remembers the etag it is
                  holding and sends it back; an unchanged game answers with
                  ~60 bytes instead of a megabyte. This is plain response data,
                  so nothing between here and the browser can strip it.

  If-None-Match   Kept for anything that does get a validator through, but the
                  browser is not one of them: every /api/* response comes back
                  re-encoded and stripped of its ETag, which is also why every
                  route under /api is `no-store` in vercel.json rather than
                  carrying a max-age it could not revalidate against.

The Supabase read is split for the same reason it is split in api/action.py.
`select=etag` is a few hundred bytes; `select=data` is the whole megabyte, and
884 KB of that is player props. Asking for both at once -- which is what this
did -- paid the megabyte on every request even when the answer was "unchanged",
and a game page polls itself for as long as it is open. Read the etag, and read
the data only when it is one this instance has not already rendered.

The listing is the exception: it carries no odds, only which games exist, so it
is cheap to rebuild and does not need a validator at all.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# balldontlie game ids are integers. Validating before the value reaches a
# PostgREST filter is what keeps an arbitrary string out of the query, the same
# guard SLUG_RE gives api/action.py.
GAME_ID_RE = re.compile(r"^[0-9]{1,12}$")

SUMMARY_COLUMNS = ("game_id,label,title,away,home,kickoff,season,week,phase,"
                   "has,etag,updated_at")

# Warm-instance memo, keyed by game id -> (etag, bundle-json-bytes). A Vercel
# instance handling several requests for the same game skips both the round trip
# and the re-serialize; a cold one just misses.
_MEMO = {}


# WHAT THE WIRE DOES NOT CARRY
#
# Two sections are stored but never sent to a page, because no page reads them:
#
#   player_props.opening   ~610 KB, and propRows() in views/football/game-odds.html
#                          is explicitly "current only" -- an opening prop answers
#                          how the market moved, which that board deliberately does
#                          not ask. Shipping it cost 60% of every poll for a
#                          section that never reached a pixel.
#   designations           ~103 KB, and the page reads `injuries` only. There is no
#                          `b.designations` access anywhere in it.
#
# Both stay in Supabase. That is the whole point of the split: balldontlie keeps
# no prop history, so an opening line not captured before kickoff cannot be
# bought back at any price, and the archive is the only copy there will ever be.
# What changes is that a live game page polling every 30 seconds stops paying for
# them 120 times an hour.
#
# `?full=1` returns the stored bundle untouched, for archival reads and for
# checking what was actually captured.
#
# odds.opening is NOT trimmed: the page renders it (oddsTable on the opening
# rows), and it is ~10 rows rather than thousands.
TRIMMED_SECTIONS = ("player_props.opening", "designations")


def trim_for_wire(bundle):
    """-> the bundle as a page should receive it. Never mutates the argument:
    the memo holds one object per warm instance and every request shares it."""
    out = dict(bundle)
    pp = out.get("player_props")
    if isinstance(pp, dict) and pp.get("opening"):
        out["player_props"] = dict(pp, opening=[])
    if out.get("designations"):
        out["designations"] = {}
    # Named rather than silent: a consumer that finds an empty `opening` should
    # be able to tell "trimmed in transit" from "never captured".
    out["trimmed"] = list(TRIMMED_SECTIONS)
    return out


def supabase_request(path):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # PostgREST puts the useful part in the body -- a missing table is a
        # bare 404 otherwise, which reads like a wrong URL rather than a table
        # that was never created.
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail:
            raise RuntimeError(
                "the game_odds table does not exist -- run "
                "scripts/sql/game_odds.sql in the Supabase SQL editor") from None
        raise RuntimeError(f"supabase {e.code}: {detail}") from None
    return json.loads(raw) if raw else None


def load_index():
    """-> {"games": {"<id>": {...}}, "updated_at": ...}

    Shaped as a map keyed by id because that is what the page reads, and because
    it makes "do we have this game?" a lookup rather than a scan."""
    rows = supabase_request(
        f"game_odds?select={SUMMARY_COLUMNS}&order=kickoff.desc") or []
    games = {}
    newest = None
    for r in rows:
        games[str(r["game_id"])] = {
            "id": r["game_id"], "label": r.get("label"), "title": r.get("title"),
            "away": r.get("away"), "home": r.get("home"),
            "kickoff": r.get("kickoff"), "season": r.get("season"),
            "week": r.get("week"), "phase": r.get("phase"),
            "has": r.get("has") or {}, "updated_at": r.get("updated_at"),
        }
        if r.get("updated_at") and (newest is None or r["updated_at"] > newest):
            newest = r["updated_at"]
    return {"games": games, "updated_at": newest}


def load_etag(game_id):
    """-> the stored bundle's etag, or None when nothing is stored for that game.

    Deliberately its own round trip. This is the request every poll makes and
    most polls make only this one, so it must not carry the data column."""
    rows = supabase_request(
        f"game_odds?game_id=eq.{urllib.parse.quote(game_id)}&select=etag")
    return rows[0].get("etag") if rows else None


def load_bundle(game_id, etag):
    """-> the bundle for a game whose etag has already been read, or None if the
    row went away between the two reads.

    The memo is keyed on that etag, so a warm instance serving the same game
    twice reads nothing at all the second time."""
    cached = _MEMO.get(game_id)
    if cached and cached[0] == etag:
        return cached[1]
    rows = supabase_request(
        f"game_odds?game_id=eq.{urllib.parse.quote(game_id)}&select=data")
    if not rows:
        return None
    bundle = rows[0].get("data")
    _MEMO[game_id] = (etag, bundle)
    return bundle


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        game_id = (params.get("game") or [""])[0].strip()

        if not game_id:
            try:
                self._json(200, load_index())
            except Exception as e:                       # noqa: BLE001
                self._json(500, {"error": str(e)})
            return

        if not GAME_ID_RE.match(game_id):
            self._json(400, {"error": "game must be a numeric balldontlie game id"})
            return

        # Compared, never interpolated into a query, so an odd value here is
        # simply an etag that matches nothing. Bounded anyway: an etag is a
        # sha256 and a caller sending more than that is not one of ours.
        known = (params.get("known") or [""])[0].strip()[:64]
        full = (params.get("full") or [""])[0].strip() in ("1", "true", "yes")

        try:
            etag = load_etag(game_id)
        except Exception as e:                           # noqa: BLE001
            self._json(500, {"error": str(e)})
            return

        if etag is None:
            # 404 rather than an empty bundle: the page distinguishes "no
            # capture yet" from "captured, but the endpoints were tier-gated",
            # and the two look identical if this returns an empty object.
            self._json(404, {"error": f"no bundle stored for game {game_id}"})
            return

        quoted = f'"{etag}"'

        # The whole point of the split read: answer without ever touching the
        # data column. `known` is the path the page takes; If-None-Match is the
        # same answer for anything whose validator survived the hop.
        if known == etag:
            self._json(200, {"unchanged": True, "etag": etag})
            return

        if self.headers.get("If-None-Match") == quoted:
            self.send_response(304)
            self.send_header("ETag", quoted)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return

        try:
            bundle = load_bundle(game_id, etag)
        except Exception as e:                           # noqa: BLE001
            self._json(500, {"error": str(e)})
            return

        if bundle is None:
            # The row was deleted between the two reads. Rare, and the page
            # already knows what to do with a 404.
            self._json(404, {"error": f"no bundle stored for game {game_id}"})
            return

        # Shallow copy: the page needs the etag to send back next time, and the
        # memoised bundle should stay exactly as it was stored. The etag is the
        # stored bundle's hash either way -- it identifies the version, not the
        # projection of it that went over the wire, so `?known=` still works
        # unchanged for a trimmed and a full reader alike.
        payload = bundle if full else trim_for_wire(bundle)
        self._json(200, dict(payload, etag=etag), etag=quoted)

    def _json(self, status, data, etag=None):
        # No `cache` argument any more: vercel.json puts every /api/* route on
        # no-store, and a header set here would only be overwritten. Freshness
        # is `?known=`, not HTTP.
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
