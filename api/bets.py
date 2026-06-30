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
        raw = resp.read()
        return json.loads(raw) if raw else None


def fetch_user(user_id):
    rows = supabase_request(
        f"users?id=eq.{urllib.request.quote(user_id)}&select=role,status"
    )
    return rows[0] if rows else None


class handler(BaseHTTPRequestHandler):
    # Resolve the user_id every operation acts on. Normally the X-User-Id
    # requester. When X-Audit-User-Id is present (an admin managing another user),
    # verify the requester is an active admin, then act on the audit target's
    # rows. For normal writes, require_active gates the requester's own status.
    # Returns (effective_user_id, error) where error is None or a (status, body)
    # tuple to send.
    def _resolve(self, require_active):
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            return None, (401, {"error": "Not authenticated"})
        audit_id = self.headers.get("X-Audit-User-Id")
        if audit_id and audit_id != user_id:
            actor = fetch_user(user_id)
            if (not actor or actor.get("status") is not True
                    or actor.get("role") != "admin"):
                return None, (403, {"error": "Admin access required"})
            return audit_id, None
        if require_active:
            user = fetch_user(user_id)
            if not user or user.get("status") is not True:
                return None, (403, {"error": "Account is inactive"})
        return user_id, None

    # List a user's bets. Reads are not status-gated for the requester's own
    # bets (mirrors /api/sync); managing another user still requires admin.
    def do_GET(self):
        eff, err = self._resolve(require_active=False)
        if err:
            self._json(*err)
            return
        try:
            rows = supabase_request(
                f"bets?user_id=eq.{urllib.request.quote(eff)}"
                f"&select=data&order=created_at"
            )
            self._json(200, [r["data"] for r in (rows or [])])
        except Exception as e:
            self._json(500, {"error": str(e)})

    # Create or update one bet. Gated on an active account (or admin when managing).
    def do_PUT(self):
        eff, err = self._resolve(require_active=True)
        if err:
            self._json(*err)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            bet = json.loads(self.rfile.read(length)) if length else {}
            bet_id = bet.get("id")
            if not bet_id:
                self._json(400, {"error": "bet id is required"})
                return

            # Upsert on the composite key (user_id, id), so a client can never
            # touch another user's row even by supplying someone else's bet id.
            supabase_request(
                "bets?on_conflict=user_id,id",
                method="POST",
                body={
                    "user_id": eff,
                    "id": bet_id,
                    "data": bet,
                    "updated_at": "now()",
                },
                headers={
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
            )
            self._json(200, {"ok": True})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # Delete one bet, scoped to the owner. Gated on an active account (or admin).
    def do_DELETE(self):
        eff, err = self._resolve(require_active=True)
        if err:
            self._json(*err)
            return
        try:
            params = parse_qs(urlparse(self.path).query)
            bet_id = params.get("id", [None])[0]
            if not bet_id:
                self._json(400, {"error": "id parameter is required"})
                return

            supabase_request(
                f"bets?user_id=eq.{urllib.request.quote(eff)}"
                f"&id=eq.{urllib.request.quote(bet_id)}",
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id, X-Audit-User-Id")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id, X-Audit-User-Id")
        self.end_headers()
