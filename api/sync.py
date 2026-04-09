from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
from urllib.parse import urlparse, parse_qs

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def supabase_request(path, method="GET", body=None, headers=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            self._json(401, {"error": "Not authenticated"})
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        sport = params.get("sport", [None])[0]

        if not sport:
            self._json(400, {"error": "sport parameter is required"})
            return

        key = params.get("key", [None])[0]

        try:
            query = (
                f"user_data?user_id=eq.{urllib.request.quote(user_id)}"
                f"&sport=eq.{urllib.request.quote(sport)}"
                f"&select=data_key,data,updated_at"
            )
            if key:
                query += f"&data_key=eq.{urllib.request.quote(key)}"

            rows = supabase_request(query)

            if key:
                if rows:
                    self._json(200, rows[0]["data"])
                else:
                    self._json(200, None)
            else:
                result = {r["data_key"]: r["data"] for r in rows}
                self._json(200, result)

        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            self._json(401, {"error": "Not authenticated"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            sport = body.get("sport")
            key = body.get("key")
            data = body.get("data")

            if not sport or not key:
                self._json(400, {"error": "sport and key are required"})
                return

            # Upsert using PostgREST on-conflict resolution
            supabase_request(
                "user_data?on_conflict=user_id,sport,data_key",
                method="POST",
                body={
                    "user_id": user_id,
                    "sport": sport,
                    "data_key": key,
                    "data": data,
                    "updated_at": "now()",
                },
                headers={
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
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
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
