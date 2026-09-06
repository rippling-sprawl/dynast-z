"""
/api/action — the Action Network betting book, rendered per request.

GET /api/action?slug=index|futures|week-1..18|preseason|postseason|other

The book used to be twenty committed HTML files under views/football/, served
with `no-store` at 464 KB a page and 1.5 MB for the futures board, every byte of
it re-sent on every load because the artwork was inlined into the same file as
the data. It is now one page model per slate in Supabase, three board builders in
api/_action/render.py, and one shell template.

CACHING, AND WHY IT IS SHAPED THIS WAY

The page model carries its own content hash, written by scripts/build_action.py,
and that hash is the ETag. A request therefore costs:

  unchanged, warm instance   one `select=etag` (a few hundred bytes), then either
                             a 304 with no body, or the memoised HTML
  unchanged, cold instance   the same, plus one render
  changed                    the etag read, the data read, and one render

which is the "only pay on a change" behaviour the static files never had -- they
had no validator at all, because Vercel's static hosting sends no ETag and a
constant Last-Modified, so `no-store` was the only honest header for them
(ARCHITECTURE.md). An endpoint can do better, so this one does.

`max-age=0, must-revalidate` and no `s-maxage` is deliberate. The whole point of
the PUT ingest is that a push is live in seconds, and there is no way to purge
Vercel's edge cache from inside a function -- so an `s-maxage` would trade the
freshness the ingest exists to provide for speed the ETag already gives. A 304 is
about 200 bytes. If edge caching is ever wanted, adding
`s-maxage=60, stale-while-revalidate=600` here is the whole change, and it costs
exactly 60 seconds of staleness after a push.

NO GATE. The pages are unlisted, not private, exactly as the generated files
were. Adding one is now cheap -- resolve X-User-Id against users.role the way
api/users.py does -- but it would stop the page being a plain document load, so
it is a decision to take on purpose rather than a side effect.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import sys
import urllib.parse
import urllib.request

# Co-located under api/ rather than imported from scripts/: Vercel does not
# bundle scripts/** with a function, which is why /api/odds-ingest is dead in
# production. See the note at the top of _action/render.py. The path insert is
# __file__-relative and stays inside api/, so it resolves whatever the
# serverless runtime sets as the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _action import render as R  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# The slugs the book can have. Anything else is a 404 rather than a lookup --
# this is also what keeps an arbitrary string out of the PostgREST filter below.
SLUG_RE = re.compile(r"^(?:index|futures|preseason|postseason|other"
                     r"|week-(?:[1-9]|1[0-8]))$")

# slug -> (etag, html) for the life of a warm instance. The first in-memory
# cache in any function here, and worth the exception: rendering the futures
# board is the expensive half of a request, and the etag read above tells us for
# certain when the memo is stale, so this can never serve a superseded page.
_MEMO = {}


def supabase_request(path):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def fetch_column(slug, column):
    rows = supabase_request(
        f"action_pages?select={column}&slug=eq.{urllib.parse.quote(slug)}")
    return rows[0][column] if rows else None


def render(slug):
    """(etag, html) for a slug, or (None, None) if the book has no such page."""
    etag = fetch_column(slug, "etag")
    if not etag:
        return None, None

    cached = _MEMO.get(slug)
    if cached and cached[0] == etag:
        return cached

    page = fetch_column(slug, "data")
    if page is None:
        return None, None
    page["images"] = R.asset_images(page.get("images"))
    html = R.render_page(page)
    _MEMO[slug] = (etag, html)
    return etag, html


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        slug = (params.get("slug", [""])[0] or "index").strip()

        if not SLUG_RE.match(slug):
            self._html(404, "Not a page of this book",
                       "There is no slate called that.")
            return

        try:
            etag, html = render(slug)
        except Exception as e:                       # noqa: BLE001
            self._html(500, "The book could not be read", str(e))
            return

        if etag is None:
            self._html(404, "Nothing on this slate yet",
                       "This page has not been pushed. Run "
                       "scripts/build_action.py --push.")
            return

        quoted = f'"{etag}"'
        if self.headers.get("If-None-Match") == quoted:
            self.send_response(304)
            self.send_header("ETag", quoted)
            self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
            self.end_headers()
            return

        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", quoted)
        self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status, title, detail):
        """A plain page for the cases that have no board to draw.

        Deliberately not JSON: this route is loaded as a document, and a browser
        showing a raw error object is worse than a sentence."""
        body = (f"<!DOCTYPE html><meta charset=utf-8><title>{R.esc(title)}</title>"
                "<div style=\"font:16px/1.5 system-ui;max-width:34em;"
                "margin:20vh auto;padding:0 16px\">"
                f"<h1 style=\"font-size:1.25rem\">{R.esc(title)}</h1>"
                f"<p>{R.esc(detail)}</p>"
                "<p><a href=\"/football/action\">Back to the book</a></p>"
                "</div>").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
