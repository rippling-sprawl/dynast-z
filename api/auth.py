from http.server import BaseHTTPRequestHandler
import json
import os
import hashlib
import hmac
import secrets
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LEN = 8


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


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            action = body.get("action")

            if action == "register":
                username = (body.get("username") or "").strip()
                password = body.get("password") or ""
                if not username:
                    self._json(400, {"error": "Username is required"})
                    return
                if len(password) < MIN_PASSWORD_LEN:
                    self._json(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                    return

                # Check if username is taken
                existing = supabase_request(
                    f"users?username=eq.{urllib.request.quote(username)}&select=id"
                )
                if existing:
                    self._json(409, {"error": "That username is already taken"})
                    return

                result = supabase_request("users", method="POST", body={
                    "username": username,
                    "password_hash": hash_password(password),
                })
                user = result[0]
                self._json(200, {
                    "user_id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
                })

            elif action == "login":
                username = (body.get("username") or "").strip()
                password = body.get("password") or ""
                if not username or not password:
                    self._json(400, {"error": "Username and password are required"})
                    return

                users = supabase_request(
                    f"users?username=eq.{urllib.request.quote(username)}"
                    f"&select=id,username,password_hash,role,status"
                )
                if not users or not verify_password(password, users[0].get("password_hash") or ""):
                    self._json(401, {"error": "Invalid username or password"})
                    return

                user = users[0]
                self._json(200, {
                    "user_id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
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
