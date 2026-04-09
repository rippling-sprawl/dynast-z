#!/usr/bin/env python3
"""Build script that adds content-hash query strings to local CSS/JS references in HTML files.

This ensures browsers fetch fresh assets after each deployment.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parent


def file_hash(path: Path) -> str:
    """Return first 8 chars of the SHA-256 hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def build():
    # Build a map of asset paths to their content hashes
    asset_hashes: dict[str, str] = {}
    for pattern in ("styles/*.css", "scripts/*.js"):
        for f in ROOT.glob(pattern):
            rel = "/" + f.relative_to(ROOT).as_posix()
            asset_hashes[rel] = file_hash(f)

    print(f"Hashed {len(asset_hashes)} assets:")
    for path, h in sorted(asset_hashes.items()):
        print(f"  {path} -> {h}")

    # Process all HTML files
    html_files = list(ROOT.glob("views/**/*.html"))
    pattern = re.compile(
        r'((?:href|src)=["\'])(/(?:styles|scripts)/[^"\'?]+)(\??[^"\']*?)(["\'])'
    )

    for html_file in html_files:
        original = html_file.read_text()

        def replacer(m: re.Match) -> str:
            prefix = m.group(1)   # href=" or src="
            asset = m.group(2)    # /styles/foo.css
            closing = m.group(4)  # " or '
            h = asset_hashes.get(asset)
            if h:
                return f"{prefix}{asset}?v={h}{closing}"
            return m.group(0)

        updated = pattern.sub(replacer, original)
        if updated != original:
            html_file.write_text(updated)
            print(f"Updated {html_file.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
