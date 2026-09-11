from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone
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
RESET_CODE_TTL_MINUTES = 30
# No 0/O/1/I/L: these codes get read aloud or retyped off a screenshot.
RESET_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


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
        raw = resp.read()          # PATCH/DELETE answer 204 with no body
        return json.loads(raw) if raw else None


def q(value):
    """Escape a PostgREST filter value. safe='' matters for timestamps, where a
    bare '+' in the UTC offset would otherwise decode as a space."""
    return urllib.request.quote(str(value), safe="")


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


def new_reset_code():
    raw = "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def hash_reset_code(code):
    """Codes are stored as a digest only, so a dump of password_resets can't be
    replayed. Normalized first, so '8f3k-92qx', '8F3K92QX' and ' 8F3K 92QX '
    all redeem the same row."""
    normalized = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def retire_reset_codes(user_id):
    """Burn every outstanding code for a user. Called when one is redeemed, when
    a fresh one is issued, and when the password changes by any route — so at
    most one code is ever live, and changing your password kills a code an admin
    handed out while you still knew the old one."""
    supabase_request(
        f"password_resets?user_id=eq.{q(user_id)}&used_at=is.null",
        method="PATCH",
        body={"used_at": datetime.now(timezone.utc).isoformat()},
    )


def set_password(user_id, password):
    supabase_request(
        f"users?id=eq.{q(user_id)}",
        method="PATCH",
        body={"password_hash": hash_password(password)},
    )
    retire_reset_codes(user_id)


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

            # Signed-in change. The current password is the proof of identity,
            # which is why this doesn't settle for the X-User-Id header alone.
            elif action == "change_password":
                user_id = self.headers.get("X-User-Id")
                if not user_id:
                    self._json(401, {"error": "Not authenticated"})
                    return
                current = body.get("current_password") or ""
                new_password = body.get("new_password") or ""
                if len(new_password) < MIN_PASSWORD_LEN:
                    self._json(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                    return

                users = supabase_request(
                    f"users?id=eq.{q(user_id)}&select=id,password_hash,status"
                )
                if not users or users[0].get("status") is not True:
                    self._json(403, {"error": "Account is inactive"})
                    return
                if not verify_password(current, users[0].get("password_hash") or ""):
                    self._json(401, {"error": "Current password is incorrect"})
                    return

                set_password(user_id, new_password)
                self._json(200, {"ok": True})

            # Admin hands the returned code to the locked-out user out of band.
            # It is shown once and never stored in the clear.
            elif action == "issue_reset":
                actor_id = self.headers.get("X-User-Id")
                if not actor_id:
                    self._json(401, {"error": "Not authenticated"})
                    return
                actors = supabase_request(f"users?id=eq.{q(actor_id)}&select=role,status")
                actor = actors[0] if actors else None
                if (not actor or actor.get("status") is not True
                        or actor.get("role") != "admin"):
                    self._json(403, {"error": "Admin access required"})
                    return

                username = (body.get("username") or "").strip()
                if not username:
                    self._json(400, {"error": "Username is required"})
                    return
                rows = supabase_request(
                    f"users?username=eq.{q(username)}&select=id,username"
                )
                if not rows:
                    self._json(404, {"error": "No such user"})
                    return

                user = rows[0]
                retire_reset_codes(user["id"])
                code = new_reset_code()
                expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_CODE_TTL_MINUTES)
                supabase_request("password_resets", method="POST", body={
                    "code_hash": hash_reset_code(code),
                    "user_id": user["id"],
                    "expires_at": expires.isoformat(),
                })
                self._json(200, {
                    "code": code,
                    "username": user["username"],
                    "expires_in_minutes": RESET_CODE_TTL_MINUTES,
                })

            # Redeem a code. Signs the user straight in, the same shape login
            # returns, so they aren't bounced to a form they can't fill.
            elif action == "reset_password":
                username = (body.get("username") or "").strip()
                code = body.get("code") or ""
                new_password = body.get("new_password") or ""
                if not username or not code:
                    self._json(400, {"error": "Username and reset code are required"})
                    return
                if len(new_password) < MIN_PASSWORD_LEN:
                    self._json(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                    return

                # One filter covers the whole check — right code, unredeemed,
                # unexpired — so a stale row simply fails to match.
                now = datetime.now(timezone.utc).isoformat()
                rows = supabase_request(
                    f"password_resets?code_hash=eq.{hash_reset_code(code)}"
                    f"&used_at=is.null&expires_at=gt.{q(now)}&select=user_id"
                )
                users = supabase_request(
                    f"users?username=eq.{q(username)}&select=id,username,role,status"
                ) if rows else []
                # The code must belong to the account being named, so a code
                # issued for one user can't be spent on another.
                if not rows or not users or users[0]["id"] != rows[0]["user_id"]:
                    self._json(400, {"error": "That reset code is invalid or has expired"})
                    return

                user = users[0]
                if user.get("status") is not True:
                    self._json(403, {"error": "Account is inactive"})
                    return

                set_password(user["id"], new_password)   # also burns the code
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
