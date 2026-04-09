from http.server import BaseHTTPRequestHandler
import json
import os
import secrets
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def supabase_request(path, method="GET", body=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    if method == "POST":
        req.add_header("Prefer", "return=representation")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def generate_code():
    return "".join(secrets.choice(CODE_CHARS) for _ in range(6))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            action = body.get("action")

            if action == "register":
                display_name = (body.get("display_name") or "").strip()
                if not display_name:
                    self._json(400, {"error": "Display name is required"})
                    return

                # Check if name is taken
                existing = supabase_request(
                    f"users?display_name=eq.{urllib.request.quote(display_name)}&select=id"
                )
                if existing:
                    self._json(409, {"error": "That name is already taken"})
                    return

                # Generate unique claim code
                for _ in range(10):
                    code = generate_code()
                    taken = supabase_request(f"users?claim_code=eq.{code}&select=id")
                    if not taken:
                        break
                else:
                    self._json(500, {"error": "Could not generate unique code"})
                    return

                result = supabase_request("users", method="POST", body={
                    "display_name": display_name,
                    "claim_code": code,
                })
                user = result[0]
                self._json(200, {
                    "user_id": user["id"],
                    "display_name": user["display_name"],
                    "claim_code": user["claim_code"],
                })

            elif action == "login":
                display_name = (body.get("display_name") or "").strip()
                claim_code = (body.get("claim_code") or "").strip().upper()
                if not display_name or not claim_code:
                    self._json(400, {"error": "Display name and code are required"})
                    return

                users = supabase_request(
                    f"users?display_name=eq.{urllib.request.quote(display_name)}"
                    f"&claim_code=eq.{urllib.request.quote(claim_code)}&select=id,display_name,claim_code"
                )
                if not users:
                    self._json(401, {"error": "Invalid name or code"})
                    return

                user = users[0]
                self._json(200, {
                    "user_id": user["id"],
                    "display_name": user["display_name"],
                    "claim_code": user["claim_code"],
                })

            else:
                self._json(400, {"error": "Unknown action"})

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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
