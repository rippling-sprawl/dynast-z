from http.server import BaseHTTPRequestHandler
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _http import send  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        html_path = os.path.join(base_dir, "views", "golf", "season.html")
        with open(html_path, "r") as f:
            content = f.read()
        send(self, 200, content.encode(), "text/html; charset=utf-8",
             {"Cache-Control": "public, max-age=0, must-revalidate"})
