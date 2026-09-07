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

Same reasoning as api/action.py, and for the same reason: `etag` is the sha256 of
the bundle's canonical JSON, computed by the writer, so an unchanged game costs a
304 rather than 900 KB. `max-age=0, must-revalidate` with no `s-maxage` is
deliberate -- there is no way to purge Vercel's edge cache from inside a
function, and an s-maxage would keep serving a stale line after a push had
replaced it. Pregame odds move; that is the whole point of capturing them.

The listing is the exception: it carries no odds, only which games exist, so it
is cheap to rebuild and gets a short s-maxage instead of a validator.
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


def load_bundle(game_id):
    """-> (etag, bundle) or (None, None) when nothing is stored for that game."""
    cached = _MEMO.get(game_id)
    rows = supabase_request(
        f"game_odds?game_id=eq.{urllib.parse.quote(game_id)}&select=data,etag")
    if not rows:
        return None, None
    etag = rows[0].get("etag")
    if cached and cached[0] == etag:
        return cached
    bundle = rows[0].get("data")
    _MEMO[game_id] = (etag, bundle)
    return etag, bundle


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        game_id = (params.get("game") or [""])[0].strip()

        if not game_id:
            try:
                self._json(200, load_index(),
                           cache="public, s-maxage=120, stale-while-revalidate=600")
            except Exception as e:                       # noqa: BLE001
                self._json(500, {"error": str(e)})
            return

        if not GAME_ID_RE.match(game_id):
            self._json(400, {"error": "game must be a numeric balldontlie game id"})
            return

        try:
            etag, bundle = load_bundle(game_id)
        except Exception as e:                           # noqa: BLE001
            self._json(500, {"error": str(e)})
            return

        if bundle is None:
            # 404 rather than an empty bundle: the page distinguishes "no
            # capture yet" from "captured, but the endpoints were tier-gated",
            # and the two look identical if this returns an empty object.
            self._json(404, {"error": f"no bundle stored for game {game_id}"})
            return

        quoted = f'"{etag}"'
        if self.headers.get("If-None-Match") == quoted:
            self.send_response(304)
            self.send_header("ETag", quoted)
            self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return

        self._json(200, bundle, etag=quoted,
                   cache="public, max-age=0, must-revalidate")

    def _json(self, status, data, etag=None, cache="no-store"):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
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
