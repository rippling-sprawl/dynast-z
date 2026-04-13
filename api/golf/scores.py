from http.server import BaseHTTPRequestHandler
import json
import os
import subprocess
from urllib.parse import urlparse, parse_qs

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Tournament configuration: (tournament, year) -> mode + source
TOURNAMENTS = {
    ("masters", "2026"): {"mode": "archive", "path": "data/masters/2026.json"},
    ("masters", "2027"): {"mode": "live", "url": "https://www.masters.com/en_US/scores/feeds/2027/scores.json"},
    ("pga", "2026"): {"mode": "upcoming"},
    ("us-open", "2026"): {"mode": "upcoming"},
    ("open", "2026"): {"mode": "upcoming"},
}


def http_fetch(url):
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "15", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        tournament = params.get("tournament", [None])[0]
        year = params.get("year", [None])[0]

        if not tournament or not year:
            self._json(400, {"error": "tournament and year parameters are required"})
            return

        key = (tournament, year)
        config = TOURNAMENTS.get(key)

        if not config:
            self._json(404, {"error": f"Unknown tournament: {tournament} {year}"})
            return

        mode = config["mode"]

        if mode == "upcoming":
            self._json(200, {"status": "upcoming", "tournament": tournament, "year": int(year)})
            return

        if mode == "archive":
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_path = os.path.join(base_dir, config["path"])
            try:
                with open(data_path, "r") as f:
                    data = json.load(f)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=86400, s-maxage=86400")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except FileNotFoundError:
                self._json(404, {"error": f"Archive data not found for {tournament} {year}"})
            return

        if mode == "live":
            try:
                raw = http_fetch(config["url"])
                data = json.loads(raw)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=600")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
