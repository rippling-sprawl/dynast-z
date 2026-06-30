from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def supabase_request(path, method="GET", body=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def fetch_user(user_id):
    rows = supabase_request(
        f"users?id=eq.{urllib.request.quote(user_id)}&select=role,status"
    )
    return rows[0] if rows else None


class handler(BaseHTTPRequestHandler):
    # Admin-only: list all users (id + username) for the /bets/audit dropdown.
    def do_GET(self):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            self._json(401, {"error": "Not authenticated"})
            return
        try:
            actor = fetch_user(user_id)
            if (not actor or actor.get("status") is not True
                    or actor.get("role") != "admin"):
                self._json(403, {"error": "Admin access required"})
                return
            rows = supabase_request("users?select=id,username&order=username.asc")
            self._json(200, rows or [])
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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
