"""
/api/action-ingest — push the pregenerated Action Network book.

GET  ?manifest=1  -> {"pages": {slug: etag}}. What the live book currently holds,
                     so scripts/build_action.py can report what a push would
                     change before making it. Public: an etag is a hash, and the
                     pages it describes are already unlisted-public.
PUT               -> {"pages": {slug: {"data": {...}, "etag": "..."}}}
                     Replaces the book wholesale: every slug in the body is
                     upserted, and any slug in the table but NOT in the body is
                     deleted. Auth: X-User-Id, must be an active admin.

WHY THE DELETE IS PART OF THE WRITE

The set of pages is data-driven -- a postseason page exists only while a playoff
ticket does -- so a push that no longer mentions a slate has to remove it. The
generated-file version of this was sweep() in render_futures.py, which os.remove'd
any action-*.html it had not just written; without the equivalent here, a slate
that empties would keep serving last month's numbers at a live URL.

WHY IMAGES ARE NOT IN THIS PAYLOAD

They are committed files under assets/action/, content-addressed by the sha in
the filename, served straight off the CDN as immutable. So artwork moves on a
deploy and data moves on a push, and this endpoint only ever carries the half
that changes daily. The cost of that split is the one gap worth knowing about: a
brand-new headshot pushed here before its PNG is committed renders as the
placeholder until the next deploy. scripts/build_action.py prints the list.

Storage: Supabase `action_pages(slug text pk, data jsonb, etag text, updated_at)`.
Schema in scripts/sql/action_pages.sql.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

SLUG_RE = re.compile(r"^(?:index|futures|preseason|postseason|other"
                     r"|week-(?:[1-9]|1[0-8]))$")

MAX_PAGES = 32


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


def manifest():
    rows = supabase_request("action_pages?select=slug,etag") or []
    return {r["slug"]: r["etag"] for r in rows}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self._json(200, {"pages": manifest()})
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            self._json(401, {"error": "Not authenticated"})
            return
        try:
            user = fetch_user(user_id)
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        if not user or user.get("status") is not True or user.get("role") != "admin":
            self._json(403, {"error": "Not authorized to update the book"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError) as e:
            self._json(400, {"error": f"Body is not JSON: {e}"})
            return

        pages = body.get("pages")
        if not isinstance(pages, dict) or not pages:
            self._json(400, {"error": "Body needs a non-empty 'pages' object"})
            return
        if len(pages) > MAX_PAGES:
            self._json(400, {"error": f"{len(pages)} pages, max {MAX_PAGES}"})
            return

        rows = []
        for slug, page in pages.items():
            if not SLUG_RE.match(slug):
                self._json(400, {"error": f"unknown slug {slug!r}"})
                return
            if not isinstance(page, dict) or "data" not in page or "etag" not in page:
                self._json(400, {"error": f"{slug}: need both 'data' and 'etag'"})
                return
            rows.append({"slug": slug, "data": page["data"],
                         "etag": page["etag"], "updated_at": "now()"})

        try:
            before = manifest()
            supabase_request(
                "action_pages?on_conflict=slug",
                method="POST",
                body=rows,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            # Anything the push did not mention is no longer part of the book.
            gone = sorted(set(before) - set(pages))
            for slug in gone:
                supabase_request(
                    f"action_pages?slug=eq.{urllib.parse.quote(slug)}",
                    method="DELETE", headers={"Prefer": "return=minimal"})
        except Exception as e:                       # noqa: BLE001
            self._json(500, {"error": str(e)})
            return

        changed = sorted(s for s, p in pages.items() if before.get(s) != p["etag"])
        self._json(200, {"written": len(rows), "changed": changed,
                         "unchanged": len(rows) - len(changed), "removed": gone})

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
