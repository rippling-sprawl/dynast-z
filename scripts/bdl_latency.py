#!/usr/bin/env python3
"""
Measure how far behind a live NFL game balldontlie actually runs.

Why
---
docs/research/nfl-live-data-apis.md picked balldontlie on published terms and
then said, plainly, that the one thing it could not establish was latency:

    "balldontlie's actual latency was never measured — it needs a key. Its
     48-hour GOAT trial would settle it against a live slate. Measure against
     the three thresholds (25s score/period, 2 min player stats, 3-5 min team
     stats) before committing. This is the single largest remaining unknown."

This script settles it. It is the reason to spend the trial on a day with a game
on it rather than on a quiet afternoon.

Two different numbers, routinely conflated
------------------------------------------
REQUEST latency is how long a GET takes. bdl_common records it on every call for
free, and `--summary` prints it. It is not the interesting one.

PROPAGATION lag is how long after something happens on the field before the API
will tell you about it. That is the number that decides whether a live score is
worth showing. It can only be measured against a running game, and it needs a
reference clock for when the play actually happened — balldontlie supplies one
itself, as `plays[].wallclock`. This is the same method that produced ESPN's
measured 26-33s in the research doc, so the two are comparable.

Four lags are tracked, each against the play that caused it:

    play          a new play appears in /plays
    score         /games changes its score          threshold  25s
    period        /games or /plays enters a new quarter        25s
    player_stat   a player's yardage moves in /stats          120s
    team_stat     a team's total_yards moves in /team_stats   240s

Everything is cassetted, so the whole game is replayable afterwards: a full live
NFL game recorded second by second is the best regression fixture this codebase
could have, and it costs one evening of a trial to get.

/plays and /stats are GOAT and ALL-STAR respectively. Without them there is no
reference clock and no stat lag, so on a free key this degrades to recording
score changes with no lag attached — it says so rather than pretending.

Usage:
    python3 scripts/bdl_latency.py --example week1 --until-final
    python3 scripts/bdl_latency.py --game-id 1392216 --max-minutes 240
    python3 scripts/bdl_latency.py --game-id 1392216 --once     # single probe
    python3 scripts/bdl_latency.py --summary                    # request latency only
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bdl_common as bdl  # noqa: E402
from fetch_bdl_game import EXAMPLES, resolve_game  # noqa: E402

# Seconds. From the research doc's thresholds; a lag under these is fit for the
# purpose the feed was chosen for.
THRESHOLDS = {"score": 25, "period": 25, "play": 25,
              "player_stat": 120, "team_stat": 240}

# Which per-player fields to watch. Yardage moves on most plays and is the
# earliest signal that a stat line has been updated at all.
WATCH_PLAYER = ("passing_yards", "rushing_yards", "receiving_yards",
                "total_tackles", "receptions")
WATCH_TEAM = ("total_yards", "total_offensive_plays", "possession_time_seconds")


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(s):
    """balldontlie's wallclock format is undocumented. Accept the ISO shapes and
    return None rather than guessing at anything else -- a misparsed reference
    clock would produce confident, wrong lag numbers, which is worse than a gap."""
    if not s:
        return None
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Poller:
    def __init__(self, game, mode, out_path):
        self.game = game
        self.gid = game["id"]
        self.home_id = game["home_team"]["id"]
        self.away_id = game["visitor_team"]["id"]
        self.mode = mode
        self.out_path = out_path

        self.observations = []
        self.polls = []
        self.unavailable = {}
        self.seen_plays = set()
        self.last_play_by_player = {}     # player_id -> (wallclock, play text)
        self.last_play_any = None         # (wallclock, text)
        self.prev_score = None
        self.prev_period = None
        self.prev_player = {}             # (pid, field) -> value
        self.prev_team = {}               # (tid, field) -> value
        self.final = False

    # -- helpers ---------------------------------------------------------
    def note(self, kind, wallclock, detail, seen_at=None):
        seen = seen_at or now_utc()
        lag = None
        if wallclock is not None:
            lag = round((seen - wallclock).total_seconds(), 1)
        self.observations.append({
            "kind": kind,
            "wallclock": wallclock.isoformat(timespec="seconds") if wallclock else None,
            "first_seen": seen.isoformat(timespec="seconds"),
            "lag_s": lag,
            "detail": detail,
        })
        thr = THRESHOLDS.get(kind)
        flag = ""
        if lag is not None and thr:
            flag = "  OK" if lag <= thr else f"  OVER {thr}s"
        print(f"    {kind:<12} lag={lag if lag is not None else '?':>7}s  {detail}{flag}")

    def call(self, path, params, paginated=False):
        try:
            if paginated:
                rows = list(bdl.paginate(path, params, mode=self.mode, quiet=True))
            else:
                payload, meta = bdl.bdl_get(path, params, mode=self.mode, quiet=True)
                rows = payload.get("data") or []
            self.polls.append({"t": now_utc().isoformat(timespec="seconds"),
                               "path": path, "rows": len(rows), "http": 200})
            return rows
        except bdl.BdlError as e:
            if path not in self.unavailable:
                self.unavailable[path] = {"error": type(e).__name__,
                                          "detail": str(e).splitlines()[0],
                                          "needs_tier": bdl.min_tier(path)}
                print(f"  {path}: {type(e).__name__} "
                      f"(needs {bdl.min_tier(path).upper()}) — skipping from here on")
            return None

    # -- one pass over each feed ----------------------------------------
    def poll_plays(self):
        rows = self.call("/plays", {"game_id": self.gid}, paginated=True)
        if rows is None:
            return
        for p in rows:
            pid = p.get("id")
            if pid in self.seen_plays:
                continue
            self.seen_plays.add(pid)
            wc = parse_ts(p.get("wallclock"))
            if wc:
                self.last_play_any = (wc, p.get("short_text") or p.get("text") or "")
                for part in p.get("participants") or []:
                    if part.get("player_id"):
                        self.last_play_by_player[part["player_id"]] = (
                            wc, p.get("short_text") or "")
            # Only the first pass over a game already in progress would
            # otherwise emit hundreds of bogus "new play" observations.
            if not self.warm:
                continue
            text = (p.get("short_text") or p.get("text") or "")[:70]
            self.note("play", wc, f"Q{p.get('period')} {p.get('clock_display')} {text}")
            if p.get("scoring_play"):
                self.note("score", wc,
                          f"SCORING {p.get('away_score')}-{p.get('home_score')} {text}")
            per = p.get("period")
            if per is not None and (self.prev_period is None or per > self.prev_period):
                if self.prev_period is not None:
                    self.note("period", wc, f"entered Q{per}")
                self.prev_period = per

    def poll_game(self):
        rows = self.call("/games", {"game_ids[]": [self.gid]})
        if not rows:
            # /games has no single-id filter documented under that name on every
            # deployment; fall back to the by-id route.
            try:
                payload, _ = bdl.bdl_get(f"/games/{self.gid}", mode=self.mode, quiet=True)
                rows = [payload.get("data") or payload]
            except bdl.BdlError:
                return
        g = rows[0]
        if (g.get("status_state") or "").lower() == "final":
            self.final = True
        score = (g.get("visitor_team_score"), g.get("home_team_score"))
        if self.prev_score is not None and score != self.prev_score and self.warm:
            wc = self.last_play_any[0] if self.last_play_any else None
            self.note("score", wc,
                      f"/games {self.prev_score[0]}-{self.prev_score[1]} -> "
                      f"{score[0]}-{score[1]}")
        self.prev_score = score

    def poll_stats(self):
        rows = self.call("/stats", {"game_ids[]": [self.gid]}, paginated=True)
        if rows is None:
            return
        for r in rows:
            pid = (r.get("player") or {}).get("id")
            if pid is None:
                continue
            for field in WATCH_PLAYER:
                v = r.get(field)
                if v in (None, 0):
                    continue
                key = (pid, field)
                if key in self.prev_player and v != self.prev_player[key] and self.warm:
                    wc = (self.last_play_by_player.get(pid) or (None, ""))[0]
                    name = " ".join(filter(None, [(r.get("player") or {}).get("first_name"),
                                                  (r.get("player") or {}).get("last_name")]))
                    self.note("player_stat", wc,
                              f"{name} {field} {self.prev_player[key]} -> {v}")
                self.prev_player[key] = v

    def poll_team_stats(self):
        # game_ids[] with brackets, not the bare form -- the bare one answers
        # 400 "game_ids must be an array". season_types[] is needed too: without
        # it /team_stats returns zero rows for a postseason game, so a January
        # run would silently measure no team-stat lag at all.
        rows = self.call("/team_stats",
                         {"game_ids[]": [self.gid],
                          "season_types[]": [3 if self.game.get("postseason") else 2]},
                         paginated=True)
        if rows is None:
            return
        for r in rows:
            tid = (r.get("team") or {}).get("id")
            if tid is None:
                continue
            for field in WATCH_TEAM:
                v = r.get(field)
                if v is None:
                    continue
                key = (tid, field)
                if key in self.prev_team and v != self.prev_team[key] and self.warm:
                    wc = self.last_play_any[0] if self.last_play_any else None
                    abbr = (r.get("team") or {}).get("abbreviation") or tid
                    self.note("team_stat", wc,
                              f"{abbr} {field} {self.prev_team[key]} -> {v}")
                self.prev_team[key] = v

    # -- the loop --------------------------------------------------------
    def run(self, fast_seconds, slow_seconds, max_minutes, until_final, once):
        # The first pass only seeds the baselines. Without this, every play and
        # every stat already on the record at start-up would be reported as
        # having just happened, with a lag of however long ago the game began.
        self.warm = False
        deadline = time.time() + max_minutes * 60
        last_slow = 0.0
        n = 0
        try:
            while True:
                n += 1
                stamp = now_utc().strftime("%H:%M:%S")
                print(f"  [{stamp}] poll {n}"
                      + ("  (baseline)" if not self.warm else ""))
                self.poll_game()
                self.poll_plays()
                if time.time() - last_slow >= slow_seconds:
                    self.poll_stats()
                    self.poll_team_stats()
                    last_slow = time.time()

                self.flush()
                self.warm = True

                if once:
                    break
                if until_final and self.final:
                    print("\n  game is final — stopping")
                    break
                if time.time() > deadline:
                    print(f"\n  --max-minutes {max_minutes} reached — stopping")
                    break
                time.sleep(fast_seconds)
        except KeyboardInterrupt:
            print("\n  interrupted — flushing what was captured")
        self.flush()

    # -- output ----------------------------------------------------------
    def summary(self):
        out = {}
        for kind in sorted({o["kind"] for o in self.observations}):
            lags = sorted(o["lag_s"] for o in self.observations
                          if o["kind"] == kind and o["lag_s"] is not None)
            if not lags:
                out[kind] = {"n": 0, "note": "no reference wallclock available"}
                continue
            thr = THRESHOLDS.get(kind)
            out[kind] = {"n": len(lags), "p50": bdl.percentile(lags, 50),
                         "p90": bdl.percentile(lags, 90), "max": lags[-1],
                         "threshold_s": thr,
                         "pass": (bdl.percentile(lags, 90) <= thr) if thr else None}
        out["request_latency_ms"] = bdl.latency_summary()
        return out

    def flush(self):
        """Rewritten in full on every pass. A three-hour game is one laptop sleep
        or one Ctrl-C away from losing everything, and the file is small."""
        doc = {
            "game_id": self.gid,
            "matchup": f"{self.game['visitor_team']['abbreviation']}@"
                       f"{self.game['home_team']['abbreviation']}",
            "kickoff": self.game.get("date"),
            "venue": self.game.get("venue"),
            "updated_at": now_utc().isoformat(timespec="seconds"),
            "final": self.final,
            "thresholds_s": THRESHOLDS,
            "unavailable": self.unavailable,
            "summary": self.summary(),
            "observations": self.observations,
            "polls": self.polls[-500:],
        }
        with open(self.out_path, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", choices=sorted(EXAMPLES))
    ap.add_argument("--game-id", type=int)
    ap.add_argument("--poll-seconds", type=int, default=10,
                    help="/games and /plays cadence (default 10)")
    ap.add_argument("--slow-seconds", type=int, default=60,
                    help="/stats and /team_stats cadence (default 60)")
    ap.add_argument("--max-minutes", type=int, default=300)
    ap.add_argument("--until-final", action="store_true",
                    help="stop as soon as the game goes final")
    ap.add_argument("--once", action="store_true",
                    help="one pass, no loop — useful for a dry rehearsal")
    ap.add_argument("--summary", action="store_true",
                    help="print request latency from the recorded index and exit")
    bdl.add_mode_args(ap)
    args = ap.parse_args()

    if args.summary:
        print(json.dumps(bdl.latency_summary(), indent=2))
        return 0
    if not args.example and not args.game_id:
        ap.error("give --example or --game-id (or --summary)")

    mode = bdl.resolve_mode(args)
    try:
        if args.game_id:
            payload, _ = bdl.bdl_get(f"/games/{args.game_id}", mode=mode)
            game = payload.get("data") or payload
        else:
            game = resolve_game(EXAMPLES[args.example], mode)
        if not game:
            return 1
    except bdl.BdlError as e:
        print(f"{e}", file=sys.stderr)
        return 1

    out_path = repo_path("cache", f"bdl_latency_{game['id']}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"Polling {game['visitor_team']['abbreviation']}@"
          f"{game['home_team']['abbreviation']} (game {game['id']}) "
          f"every {args.poll_seconds}s / {args.slow_seconds}s\n"
          f"  kickoff {game.get('date')}  status={game.get('status')!r}\n"
          f"  writing {os.path.abspath(out_path)}\n")

    p = Poller(game, mode, out_path)
    p.run(args.poll_seconds, args.slow_seconds, args.max_minutes,
          args.until_final, args.once)
    doc = p.flush()

    print("\nSummary")
    for kind, s in doc["summary"].items():
        if kind == "request_latency_ms":
            continue
        if s.get("n"):
            print(f"  {kind:<12} n={s['n']:<4} p50={s['p50']}s p90={s['p90']}s "
                  f"max={s['max']}s  threshold {s['threshold_s']}s  "
                  f"{'PASS' if s['pass'] else 'FAIL'}")
        else:
            print(f"  {kind:<12} {s.get('note', 'no observations')}")
    print(f"\n  request latency: "
          f"{json.dumps(doc['summary']['request_latency_ms'], sort_keys=True)}")
    if doc["unavailable"]:
        print(f"\n  {len(doc['unavailable'])} endpoints unavailable — "
              f"{', '.join(sorted(doc['unavailable']))}")
    print(f"\nWrote {os.path.abspath(out_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
