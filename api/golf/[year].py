from http.server import BaseHTTPRequestHandler
import os


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        html_path = os.path.join(base_dir, "views", "golf", "season.html")
        with open(html_path, "r") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
        self.end_headers()
        self.wfile.write(content.encode())
