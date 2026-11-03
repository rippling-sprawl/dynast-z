"""
/api/action-ledger — every tracked Action Network bet, for admins only.

GET  -> {"rows": [...], "fetched_at": "...", "built_at": "...",
         "chances": {"<ticket id>": 35.5, ...}}
        Auth: X-User-Id, must be an active admin. The row shape is documented
        in scripts/build_action_ledger.py, which is what writes it.
PUT  -> {"data": {"rows": [...], ...}, "etag": "..."}
        Replaces the ledger. Same auth.
POST -> {"id": <ticket id>, "chance": 0-100 | null}
        Sets (or, with null, clears) an admin's hand-set win chance for one
        ticket. Same auth. A ticket with no entry falls back, on the page, to
        the chance its odds imply.

Unlike the Action book (api/action.py), which is unlisted-public, this one is
gated: the book is a board of open futures, the ledger is the whole betting
history with stakes and results on every row.

Storage: Supabase `action_pages`, slug `ledger` -- the same table as the book,
so no schema change, but not part of the book. The hand-set chances are their
own slug, `ledger-chances`, so re-seeding the ledger never wipes them.
api/action-ingest.py excludes both slugs from its manifest, which is what keeps
a book push (which deletes any slug it was not sent) from removing them, and
api/action.py only serves its own allowlisted slugs, so neither is public.

Size: ~11k rows, ~3.8 MB of JSON and ~0.5 MB gzipped. _http.send gzips it.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _http import send_json  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

SLUG = "ledger"
CHANCES_SLUG = "ledger-chances"


def supabase_request(path, method="GET", body=None, headers=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def resolve_admin(user_id):
    """None when the caller is an active admin, else (status, body)."""
    if not user_id:
        return 401, {"error": "Not authenticated"}
    try:
        rows = supabase_request(
            f"users?id=eq.{urllib.parse.quote(user_id)}&select=role,status")
    except urllib.error.HTTPError as e:
        # A malformed id is a 400 from PostgREST (not a uuid); that is a
        # caller who is not an admin, not a server fault.
        if e.code == 400:
            return 403, {"error": "Admins only"}
        raise
    user = rows[0] if rows else None
    if not user or user.get("status") is not True or user.get("role") != "admin":
        return 403, {"error": "Admins only"}
    return None


def load():
    rows = supabase_request(
        f"action_pages?slug=in.({SLUG},{CHANCES_SLUG})&select=slug,data") or []
    by_slug = {r["slug"]: r["data"] for r in rows}
    data = by_slug.get(SLUG)
    if data is None:
        return None
    return {**data, "chances": (by_slug.get(CHANCES_SLUG) or {}).get("chances", {})}


def load_chances():
    rows = supabase_request(f"action_pages?slug=eq.{CHANCES_SLUG}&select=data")
    return ((rows[0]["data"] if rows else None) or {}).get("chances", {})


def set_chance(body):
    """(result, error). One ticket's chance, as a percent; null clears it.

    Read-modify-write of one small JSON object: fine for a page only admins
    edit, one cell at a time."""
    if not isinstance(body, dict):
        return None, "Body must be an object"
    tid, chance = body.get("id"), body.get("chance")
    if isinstance(tid, bool) or not isinstance(tid, int):
        return None, "id must be a ticket id"
    if chance is not None:
        if isinstance(chance, bool) or not isinstance(chance, (int, float)) or not 0 <= chance <= 100:
            return None, "chance must be a number from 0 to 100, or null"
        chance = round(float(chance), 1)
    chances = load_chances()
    if chance is None:
        chances.pop(str(tid), None)
    else:
        chances[str(tid)] = chance
    supabase_request(
        "action_pages?on_conflict=slug", method="POST",
        body=[{"slug": CHANCES_SLUG, "data": {"chances": chances},
               "etag": str(len(chances)), "updated_at": "now()"}],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
    return {"id": tid, "chance": chance}, None


def save(body):
    """(result, error). Validates just enough to keep a bad push out."""
    if not isinstance(body, dict):
        return None, "Body must be an object"
    data, etag = body.get("data"), body.get("etag")
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return None, "Body needs data.rows"
    if not isinstance(etag, str) or not etag:
        return None, "Body needs an etag"
    supabase_request(
        "action_pages?on_conflict=slug", method="POST",
        body=[{"slug": SLUG, "data": data, "etag": etag, "updated_at": "now()"}],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
    return {"written": len(data["rows"]), "etag": etag}, None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            err = resolve_admin(self.headers.get("X-User-Id"))
            if err:
                self._json(*err)
                return
            data = load()
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        if data is None:
            self._json(404, {"error": "No ledger yet -- run scripts/build_action_ledger.py --push"})
            return
        self._json(200, data)

    def do_POST(self):
        self._write(set_chance)

    def do_PUT(self):
        self._write(save)

    def _write(self, fn):
        try:
            err = resolve_admin(self.headers.get("X-User-Id"))
            if err:
                self._json(*err)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError) as e:
            self._json(400, {"error": f"Body is not JSON: {e}"})
            return
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        try:
            result, error = fn(body)
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        if error:
            self._json(400, {"error": error})
            return
        self._json(200, result)

    def _json(self, status, data):
        send_json(self, status, data, {"Cache-Control": "no-store"})
