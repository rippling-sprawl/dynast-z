#!/usr/bin/env python3
"""
Parse a FanDuel Recorder bundle into data/fd.json, the file that views/odds.html
loads as its PRIMARY layout (data.layout + data.attachments.markets) before it
unions DraftKings and theScore prices on top.

Input  : data/imports/fd.json   (a Recorder "Copy bundle" output)
Output : data/fd.json           (FanDuel's own native shape, merged)

FanDuel serves the whole NFL futures page through one call:
    api.sportsbook.fanduel.com/sbapi/content-managed-page?page=CUSTOM&customPageId=nfl
whose body is exactly {layout, attachments} — the shape data/fd.json already has.
The page also streams fresher live prices through
    .../fixedodds/readonly/v1/getMarketPrices
which carry updated winRunnerOdds per selectionId. The Recorder captures both, so
a bundle holds one (or more) content-managed-page snapshots plus any price ticks.

The consumer reads ONLY:
  - layout.tabs / layout.cards / layout.coupons   (the navigation tree)
  - layout.tabsDisplayOrder, layout.defaultTab, ...
  - attachments.markets[*].runners[*].runnerName              "Lamar Jackson Over 3200.5"
  - attachments.markets[*].runners[*].winRunnerOdds.americanDisplayOdds.americanOdds
so we re-assemble fd.json in that same native shape and the consumer needs no
changes.

Merge semantics (must match the DK and theScore parsers): a partial capture must
never delete anything. We union every id-keyed collection — layout.{coupons,tabs,
cards,...} and attachments.{markets,events,competitions,eventTypes} — with the
freshly-captured entry overriding the stored one on conflict. Nothing is removed.
List/scalar layout fields (tabsDisplayOrder, defaultTab, page, seo, ...) are taken
from the fresh snapshot when present, else kept. Finally, live getMarketPrices
ticks are folded into the matching runners by selectionId so odds are as fresh as
the capture allows.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "fd.json")
OUT_PATH = os.path.join(ROOT, "data", "fd.json")

# Mirror of the Recorder's blocklist — drop analytics/telemetry hosts at parse
# time too. Keep in sync with BLOCK in scripts/odds-recorder.js.
BLOCK = ["datadoghq.com", "launchdarkly.com"]

# The two FanDuel endpoints we consume.
PAGE_PATH = "content-managed-page"      # full {layout, attachments} snapshot
PRICES_PATH = "getMarketPrices"         # live winRunnerOdds ticks per selectionId

# Every id-keyed dict we union. layout.* live under "layout", attachments.* under
# "attachments"; each is merged by key with the fresh entry winning on conflict.
LAYOUT_DICTS = ["coupons", "tabs", "cards", "links", "dimensions", "marketBlurbs"]
ATT_DICTS = ["eventTypes", "competitions", "events", "markets"]
# layout fields refreshed wholesale from the newest snapshot when present.
LAYOUT_SCALARS = ["page", "seo", "defaultScheduledTabs", "dimensions",
                  "tabsDisplayOrder", "defaultTab"]


def host_of(url):
    try:
        return url.split("/")[2].lower()
    except Exception:
        return ""


def blocked(url):
    h = host_of(url)
    # exact, dot-subdomain (rum.datadoghq.com), or hyphen sibling that vendors
    # use for ingest hosts (browser-intake-datadoghq.com).
    return any(h == d or h.endswith("." + d) or h.endswith("-" + d) for d in BLOCK)


def load_existing():
    """Existing data/fd.json -> {layout, attachments}, or empty scaffolds."""
    if os.path.exists(OUT_PATH):
        try:
            d = json.load(open(OUT_PATH))
            d.setdefault("layout", {})
            d.setdefault("attachments", {})
            return d
        except Exception:
            pass
    return {"layout": {}, "attachments": {}}


def merge_dicts(base, fresh, keys):
    """Union each id-keyed sub-dict; fresh entry wins. Returns per-collection
    {key: (updated, added)} so the caller can report each line accurately."""
    counts = {}
    for k in keys:
        src = fresh.get(k)
        if not isinstance(src, dict):
            continue
        dst = base.setdefault(k, {})
        if not isinstance(dst, dict):
            dst = base[k] = {}
        updated = added = 0
        for key, val in src.items():
            if key in dst:
                updated += 1
            else:
                added += 1
            dst[key] = val
        counts[k] = (updated, added)
    return counts


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])

    out = load_existing()
    layout = out["layout"]
    att = out["attachments"]
    # Snapshot every collection's size before merging, for the summary table.
    old_befores = {}
    for coll in ATT_DICTS:
        old_befores[coll] = len((att.get(coll) or {}))
    for coll in LAYOUT_DICTS:
        old_befores[coll] = len((layout.get(coll) or {}))

    kept_hosts, dropped = set(), 0
    page_snapshots = 0
    price_ticks = {}     # selectionId -> winRunnerOdds (newest capture wins)

    layout_counts = {}   # collection -> (updated, added), aggregated over snapshots
    att_counts = {}

    for c in captures:
        url = c.get("url", "")
        if blocked(url):
            dropped += 1
            continue
        body = c.get("body")

        if PAGE_PATH in url:
            if not isinstance(body, dict):
                continue
            fresh_layout = body.get("layout")
            fresh_att = body.get("attachments")
            if not isinstance(fresh_layout, dict) or not isinstance(fresh_att, dict):
                continue
            kept_hosts.add(host_of(url))
            page_snapshots += 1

            # Union id-keyed collections; newest snapshot wins on conflict.
            for coll, (u, a) in merge_dicts(layout, fresh_layout, LAYOUT_DICTS).items():
                pu, pa = layout_counts.get(coll, (0, 0))
                layout_counts[coll] = (pu + u, pa + a)
            for coll, (u, a) in merge_dicts(att, fresh_att, ATT_DICTS).items():
                pu, pa = att_counts.get(coll, (0, 0))
                att_counts[coll] = (pu + u, pa + a)
            # Refresh whole-value layout fields from the newest snapshot.
            for k in LAYOUT_SCALARS:
                if k in fresh_layout:
                    layout[k] = fresh_layout[k]

        elif PRICES_PATH in url:
            # getMarketPrices returns a list of markets, each with runnerDetails.
            if not isinstance(body, list):
                continue
            kept_hosts.add(host_of(url))
            for mkt in body:
                for rd in (mkt.get("runnerDetails") or []):
                    sid = rd.get("selectionId")
                    if sid is not None and rd.get("winRunnerOdds"):
                        price_ticks[sid] = rd

    if page_snapshots == 0 and not os.path.exists(OUT_PATH):
        sys.exit("No content-managed-page snapshot in bundle and no existing "
                 "data/fd.json to update — nothing to write.")

    # Fold live price ticks into the matching runners by selectionId.
    priced = 0
    if price_ticks:
        for m in (att.get("markets") or {}).values():
            for r in (m.get("runners") or []):
                rd = price_ticks.get(r.get("selectionId"))
                if not rd:
                    continue
                r["winRunnerOdds"] = rd["winRunnerOdds"]
                if "previousWinRunnerOdds" in rd:
                    r["previousWinRunnerOdds"] = rd["previousWinRunnerOdds"]
                if rd.get("runnerStatus"):
                    r["runnerStatus"] = rd["runnerStatus"]
                if "handicap" in rd:
                    r["handicap"] = rd["handicap"]
                priced += 1

    new_markets = len((att.get("markets") or {}))
    new_coupons = len((layout.get("coupons") or {}))

    print("Parsed %d captures (%d page snapshots, dropped %d blocked: %s)" %
          (len(captures), page_snapshots, dropped, ", ".join(BLOCK)))
    print("Source hosts:", ", ".join(sorted(h for h in kept_hosts if h)) or "—")
    print()
    # One row per id-keyed collection: existing-before, updated, added, total-now.
    print("%-14s %8s %8s %8s %8s" % ("collection", "existing", "updated", "added", "total"))
    print("-" * 50)
    for coll in ATT_DICTS + LAYOUT_DICTS:
        counts = att_counts.get(coll) or layout_counts.get(coll)
        if counts is None:
            continue
        bucket = att if coll in ATT_DICTS else layout
        updated, added = counts
        print("%-14s %8d %8d %8d %8d" %
              (coll, old_befores.get(coll, 0), updated, added, len(bucket.get(coll) or {})))
    if price_ticks:
        print("\nLive price ticks: %d selections in bundle, %d folded into runners."
              % (len(price_ticks), priced))

    if page_snapshots == 0 and not price_ticks:
        print("\nNo FanDuel content in bundle — fd.json left unchanged.")
        return

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print("\nWrote data/fd.json (%d markets, %d coupons, %d tabs)" %
          (new_markets, new_coupons, len(layout.get("tabs") or {})))


if __name__ == "__main__":
    main()
