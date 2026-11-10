"""Edit the /power-rankings deck from the command line, against the same
Supabase row the page saves to (the copy of record; see
scripts/sql/power_rankings.sql).

    python3 scripts/power_rankings_sync.py pull deck.json   # {"version", "model"}
    # ...edit deck.json's "model"...
    python3 scripts/power_rankings_sync.py push deck.json

push goes through api/power-rankings.py's write_deck as ADMIN_USER_ID (.env),
so it is held to the same version lock as the page: if anyone saved after the
pull, it is refused rather than written over them. Pull again and redo the edit.
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

spec = importlib.util.spec_from_file_location(
    "power_rankings_api", os.path.join(ROOT, "api", "power-rankings.py"))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def main(argv):
    if len(argv) != 3 or argv[1] not in ("pull", "push"):
        sys.exit(__doc__)
    cmd, path = argv[1], argv[2]
    admin = os.environ.get("ADMIN_USER_ID")
    if not admin:
        sys.exit("ADMIN_USER_ID is not set")

    if cmd == "pull":
        status, body = api.read_deck(admin)
        if status != 200:
            sys.exit(f"{status}: {body}")
        with open(path, "w") as f:
            json.dump({"version": body["version"], "model": body["model"]}, f,
                      indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"pulled version {body['version']} -> {path}")
    else:
        with open(path) as f:
            deck = json.load(f)
        status, body = api.write_deck(admin, deck)
        if status != 200:
            sys.exit(f"{status}: {body}")
        print(f"pushed version {deck['version']} -> {body['version']}")


if __name__ == "__main__":
    main(sys.argv)
