"""
/api/odds-ingest — paste-a-bundle ingest for the /odds page.

PUT : body is a raw Recorder bundle (or {"bundle": <bundle>}). The book is
      auto-detected (override with ?book=fd|dk|score). We load the current odds
      state from Supabase, merge the bundle in via scripts/odds_merge.ingest
      (additive — never deletes other books/markets/candidates), and write back
      only the keys this bundle touched. Idempotent: re-pasting the same bundle
      is a no-op. Auth: X-User-Id header; the user must be active with role 'admin'.
GET : returns the merged state for the page. ?key=fd|dk|score|outrights for one
      artifact, otherwise all four. Public (these were public static files).

Storage: a Supabase table `odds_state(data_key text pk, data jsonb, updated_at)`.
See docs/odds-ingest.md for the schema and the odds.html migration.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse
import urllib.request

# Import the shared merge library. __file__-relative so it resolves regardless of
# the serverless runtime's working dir; vercel.json bundles scripts/** alongside.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import odds_merge  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

STATE_KEYS = ("fd", "dk", "score", "outrights")


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


def load_state():
    """Read the four artifacts from Supabase into a merge-ready state dict."""
    rows = supabase_request("odds_state?select=data_key,data") or []
    stored = {r["data_key"]: r["data"] for r in rows}
    state = odds_merge.empty_state()
    for k in STATE_KEYS:
        if stored.get(k) is not None:
            state[k] = stored[k]
    return state


def save_keys(state, keys):
    """Upsert just the touched artifacts (PostgREST merge-duplicates on data_key)."""
    payload = [{"data_key": k, "data": state[k], "updated_at": "now()"} for k in keys]
    supabase_request(
        "odds_state?on_conflict=data_key",
        method="POST",
        body=payload,
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def json_safe(o):
    """Make a parser summary JSON-serializable (tuple dict-keys -> strings)."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if isinstance(k, tuple):
                k = " ".join(str(x) for x in k)
            elif not isinstance(k, str):
                k = str(k)
            out[k] = json_safe(v)
        return out
    if isinstance(o, (list, tuple)):
        return [json_safe(x) for x in o]
    return o


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        key = params.get("key", [None])[0]
        try:
            if key:
                if key not in STATE_KEYS:
                    self._json(400, {"error": "unknown key %r" % key})
                    return
                rows = supabase_request(
                    "odds_state?select=data&data_key=eq." + urllib.parse.quote(key))
                self._json(200, rows[0]["data"] if rows else None)
            else:
                self._json(200, load_state())
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            self._json(401, {"error": "Not authenticated"})
            return
        user = fetch_user(user_id)
        if not user or user.get("status") is not True or user.get("role") != "admin":
            self._json(403, {"error": "Not authorized to update odds"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._json(400, {"error": "Body must be JSON"})
            return

        # Accept a raw Recorder bundle or {"bundle": <bundle>, "book": <override>}.
        bundle = body.get("bundle") if isinstance(body, dict) and "captures" not in body else body
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        book = params.get("book", [None])[0] or (body.get("book") if isinstance(body, dict) else None)

        if not isinstance(bundle, dict) or not bundle.get("captures"):
            self._json(400, {"error": "No Recorder bundle found (expected a "
                                      "'captures' array)"})
            return

        try:
            state = load_state()
            state, summary = odds_merge.ingest(bundle, state, book=book)
            save_keys(state, summary["changed_keys"])
        except ValueError as e:          # book couldn't be determined
            self._json(400, {"error": str(e)})
            return
        except Exception as e:
            self._json(500, {"error": str(e)})
            return

        self._json(200, {"ok": True, "book": summary["book"],
                         "changed": summary["changed_keys"],
                         "summary": json_safe({k: v for k, v in summary.items()
                                               if k not in ("book", "changed_keys")})})

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
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
