"""
/api/bun-notes — the note store behind /football/bakers-buns.

GET    : every note, oldest first. `?team=CHI` narrows to one team, `?team=` to
         the league-wide ones. Public, because the notes are published reading
         for everyone; the page renders them for signed-out visitors too.
PUT    : create or update. Body is one note object or {"notes": [...]} so the
         modal's multi-bullet save is a single request. Admin only.
DELETE : ?id=n_x, one note. Admin only.

Storage: a Supabase table `bun_notes(id text pk, team, week, data jsonb, ...)`.
See scripts/sql/bun_notes.sql for the schema and scripts/seed_bun_notes.py for
the one-time import of the notes that were seeded from the Google Doc.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# The one combined picker: a general note, the preseason, the 18 regular-season
# weeks, then the four playoff rounds. Anything else is rejected rather than
# stored, so the page never has to render a week label it has no name for.
WEEKS = {"all", "pre", "wc", "div", "conf", "sb"} | {str(n) for n in range(1, 19)}
KINDS = {"note", "schedule"}
MAX_TEXT = 2000
MAX_BATCH = 50


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


def fetch_user(user_id):
    rows = supabase_request(
        f"users?id=eq.{urllib.parse.quote(user_id)}&select=role,status")
    return rows[0] if rows else None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_source(src):
    """Keep only the two fields the card renders, and only for a real x.com post.

    The client parses the handle out of the URL and we re-parse it here rather
    than trusting it, so a stored source can never render a label that points
    somewhere other than the link.
    """
    if not isinstance(src, dict):
        return None
    url = (src.get("url") or "").strip()
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in ("x.com", "twitter.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    # /<handle>/status/<id>
    if len(parts) < 3 or parts[1] not in ("status", "statuses") or not parts[2].isdigit():
        return None
    return {"url": url, "handle": parts[0]}


def normalize(note, author_id):
    """Validate one note off the wire. Returns (row, error_message)."""
    if not isinstance(note, dict):
        return None, "note must be an object"

    note_id = (note.get("id") or "").strip()
    if not note_id:
        return None, "note id is required"

    text = (note.get("text") or "").strip()
    if not text:
        return None, "note text is required"
    if len(text) > MAX_TEXT:
        return None, f"note text is longer than {MAX_TEXT} characters"

    week = str(note.get("week") or "all")
    if week not in WEEKS:
        return None, f"unknown week {week!r}"

    kind = note.get("kind") or "note"
    if kind not in KINDS:
        return None, f"unknown kind {kind!r}"

    team = (note.get("team") or "").strip().upper()

    data = {
        "id": note_id,
        "team": team,
        "week": week,
        "kind": kind,
        "text": text,
        # The author and the timestamps are stamped here, not accepted from the
        # client. createdAt is only taken from the body when the client is
        # editing a note it already has, so an edit keeps its original date.
        "authorId": author_id,
        "createdAt": note.get("createdAt") or now_iso(),
        "updatedAt": now_iso(),
    }
    source = clean_source(note.get("source"))
    if source:
        data["source"] = source
    if isinstance(note.get("order"), int):
        data["order"] = note["order"]
    if note.get("seeded"):
        data["seeded"] = True

    return {
        "id": note_id,
        "team": team,
        "week": week,
        "data": data,
        "updated_at": "now()",
    }, None


class handler(BaseHTTPRequestHandler):
    def _admin(self):
        """Returns (user_id, error) where error is None or a (status, body) tuple."""
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            return None, (401, {"error": "Not authenticated"})
        user = fetch_user(user_id)
        if not user or user.get("status") is not True or user.get("role") != "admin":
            return None, (403, {"error": "Not authorized to edit notes"})
        return user_id, None

    def do_GET(self):
        params = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query, keep_blank_values=True)
        query = "bun_notes?select=data&order=created_at"
        if "team" in params:
            team = (params["team"][0] or "").upper()
            query += "&team=eq." + urllib.parse.quote(team)
        try:
            rows = supabase_request(query)
            self._json(200, [r["data"] for r in (rows or [])])
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        user_id, err = self._admin()
        if err:
            self._json(*err)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._json(400, {"error": "Body must be JSON"})
            return

        notes = body.get("notes") if isinstance(body, dict) and "notes" in body else [body]
        if not isinstance(notes, list) or not notes:
            self._json(400, {"error": "No notes in the request"})
            return
        if len(notes) > MAX_BATCH:
            self._json(400, {"error": f"At most {MAX_BATCH} notes per request"})
            return

        rows = []
        for note in notes:
            row, error = normalize(note, user_id)
            if error:
                self._json(400, {"error": error})
                return
            rows.append(row)

        try:
            # Upsert on the primary key. created_at is left out of the payload
            # so an edit keeps the row's original insert time.
            supabase_request(
                "bun_notes?on_conflict=id",
                method="POST",
                body=rows,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            self._json(200, {"ok": True, "notes": [r["data"] for r in rows]})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_DELETE(self):
        _, err = self._admin()
        if err:
            self._json(*err)
            return
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        note_id = params.get("id", [None])[0]
        if not note_id:
            self._json(400, {"error": "id parameter is required"})
            return
        try:
            supabase_request(
                "bun_notes?id=eq." + urllib.parse.quote(note_id),
                method="DELETE",
                headers={"Prefer": "return=minimal"},
            )
            self._json(200, {"ok": True})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
