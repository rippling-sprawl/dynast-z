"""Response writing shared by every function under api/ (and server.py).

JSON goes out compact (no whitespace after separators), and any body of 1 KB
or more is gzipped when the client advertises it. Smaller bodies are sent as
they are: the gzip header and trailer would eat most of the saving.

Leading underscore: Vercel does not route `_*.py`, but bundles it with every
function that imports it, the same as api/_action and api/_pickem.
"""
import gzip
import json

GZIP_MIN_BYTES = 1024


def dumps(data):
    """Compact UTF-8 JSON bytes."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def send(handler, status, body, content_type, headers=None):
    """Write status, headers and `body` (bytes), gzipped when worthwhile."""
    accepts = handler.headers.get("Accept-Encoding", "") if handler.headers else ""
    gzipped = len(body) >= GZIP_MIN_BYTES and "gzip" in accepts.lower()
    if gzipped:
        body = gzip.compress(body, compresslevel=6)
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Vary", "Accept-Encoding")
    if gzipped:
        handler.send_header("Content-Encoding", "gzip")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def send_json(handler, status, data, headers=None):
    send(handler, status, dumps(data), "application/json", headers)
