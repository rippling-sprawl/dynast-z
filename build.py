#!/usr/bin/env python3
"""Deploy-time cache busting for local CSS/JS references in HTML files.

Assets are served with `max-age=31536000, immutable` (see vercel.json), so the
URL must change when the content does. This script appends a content hash as
`?v=<hash8>` to every local /styles/* and /scripts/* reference in the views.

Hashes are NEVER committed. Source HTML references assets unversioned; Vercel
runs this script on every deploy via `buildCommand`, so the committed tree and
the deployed tree differ by exactly these query strings.

Usage:
    python3 build.py           inject content hashes (what Vercel runs)
    python3 build.py --strip   remove them again (undo a stray local run)
    python3 build.py --check   exit 1 if any hash is present in the source tree
"""

from __future__ import annotations  # macOS system python3 is 3.9

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

HTML_GLOB = "**/*.html"

# href="/styles/foo.css" or src='/scripts/bar.js', with an optional query string.
ASSET_REF = re.compile(
    r'((?:href|src)=["\'])(/(?:styles|scripts)/[^"\'?]+)(\?[^"\']*)?(["\'])'
)


def file_hash(path: Path) -> str:
    """Return first 8 chars of the SHA-256 hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def asset_hashes() -> dict[str, str]:
    """Map every hashable asset's absolute URL path to its content hash."""
    hashes: dict[str, str] = {}
    for pattern in ("styles/**/*.css", "scripts/**/*.js"):
        for f in ROOT.glob(pattern):
            hashes["/" + f.relative_to(ROOT).as_posix()] = file_hash(f)
    return hashes


def html_files() -> list[Path]:
    return sorted(
        f for f in ROOT.glob(HTML_GLOB) if ".git" not in f.parts
    )


def other_params(query: str | None) -> str:
    """Return the query string minus any `v` param, ready to re-append."""
    if not query:
        return ""
    kept = [p for p in query.lstrip("?").split("&") if p and not p.startswith("v=")]
    return ("?" + "&".join(kept)) if kept else ""


def rewrite(text: str, hashes: dict[str, str] | None) -> str:
    """Inject hashes (or strip them, when `hashes` is None) in one HTML string."""

    def replacer(m: re.Match) -> str:
        prefix, asset, query, closing = m.groups()
        rest = other_params(query)
        h = hashes.get(asset) if hashes else None
        if h:
            extra = "&" + rest.lstrip("?") if rest else ""
            return f"{prefix}{asset}?v={h}{extra}{closing}"
        return f"{prefix}{asset}{rest}{closing}"

    return ASSET_REF.sub(replacer, text)


def apply(hashes: dict[str, str] | None) -> int:
    """Rewrite every HTML file in place. Returns the number changed."""
    changed = 0
    for html_file in html_files():
        original = html_file.read_text()
        updated = rewrite(original, hashes)
        if updated != original:
            html_file.write_text(updated)
            print(f"Updated {html_file.relative_to(ROOT)}")
            changed += 1
    return changed


def build() -> None:
    hashes = asset_hashes()
    print(f"Hashed {len(hashes)} assets:")
    for path, h in sorted(hashes.items()):
        print(f"  {path} -> {h}")
    print(f"Injected hashes into {apply(hashes)} HTML files.")


def strip() -> None:
    print(f"Stripped hashes from {apply(None)} HTML files.")


def check() -> int:
    """Fail if the source tree carries any cache-bust hash."""
    offenders = [
        f.relative_to(ROOT)
        for f in html_files()
        if re.search(r'(?:href|src)=["\']/(?:styles|scripts)/[^"\']*\?v=', f.read_text())
    ]
    if offenders:
        print("Cache-bust hashes must not be committed. Run: python3 build.py --strip")
        for f in offenders:
            print(f"  {f}")
        return 1
    print("Clean: no cache-bust hashes in source HTML.")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--strip":
        strip()
    elif arg == "--check":
        sys.exit(check())
    elif arg:
        print(__doc__)
        sys.exit(2)
    else:
        build()
