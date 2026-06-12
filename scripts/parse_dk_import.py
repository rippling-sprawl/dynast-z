#!/usr/bin/env python3
"""
Parse a DraftKings Recorder bundle into data/dk.json, the file that
views/odds.html's buildDkIndex() consumes.

Input  : data/imports/dk.json   (a Recorder "Copy bundle" output)
Output : data/dk.json           (DraftKings' own native shape, merged)

DK serves futures through sportscontent/.../leagueSubcategory/v1/markets, each
response carrying parallel `markets` + `selections` lists linked by marketId
(plus sports/leagues/events metadata). The Recorder captures one such response
per subcategory the page loads, so a bundle holds many of them. We re-assemble a
single dk.json in that *same native shape*, so the consumer needs no changes.

buildDkIndex() reads ONLY:
  - market.name              e.g. "NFL 2026/27 - Lamar Jackson Regular Season Passing Yards"
  - selection.outcomeType    "Over" / "Under"
  - selection.label          "Over 3999.5"   (line parsed out)
  - selection.displayOdds.american

So we keep only the Over/Under player-prop markets (those whose selections carry
an outcomeType). Outright / award / division-winner markets (Winner, MVP-style
awards, "Player to Have 1000+ ...", conference & division winners) have no
Over/Under and the odds page has no home for them yet — they are reported but
not written, exactly like the theScore LIST markets.

Merge semantics (must match the theScore parser): a partial capture must never
delete markets. We union by market name; a freshly-captured market (and its
selections + event) overrides the stored one. Nothing is removed.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "dk.json")
OUT_PATH = os.path.join(ROOT, "data", "dk.json")

# Mirror of the Recorder's blocklist — drop analytics/telemetry hosts at parse
# time too. Keep in sync with BLOCK in scripts/odds-recorder.js.
BLOCK = ["datadoghq.com", "launchdarkly.com"]

# Only these DK endpoints carry the markets+selections we want.
MARKET_PATH = "leagueSubcategory/v1/markets"


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


def is_ou(selections):
    """A player-prop market is one whose selections carry Over/Under outcomes."""
    return any((s.get("outcomeType") in ("Over", "Under")) for s in selections)


def load_existing_units():
    """Existing dk.json -> {market name: {market, event, selections}}."""
    units = {}
    if not os.path.exists(OUT_PATH):
        return units, {}, {}
    try:
        old = json.load(open(OUT_PATH))
    except Exception:
        return units, {}, {}
    sels_by_mid = {}
    for s in old.get("selections", []):
        sels_by_mid.setdefault(s.get("marketId"), []).append(s)
    events_by_id = {e.get("id"): e for e in old.get("events", [])}
    sports = {s.get("id"): s for s in old.get("sports", [])}
    leagues = {l.get("id"): l for l in old.get("leagues", [])}
    for m in old.get("markets", []):
        name = m.get("name")
        if not isinstance(name, str):
            continue
        units[name] = {
            "market": m,
            "event": events_by_id.get(m.get("eventId")),
            "selections": sels_by_mid.get(m.get("id"), []),
        }
    return units, sports, leagues


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])

    units, sports, leagues = load_existing_units()
    existing_names = set(units)

    kept_hosts, dropped, market_responses = set(), 0, 0
    outrights = {}            # name -> selection count (reported, not written)
    captured_ou = set()       # OU market names seen in THIS bundle

    for c in captures:
        url = c.get("url", "")
        if blocked(url):
            dropped += 1
            continue
        if MARKET_PATH not in url:
            continue
        body = c.get("body")
        if not isinstance(body, dict):
            continue
        kept_hosts.add(host_of(url))
        market_responses += 1

        for s in body.get("sports", []):
            sports[s.get("id")] = s
        for l in body.get("leagues", []):
            leagues[l.get("id")] = l

        sels_by_mid = {}
        for s in body.get("selections", []):
            sels_by_mid.setdefault(s.get("marketId"), []).append(s)
        events_by_id = {e.get("id"): e for e in body.get("events", [])}

        for m in body.get("markets", []):
            name = (m.get("name") or "").strip()
            if not name:
                continue
            sels = sels_by_mid.get(m.get("id"), [])
            if not is_ou(sels):
                outrights[name] = len(sels)
                continue
            captured_ou.add(name)
            # newest capture wins on conflict; carry its event + selections.
            units[name] = {
                "market": m,
                "event": events_by_id.get(m.get("eventId")),
                "selections": sels,
            }

    # Rebuild the flat native-shape lists from the merged units.
    markets, selections, events_by_id = [], [], {}
    for name in sorted(units):
        u = units[name]
        markets.append(u["market"])
        selections.extend(u["selections"])
        ev = u.get("event")
        if isinstance(ev, dict) and ev.get("id"):
            events_by_id[ev["id"]] = ev

    out = {
        "sports": list(sports.values()),
        "leagues": list(leagues.values()),
        "events": list(events_by_id.values()),
        "markets": markets,
        "selections": selections,
        "subscriptionPartials": {},
    }

    updated = len(captured_ou & existing_names)
    added = len(captured_ou - existing_names)

    print("Parsed %d captures (%d market responses, dropped %d blocked: %s)" %
          (len(captures), market_responses, dropped, ", ".join(BLOCK)))
    print("Source hosts:", ", ".join(sorted(h for h in kept_hosts if h)) or "—")
    print()
    print("Over/Under player-prop markets")
    print("  existing : %d" % len(existing_names))
    print("  in bundle: %d  (updated %d, added %d)" %
          (len(captured_ou), updated, added))
    print("  total    : %d markets, %d selections" % (len(markets), len(selections)))

    if not captured_ou:
        print("\nNo OU markets in bundle — dk.json left unchanged.")
        return

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    if outrights:
        print("\nOutright/award markets present but NOT written (no Over/Under view yet):")
        for n in sorted(outrights):
            print("  - %s (%d selections)" % (n, outrights[n]))

    print("\nWrote data/dk.json")


if __name__ == "__main__":
    main()
