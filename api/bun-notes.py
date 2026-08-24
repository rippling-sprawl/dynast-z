"""
/api/bun-notes — the note store behind /football/bakers-buns.

GET    : every note, oldest first. `?team=CHI` narrows to one team, `?team=` to
         the league-wide ones. Public, because the notes are published reading
         for everyone; the page renders them for signed-out visitors too.
PUT    : create or update. Body is one note object or {"notes": [...]} so the
         modal's multi-bullet save is a single request. Any active account may
         write; an existing note needs its author or an admin.
DELETE : ?id=n_x, one note. Its author or an admin.

Storage: a Supabase table `bun_notes(id text pk, team, week, data jsonb, ...)`.
See scripts/sql/bun_notes.sql for the schema and scripts/seed_bun_notes.py for
the one-time import of the notes that were seeded from the Google Doc.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import re
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

# Ids are minted by the client ('n_...') or by the seeder ('seed_CHI_note_0'),
# so they are only ever this alphabet. Pinning that down is also what makes them
# safe to interpolate into the `id=in.(...)` filter the ownership pre-read uses.
NOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


# ---- who may write what -----------------------------------------------------
# The notes are a shared, published store: anyone signed in may file one, and
# owns what they filed. An admin owns everything. These three live at module
# level rather than on the handler because server.py loads this file to mirror
# the rule locally — see bun_notes_api() there.


def resolve_actor(user_id):
    """Returns (user_id, is_admin, error), error being None or (status, body).

    Any active account may write notes; the admin flag decides whose notes they
    may touch besides their own.
    """
    if not user_id:
        return None, False, (401, {"error": "Not authenticated"})
    user = fetch_user(user_id)
    if not user or user.get("status") is not True:
        return None, False, (403, {"error": "Account is inactive"})
    return user_id, user.get("role") == "admin", None


def fetch_authors(ids):
    """Map of note id -> authorId, for the ids that already exist.

    One query for the whole batch. A missing key means the note is new; a None
    value means an unowned note — the seeded import filed those with no author
    (see scripts/seed_bun_notes.py), so only an admin can touch them.
    """
    ids = [i for i in ids if i]
    if not ids:
        return {}
    quoted = ",".join('"' + i + '"' for i in ids)
    rows = supabase_request(
        "bun_notes?id=in.(" + urllib.parse.quote(quoted) + ")&select=id,data")
    return {r["id"]: (r.get("data") or {}).get("authorId") for r in (rows or [])}


def may_write(authors, note_id, user_id, is_admin):
    """None when the write is allowed, else the message to 403 with.

    A note whose id is not in `authors` does not exist yet, and creating one is
    always allowed.
    """
    if is_admin or note_id not in authors:
        return None
    if authors[note_id] and authors[note_id] == user_id:
        return None
    return "You can only edit your own notes"


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


def note_id_of(note):
    """Pull the id off a note from the wire. Returns (id, error_message).

    Split out of normalize() because the ids have to be read and checked before
    anything else: they are what the ownership pre-read asks about, and its
    answer is what normalize() then stamps as the author.
    """
    if not isinstance(note, dict):
        return None, "note must be an object"
    note_id = (note.get("id") or "").strip()
    if not note_id:
        return None, "note id is required"
    if not NOTE_ID.match(note_id):
        return None, f"invalid note id {note_id!r}"
    return note_id, None


def normalize(note, author_id):
    """Validate one note off the wire. Returns (row, error_message).

    `author_id` is the note's owner as resolved by the caller: the requester for
    a new note, the original author for an edit.
    """
    note_id, error = note_id_of(note)
    if error:
        return None, error

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
        # client. Both the author and createdAt are carried forward on an edit
        # rather than restamped: an admin correcting someone's note must not
        # take it off them, and an edit keeps its original date.
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
    def _actor(self):
        return resolve_actor(self.headers.get("X-User-Id"))

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
        user_id, is_admin, err = self._actor()
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

        ids = []
        for note in notes:
            note_id, error = note_id_of(note)
            if error:
                self._json(400, {"error": error})
                return
            ids.append(note_id)

        try:
            authors = fetch_authors(ids)
        except Exception as e:
            self._json(500, {"error": str(e)})
            return

        rows = []
        for note, note_id in zip(notes, ids):
            refused = may_write(authors, note_id, user_id, is_admin)
            if refused:
                self._json(403, {"error": refused})
                return
            # An existing note keeps the author it was filed under; a new one is
            # owned by whoever is writing it.
            row, error = normalize(note, authors.get(note_id, user_id))
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
        user_id, is_admin, err = self._actor()
        if err:
            self._json(*err)
            return
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        note_id = (params.get("id", [None])[0] or "").strip()
        if not note_id:
            self._json(400, {"error": "id parameter is required"})
            return
        if not NOTE_ID.match(note_id):
            self._json(400, {"error": f"invalid note id {note_id!r}"})
            return
        try:
            # An id that matches nothing stays a 200 no-op, as it always was.
            refused = may_write(fetch_authors([note_id]), note_id, user_id, is_admin)
        except Exception as e:
            self._json(500, {"error": str(e)})
            return
        if refused:
            self._json(403, {"error": refused})
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
