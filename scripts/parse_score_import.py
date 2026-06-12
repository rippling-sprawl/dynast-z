#!/usr/bin/env python3
"""
Parse a theScore Recorder bundle into the per-stat files that views/odds.html's
buildScoreIndex() consumes (data/score/<stat>.json).

Input  : data/imports/score.json  (a Recorder "Copy bundle" output)
Output : data/score/{passing_yards,passing_tds,receiving_yards,
                     receiving_tds,rushing_yards,wins}.json

The bundle captures theScore's GraphQL responses (CompetitionDrawerContent /
SeeAllLinesModal). Each TOTAL market is an Over/Under player|team line whose
name is e.g. "Ashton Jeanty Total Rushing Yards" / "BUF Bills Regular Season
Wins" — exactly the format buildScoreIndex strips to recover the player/team.

We re-emit each stat in the file shape the consumer already expects:
    {data:{page:{title, pageChildren:[{sectionChildren:[
        {marketplaceShelfChildren:[{markets:[ <slim market> ]}]}]}]}}}

LIST markets (MVP, OPOY, DPOY, Super Bowl Winner, Most Regular Season Wins) are
outright/award markets the odds page does not render today — they are reported
but not written.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "score.json")
SCORE_DIR = os.path.join(ROOT, "data", "score")

# Mirror of the Recorder's blocklist — drop analytics/telemetry hosts at parse
# time too, so a bundle captured by an older Recorder is still cleaned. Keep in
# sync with BLOCK in scripts/odds-recorder.js.
BLOCK = ["datadoghq.com", "launchdarkly.com"]

# stat-name suffix (as it appears at the end of a market name) -> (file, page title)
STAT_MAP = [
    ("Total Passing Yards",    "passing_yards",   "Regular Season Passing Yards"),
    ("Total Passing TDs",      "passing_tds",     "Regular Season Passing TDs"),
    ("Total Rushing Yards",    "rushing_yards",   "Regular Season Rushing Yards"),
    ("Total Receiving Yards",  "receiving_yards", "Regular Season Receiving Yards"),
    ("Total Receiving TDs",    "receiving_tds",   "Regular Season Receiving TDs"),
    ("Regular Season Wins",    "wins",            "Regular Season Wins"),
]


def host_of(url):
    try:
        return url.split("/")[2].lower()
    except Exception:
        return ""


def blocked(url):
    h = host_of(url)
    # Match the exact host, a dot-subdomain (rum.datadoghq.com), or a hyphen
    # sibling that vendors use for ingest hosts (browser-intake-datadoghq.com).
    return any(h == d or h.endswith("." + d) or h.endswith("-" + d) for d in BLOCK)


def iter_markets(obj):
    """Yield every dict carrying a 'selections' list anywhere in the tree."""
    if isinstance(obj, dict):
        if isinstance(obj.get("selections"), list):
            yield obj
        for v in obj.values():
            yield from iter_markets(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_markets(v)


def slim_market(m):
    """Keep only what buildScoreIndex reads, for tidy, predictable files."""
    sels = []
    for s in m.get("selections", []):
        name = s.get("name") or {}
        pts = s.get("points") or {}
        odds = s.get("odds") or {}
        sels.append({
            "name": {"cleanName": name.get("cleanName")},
            "type": s.get("type"),
            "points": {"decimalPoints": pts.get("decimalPoints")} if pts else None,
            "odds": {"formattedOdds": odds.get("formattedOdds")},
        })
    return {"name": m.get("name"), "type": m.get("type"), "selections": sels}


def classify(name):
    """Return the STAT_MAP entry whose suffix matches this market name, or None."""
    for suffix, fname, title in STAT_MAP:
        if name.endswith(suffix):
            return (suffix, fname, title)
    return None


def wrap(title, markets):
    return {"data": {"page": {"title": title, "pageChildren": [
        {"sectionChildren": [
            {"marketplaceShelfChildren": [{"markets": markets}]}
        ]}
    ]}}}


def collect_score(captures):
    """Scan captures for theScore markets. Returns (totals, list_markets,
    kept_hosts, dropped): `totals` maps a TOTAL market name to its slim form
    (deduped, keeping the version with the most selections); `list_markets` maps
    each LIST/outright name to its selection count (reported, not written)."""
    kept_hosts, dropped = set(), 0
    totals, list_markets = {}, {}
    for c in captures:
        url = c.get("url", "")
        if blocked(url):
            dropped += 1
            continue
        body = c.get("body")
        if not isinstance(body, dict):
            continue
        kept_hosts.add(host_of(url))
        for m in iter_markets(body.get("data")):
            name = (m.get("name") or "").strip()
            if not name:
                continue
            if m.get("type") == "LIST":
                list_markets[name] = len(m.get("selections", []))
                continue
            if m.get("type") != "TOTAL":
                continue
            if classify(name) is None:
                continue
            slim = slim_market(m)
            prev = totals.get(name)
            if prev is None or len(slim["selections"]) > len(prev["selections"]):
                totals[name] = slim
    return totals, list_markets, kept_hosts, dropped


def merge_score(existing_by_stat, captures):
    """Merge a theScore bundle into the prior per-stat docs. `existing_by_stat`
    maps a stat file name ("wins", "passing_yards", ...) to its wrapped doc.
    Returns (out_by_stat, summary): out_by_stat holds ONLY the stats this bundle
    changed (each a freshly-wrapped doc), so the caller updates just those keys.
    Pure: no file I/O, no printing."""
    existing_by_stat = existing_by_stat or {}
    totals, list_markets, kept_hosts, dropped = collect_score(captures)

    grouped = {fname: [] for _, fname, _ in STAT_MAP}
    titles = {fname: title for _, fname, title in STAT_MAP}
    for name, slim in totals.items():
        _suffix, fname, _title = classify(name)
        grouped[fname].append(slim)

    out_by_stat = {}
    stats = {}            # fname -> {existing, updated, added, total, changed}
    for _, fname, _ in STAT_MAP:
        existing = {}
        old = existing_by_stat.get(fname)
        if old:
            for m in iter_markets(old):
                if isinstance(m.get("name"), str):
                    existing[m["name"]] = m

        captured = grouped[fname]
        updated = sum(1 for m in captured if m["name"] in existing)
        added = len(captured) - updated
        merged = dict(existing)
        for m in captured:
            merged[m["name"]] = m            # new capture wins on conflict
        mkts = sorted(merged.values(), key=lambda m: m["name"])

        changed = bool(captured)
        if changed:
            out_by_stat[fname] = wrap(titles[fname], mkts)
        stats[fname] = {"existing": len(existing), "updated": updated,
                        "added": added, "total": len(mkts), "changed": changed}

    summary = {
        "captures": len(captures),
        "dropped": dropped,
        "kept_hosts": sorted(h for h in kept_hosts if h),
        "stats": stats,
        "list_markets": list_markets,
        "changed": bool(out_by_stat),
    }
    return out_by_stat, summary


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])

    existing_by_stat = {}
    for _, fname, _ in STAT_MAP:
        path = os.path.join(SCORE_DIR, fname + ".json")
        if os.path.exists(path):
            try:
                existing_by_stat[fname] = json.load(open(path))
            except Exception:
                pass

    out_by_stat, s = merge_score(existing_by_stat, captures)

    print("Parsed %d captures (dropped %d blocked: %s)" %
          (s["captures"], s["dropped"], ", ".join(BLOCK)))
    print("Source hosts:", ", ".join(s["kept_hosts"]) or "—")
    print()
    print("%-16s %8s %8s %8s %8s" % ("stat", "existing", "updated", "added", "total"))
    print("-" * 54)
    written = 0
    for _, fname, _ in STAT_MAP:
        st = s["stats"][fname]
        if not st["changed"]:
            print("%-16s %8d %8s %8s %8d   (no capture — kept)" %
                  (fname, st["existing"], "-", "-", st["total"]))
            continue
        with open(os.path.join(SCORE_DIR, fname + ".json"), "w") as f:
            json.dump(out_by_stat[fname], f, indent=2)
        written += 1
        print("%-16s %8d %8d %8d %8d" %
              (fname, st["existing"], st["updated"], st["added"], st["total"]))

    print()
    if s["list_markets"]:
        print("LIST/outright markets present but NOT written (no Over/Under view yet):")
        for n in sorted(s["list_markets"]):
            print("  - %s (%d selections)" % (n, s["list_markets"][n]))
    print("\nWrote %d/%d stat files." % (written, len(STAT_MAP)))


if __name__ == "__main__":
    main()
