"""
/api/power-rankings — the card deck behind /power-rankings.

GET : {"model", "version", "updatedAt", "updatedBy"} for the deck, or 404
      {"seed": true} while the table has no row yet; the page then loads
      data/power_rankings_seed.json and saves it as version 1.
PUT : {"model", "version"}, where `version` is the one the edit was made from
      (0 to create the row). Written only if the stored row is still at that
      version, else 409 with the current version, so a stale tab or script can
      never overwrite newer cards. 200 {"version", "updatedAt"} on success.

Both need an active admin (X-User-Id), as the page itself does.

Storage: Supabase `power_rankings(id pk, version, data jsonb, ...)` plus an
append-only `power_rankings_history`. See scripts/sql/power_rankings.sql.
The table is the copy of record; nothing in a deploy writes to it.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
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

DECK_ID = "jhbc"
MAX_BYTES = 512 * 1024
MAX_CARDS = 64


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


# ---- shared with server.py --------------------------------------------------
# These live at module level so server.py can load this file and serve the
# same rules locally — see power_rankings_api() there. Each returns
# (status, body).


def resolve_admin(user_id):
    """-> (username, error): error None or (status, body)."""
    if not user_id:
        return None, (401, {"error": "Not authenticated"})
    rows = supabase_request(
        f"users?id=eq.{urllib.parse.quote(user_id)}&select=username,role,status")
    user = rows[0] if rows else None
    if not user or user.get("status") is not True:
        return None, (403, {"error": "Account is inactive"})
    if user.get("role") != "admin":
        return None, (403, {"error": "Only an admin can open the power rankings"})
    return user["username"], None


def fetch_row():
    rows = supabase_request(
        f"power_rankings?id=eq.{DECK_ID}&select=version,data,updated_by,updated_at")
    return rows[0] if rows else None


def validate(model):
    """None when `model` is a deck the page can render, else the message."""
    if not isinstance(model, dict):
        return "model must be an object"
    cards, tiers = model.get("cards"), model.get("tiers")
    if not isinstance(cards, list) or not isinstance(tiers, list) or not tiers:
        return "model needs a cards list and a non-empty tiers list"
    if len(cards) > MAX_CARDS:
        return f"at most {MAX_CARDS} cards"
    ids = set()
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not card["id"]:
            return "every card needs a string id"
        if card["id"] in ids:
            return f"duplicate card id {card['id']!r}"
        ids.add(card["id"])
    if len(json.dumps(model)) > MAX_BYTES:
        return "model is too large"
    return None


def read_deck(user_id):
    _, err = resolve_admin(user_id)
    if err:
        return err
    row = fetch_row()
    if not row:
        return 404, {"seed": True}
    return 200, {
        "model": row["data"],
        "version": row["version"],
        "updatedAt": row["updated_at"],
        "updatedBy": row.get("updated_by"),
    }


def write_deck(user_id, body):
    username, err = resolve_admin(user_id)
    if err:
        return err
    if not isinstance(body, dict):
        return 400, {"error": "Body must be an object"}
    model, base = body.get("model"), body.get("version")
    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        return 400, {"error": "version (the one this edit started from) is required"}
    error = validate(model)
    if error:
        return 400, {"error": error}

    now = datetime.now(timezone.utc).isoformat()
    row = {"version": base + 1, "data": model, "updated_by": username, "updated_at": now}
    if base == 0:
        # Create. ignore-duplicates turns "someone created it first" into an
        # empty answer rather than an overwrite.
        written = supabase_request(
            "power_rankings?on_conflict=id",
            method="POST",
            body={"id": DECK_ID, **row},
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
        )
    else:
        # The version filter is the lock: a row that has moved on matches
        # nothing, so nothing is written.
        written = supabase_request(
            f"power_rankings?id=eq.{DECK_ID}&version=eq.{base}",
            method="PATCH",
            body=row,
            headers={"Prefer": "return=representation"},
        )
    if not written:
        current = fetch_row()
        return 409, {
            "error": "The cards were saved from somewhere else since this copy was loaded",
            "version": current["version"] if current else 0,
            "updatedBy": current.get("updated_by") if current else None,
        }

    try:
        supabase_request(
            "power_rankings_history",
            method="POST",
            body={"id": DECK_ID, **row},
            headers={"Prefer": "return=minimal"},
        )
    except urllib.error.URLError:
        pass  # The save itself landed; history is a convenience.
    return 200, {"version": row["version"], "updatedAt": now}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self._json(*read_deck(self.headers.get("X-User-Id")))
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._json(400, {"error": "Body must be JSON"})
            return
        try:
            self._json(*write_deck(self.headers.get("X-User-Id"), body))
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        send_json(self, status, data, {
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, X-User-Id",
        })

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
