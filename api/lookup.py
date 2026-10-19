from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.request
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _http import send_json  # noqa: E402

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
        return json.loads(resp.read())


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        username = params.get("username", [None])[0]

        if not username:
            self._json(400, {"error": "username parameter is required"})
            return

        try:
            users = supabase_request(
                f"users?username=eq.{urllib.request.quote(username)}&select=id,username"
            )
            if not users:
                self._json(404, {"error": "no username found"})
                return

            user_id = users[0]["id"]

            sport = params.get("sport", ["masters"])[0]
            rows = supabase_request(
                f"user_data?user_id=eq.{user_id}"
                f"&sport=eq.{urllib.request.quote(sport)}"
                f"&data_key=eq.3ball"
                f"&select=data"
            )

            data = rows[0]["data"] if rows else {"rounds": {}}
            self._json(200, {"username": users[0]["username"], "threeBall": data})

        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        send_json(self, status, data, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
