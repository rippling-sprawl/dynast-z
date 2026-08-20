#!/usr/bin/env python3
"""
Build the regression worksheet behind each team card on /football/bakers-buns:
data/nfl_regression_{cap_season}.json.

Why this exists
---------------
The Projections table scores a team on what it *is* — the eye test, the line,
the schedule, the rest. This file answers the other question: which parts of
last season were the team, and which parts were the bounce of the ball. Five
numbers, chosen because each is either famously sticky or famously not:

    Havoc rate         sticky.  A defense that pressured the quarterback on a
                                fifth of his dropbacks will do it again. If the
                                takeaways did not follow, they are coming.
    Turnover margin    noisy.   Fumble recoveries are close to a coin flip and
                                interception rate barely correlates year to
                                year. A big margin in either direction is the
                                single loudest regression signal there is.
    One-score record   noisy.   Over a season, teams converge on .500 in games
                                decided by a possession. 11-2 is not a skill.
    4th-down rate      noisy.   Twenty-odd attempts a year. Nothing about a
                                season's worth of them predicts the next.
    Dead cap           real.    Not regression at all — the constraint the other
                                four get spent under. Carried here because it is
                                the answer to "so can they fix it?"

Sources
-------
On-field numbers come from nflverse's play-by-play release, which is the only
free feed with a real play table: pressure needs qb_hit, and no box-score API
carries it. One gzipped CSV per season, ~19 MB, parsed streaming.

    https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz

Dead money is scraped from Over The Cap's cap-space page, which publishes three
league years as three tables under one URL; the first is the current one.

    https://overthecap.com/salary-cap-space

Definitions, and why they are what they are
-------------------------------------------
Regular season only, throughout. The playoff field is not the league, so a
seven-game postseason sample would make the twelve teams that reached it
incomparable with the twenty that did not.

*Pressure* is a dropback on which the quarterback was sacked or hit. It is a
floor, not the PFF number: hurries are charted by hand and are in no free feed,
so a pressure here is one that put a defender's hands on the passer. The rate
is per dropback (scrambles included, since a scramble is a dropback that broke
down), which is the denominator that keeps a team that faces 700 dropbacks
comparable with one that faces 550.

*Turnovers* are counted from scrimmage — interceptions and fumbles lost on run
or pass plays. Muffed punts and kick fumbles are left out on purpose: on a
kicking play nflverse's posteam is the kicking team, so the muff belongs to the
side listed as the defense, and attributing it correctly costs more than the
one or two plays a year it moves.

*One-score* is a final margin of eight points or fewer — a touchdown and the
two-point conversion, the largest deficit that is still one possession.

*4th down* counts only the plays a team chose to run: pass and run attempts on
fourth down. Punts and field goals are not conversion attempts, and a kneel is
not one either.

Usage:
    python3 scripts/fetch_nfl_regression.py                  # last season + this cap year
    python3 scripts/fetch_nfl_regression.py --season 2024 --cap-season 2025
    python3 scripts/fetch_nfl_regression.py --keep-pbp       # leave the CSV in /cache
"""

import argparse
import csv
import gzip
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.csv.gz")
OTC_URL = "https://overthecap.com/salary-cap-space"

# nflverse abbreviations are not this site's for two clubs. Everything else
# already agrees, and the schedule/logo/projection files all key on ours.
PBP_ABBR = {"LA": "LAR", "WAS": "WSH"}

# Over The Cap names teams by their nickname alone. Nothing else on the page
# identifies a row, so the nickname is the join key.
OTC_TEAM = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF",
    "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN", "Browns": "CLE",
    "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAX", "Chiefs": "KC",
    "Chargers": "LAC", "Rams": "LAR", "Raiders": "LV", "Dolphins": "MIA",
    "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "Seahawks": "SEA",
    "49ers": "SF", "Buccaneers": "TB", "Titans": "TEN", "Commanders": "WSH",
}

EXPECTED_TEAMS = 32
EXPECTED_GAMES = 272


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def curl_bytes(url, browser_ua=False):
    """Raw body, via curl. -L because both sources redirect: the nflverse asset
    to a signed S3 URL, and OTC between www and apex. Over The Cap serves an
    interstitial to curl's default UA, so that one asks for a browser string;
    GitHub releases do not care either way."""
    cmd = ["curl", "-sL", "--max-time", "300"]
    if browser_ua:
        cmd += ["-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"]
    result = subprocess.run(cmd + [url], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr.decode()[:200]}")
    if not result.stdout:
        raise RuntimeError(f"empty response for {url}")
    return result.stdout


# ---------- play-by-play ----------

def load_pbp(season, cache_path):
    """The season's CSV, cached. A finished season's play-by-play never changes,
    so a second run in the same afternoon should not pull 19 MB again."""
    if os.path.exists(cache_path):
        print(f"  using cached {os.path.basename(cache_path)}")
        return open(cache_path, "rb").read()
    url = PBP_URL.format(season=season)
    print(f"  downloading {url}")
    blob = curl_bytes(url)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(blob)
    print(f"  {len(blob) / 1024 / 1024:.1f} MB")
    return blob


def flag(row, key):
    """nflverse writes its booleans as 0/1, but a play that cannot have the
    property at all (a kickoff, for a fourth-down flag) gets NA. Anything that
    is not exactly "1" is a no."""
    return row.get(key) == "1"


def tally(blob):
    """One pass over the season. Every counter is per team, and a play feeds
    both sides of it: the offense's giveaway is the defense's takeaway, so they
    are incremented together and the league's margins sum to zero by
    construction."""
    stats = {}
    games = {}

    def team(t):
        t = PBP_ABBR.get(t, t)
        if t not in stats:
            stats[t] = dict(dropbacks=0, sacks=0, pressures=0, takeaways=0,
                            giveaways=0, fourth_conv=0, fourth_att=0)
        return stats[t]

    reader = csv.DictReader(io.TextIOWrapper(gzip.open(io.BytesIO(blob)), encoding="utf-8"))
    plays = 0
    for row in reader:
        if row["season_type"] != "REG":
            continue
        plays += 1

        # The final score rides on every row of the game; the first one that
        # carries it settles the game and the rest are ignored.
        gid = row["game_id"]
        if gid not in games and row["home_score"] and row["away_score"]:
            games[gid] = (PBP_ABBR.get(row["home_team"], row["home_team"]),
                          PBP_ABBR.get(row["away_team"], row["away_team"]),
                          int(float(row["home_score"])), int(float(row["away_score"])))

        # Kickoffs, timeouts and the end-of-quarter markers have no possession.
        if not row["posteam"] or not row["defteam"]:
            continue
        # A penalty play (no_play) is a play that did not happen; a punt, kick
        # or field goal is nobody's dropback and nobody's conversion attempt.
        if row["play_type"] not in ("pass", "run"):
            continue

        off, dfn = team(row["posteam"]), team(row["defteam"])

        if flag(row, "qb_dropback"):
            dfn["dropbacks"] += 1
            if flag(row, "sack"):
                dfn["sacks"] += 1
            # Counted as one pressure, not two: a sack is already a hit, and
            # nflverse flags both on the same play.
            if flag(row, "sack") or flag(row, "qb_hit"):
                dfn["pressures"] += 1

        turnovers = flag(row, "interception") + flag(row, "fumble_lost")
        off["giveaways"] += turnovers
        dfn["takeaways"] += turnovers

        if flag(row, "fourth_down_converted"):
            off["fourth_conv"] += 1
            off["fourth_att"] += 1
        elif flag(row, "fourth_down_failed"):
            off["fourth_att"] += 1

    # One-score record: a possession game is one decided by 8 or fewer, the
    # largest margin a touchdown and a two-point conversion can erase.
    for t in stats.values():
        t["os_w"] = t["os_l"] = t["os_t"] = 0
    for home, away, hs, aws in games.values():
        if abs(hs - aws) > 8:
            continue
        if hs > aws:
            team(home)["os_w"] += 1
            team(away)["os_l"] += 1
        elif aws > hs:
            team(away)["os_w"] += 1
            team(home)["os_l"] += 1
        else:
            team(home)["os_t"] += 1
            team(away)["os_t"] += 1

    return stats, games, plays


# ---------- Over The Cap ----------

def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def money(text):
    """"$36,520,240" and "-$1,204,988" both to an int. OTC writes a negative cap
    space with the sign outside the dollar sign."""
    text = text.replace(",", "").replace("$", "").strip()
    if not text or text in ("-", "—"):
        return None
    return int(float(text))


def parse_otc(html, cap_season):
    """The page ships three league years as three tables — 2026, 2027, 2028 in
    the tab strip — so the season is picked by position in that strip rather
    than by reading a year off a row, because the rows carry none."""
    tabs = re.findall(r'href="#season-(\d{4})"', html)
    if str(cap_season) not in tabs:
        raise RuntimeError(f"Over The Cap has no {cap_season} table (found {tabs})")
    idx = tabs.index(str(cap_season))

    tables = re.findall(r"<table.*?</table>", html, re.S)
    if len(tables) <= idx:
        raise RuntimeError(f"expected {idx + 1} tables on the page, found {len(tables)}")

    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tables[idx], re.S):
        cells = [strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 6 or cells[0] not in OTC_TEAM:
            continue
        out[OTC_TEAM[cells[0]]] = {
            "dead": money(cells[5]),
            "capSpace": money(cells[1]),
            "spending": money(cells[4]),
        }
    return out


# ---------- assembly ----------

def rank_by(rows, key, high_is_first=True):
    """A 1..32 rank on one field. Ties share the better number and the ones
    behind them skip — two teams at -2 are both 18th and the next is 20th, which
    is how a standings table reads and how a reader will read "18th" here.

    Which direction counts as first is the caller's call — for dead money the
    good end is the low one — but the rank itself is always "1 is the front of
    this list", and the page decides what the front means."""
    ordered = sorted((v for v in (key(r) for r in rows.values()) if v is not None),
                     reverse=high_is_first)
    return {v: ordered.index(v) + 1 for v in set(ordered)}


def build(stats, caps):
    teams = {}
    for abbr, s in stats.items():
        db = s["dropbacks"] or 1
        att = s["fourth_att"] or 1
        cap = caps.get(abbr, {})
        teams[abbr] = {
            "havoc": {
                "pressureRate": round(100 * s["pressures"] / db, 1),
                "sackRate": round(100 * s["sacks"] / db, 1),
                "pressures": s["pressures"],
                "sacks": s["sacks"],
                "dropbacks": s["dropbacks"],
            },
            "turnovers": {
                "diff": s["takeaways"] - s["giveaways"],
                "takeaways": s["takeaways"],
                "giveaways": s["giveaways"],
            },
            "oneScore": {
                "w": s["os_w"], "l": s["os_l"], "t": s["os_t"],
                "games": s["os_w"] + s["os_l"] + s["os_t"],
                "pct": round((s["os_w"] + 0.5 * s["os_t"]) /
                             max(1, s["os_w"] + s["os_l"] + s["os_t"]), 3),
            },
            "fourthDown": {
                "pct": round(100 * s["fourth_conv"] / att, 1),
                "conv": s["fourth_conv"],
                "att": s["fourth_att"],
            },
            "deadCap": {
                "amount": cap.get("dead"),
                "capSpace": cap.get("capSpace"),
                "spending": cap.get("spending"),
            },
        }

    # Ranked after the fact rather than inside the loop: a rank is a statement
    # about the field, so it cannot be computed until the whole field is built.
    ranks = [
        ("havoc", "pressureRate", True),
        ("turnovers", "diff", True),
        ("oneScore", "pct", True),
        ("fourthDown", "pct", True),
        ("deadCap", "amount", False),   # least dead money is rank 1
    ]
    for block, field, high_first in ranks:
        table = rank_by(teams, lambda t, b=block, f=field: t[b][f], high_first)
        for t in teams.values():
            v = t[block][field]
            t[block]["rank"] = table.get(v)

    return teams


def league_means(teams):
    """The middle of each column, so a card can say "against a league average of
    …" without every card recomputing it from 32 objects.

    Dead money gets a median as well, and the median is what the page shows.
    The on-field columns are near enough symmetric for a mean to describe them —
    pressure rate runs about 9% to 22% around a middle of 15 — but dead money is
    a long right tail with a handful of teams eating a franchise quarterback,
    and one of those drags the mean about $9M above the team that is actually
    31st. A card comparing a team against a number no team is near would be
    worse than showing nothing."""
    def col(f):
        return sorted(v for v in (f(t) for t in teams.values()) if v is not None)

    def mean(f):
        vals = col(f)
        return sum(vals) / len(vals) if vals else None

    def median(f):
        vals = col(f)
        if not vals:
            return None
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2

    return {
        "pressureRate": round(mean(lambda t: t["havoc"]["pressureRate"]), 1),
        "sackRate": round(mean(lambda t: t["havoc"]["sackRate"]), 1),
        "fourthDownPct": round(mean(lambda t: t["fourthDown"]["pct"]), 1),
        "oneScoreGames": round(mean(lambda t: t["oneScore"]["games"]), 1),
        "deadCap": int(mean(lambda t: t["deadCap"]["amount"])),
        "deadCapMedian": int(median(lambda t: t["deadCap"]["amount"])),
    }


def verify(teams, games, stats):
    ok = True
    if len(teams) != EXPECTED_TEAMS:
        print(f"! {len(teams)} teams, expected {EXPECTED_TEAMS}", file=sys.stderr)
        ok = False
    if len(games) != EXPECTED_GAMES:
        print(f"! {len(games)} scored games, expected {EXPECTED_GAMES}", file=sys.stderr)
        ok = False

    # Every giveaway is somebody's takeaway, so the league's margins must cancel.
    # If they do not, a play was attributed to one side and not the other.
    margin = sum(t["turnovers"]["diff"] for t in teams.values())
    if margin != 0:
        print(f"! turnover margins sum to {margin}, not 0", file=sys.stderr)
        ok = False

    missing = sorted(a for a, t in teams.items() if t["deadCap"]["amount"] is None)
    if missing:
        print(f"! no dead money for {', '.join(missing)}", file=sys.stderr)
        ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    now = datetime.now(timezone.utc)
    # A season is named for the year it starts, so the last *finished* one is
    # this year only once we are past the February that ended it.
    last_done = now.year - 1 if now.month >= 3 else now.year - 2
    ap.add_argument("--season", type=int, default=last_done,
                    help="finished season the on-field stats come from")
    ap.add_argument("--cap-season", type=int, default=last_done + 1,
                    help="league year the dead money comes from")
    ap.add_argument("--keep-pbp", action="store_true",
                    help="leave the play-by-play CSV in /cache for the next run")
    args = ap.parse_args()

    print(f"Play-by-play: {args.season} regular season (nflverse)")
    cache_path = repo_path("cache", f"pbp_{args.season}.csv.gz")
    blob = load_pbp(args.season, cache_path)
    stats, games, plays = tally(blob)
    print(f"  {plays} plays, {len(games)} games, {len(stats)} teams")

    print(f"Dead money: {args.cap_season} league year (Over The Cap)")
    caps = parse_otc(curl_bytes(OTC_URL, browser_ua=True).decode("utf-8", "replace"),
                     args.cap_season)
    print(f"  {len(caps)} teams")

    teams = build(stats, caps)
    if not verify(teams, games, stats):
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    out = {
        "statsSeason": args.season,
        "capSeason": args.cap_season,
        "note": (f"Regression worksheet for the {args.cap_season} projections. "
                 f"On-field numbers are {args.season} regular season only. "
                 "A pressure is a dropback ending in a sack or a QB hit — hurries "
                 "are hand-charted and in no free feed, so this is a floor. "
                 "Turnovers are from scrimmage. A one-score game is decided by 8 "
                 "or fewer. Fourth down counts pass and run attempts only. Rank 1 "
                 "is the highest value in every block except deadCap, where it is "
                 "the lowest."),
        "sources": {
            "onField": PBP_URL.format(season=args.season),
            "deadCap": OTC_URL,
        },
        "league": league_means(teams),
        "teams": dict(sorted(teams.items())),
    }

    out_path = repo_path("data", f"nfl_regression_{args.cap_season}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"\nWrote {len(teams)} teams to {os.path.abspath(out_path)} "
          f"({os.path.getsize(out_path) / 1024:.0f} KB)")

    meta_path = repo_path("data", f"nfl_regression_{args.cap_season}_meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "sources": out["sources"],
            "stats_season": args.season,
            "cap_season": args.cap_season,
            "team_count": len(teams),
            "game_count": len(games),
            "play_count": plays,
            "league": out["league"],
            "size_bytes": os.path.getsize(out_path),
            "fetched_at": now.isoformat(timespec="seconds"),
            "fetched_ts": int(time.time()),
        }, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")

    if not args.keep_pbp and os.path.exists(cache_path):
        os.remove(cache_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
