"""The rules of the Survivor pool. Pure: no I/O, no network, no environment,
stdlib only.

The whole game is four sentences:

  * Every week you pick ONE team to win its game OUTRIGHT. No spread -- the
    line that makes Pick 'Em interesting is not part of this game at all, which
    is why a game with no frozen line is still perfectly pickable here.
  * A team may be used ONCE per season. Spending Kansas City in week 2 is the
    real cost of a week 2 pick, and it is why this is a season-long game rather
    than eighteen independent coin flips.
  * Your team loses and you are OUT. A tie counts as a loss, which is the
    default the big contests run (Circa's rules say so in as many words) and the
    only reading under which "survive" means what it says.
  * Miss a week and you are OUT. Once every game of a week has kicked off there
    is no pick left to make, so an entry with nothing down that week is done.

WHY ELIMINATION IS DERIVED AND NEVER STORED

There is no `eliminated` column and there must not be one. An entry's fate is a
function of its picks and the scores, both of which already live in the
database, and a stored verdict is a second copy of an answer that can go stale:
a game re-graded after a scoring correction would leave a player marked dead
with a winning pick on the board, and nothing would ever notice. walk_entry()
replays the season from the picks every time it is asked, so the standings are
always a statement about the current scores rather than about whatever a job
believed last Tuesday.

It also costs nothing. An entry is at most eighteen rows and the walk is a
single pass over them.

WHERE AN ENTRY STARTS

At its first pick. There is no sign-up step and no roster, so "in the pool" can
only mean "has picked", and a player who joins in week 4 is not retroactively
eliminated for the three weeks before they had an account. From that first pick
onwards every week counts, missed weeks included.

Imported by api/survivor.py and api/survivor-standings.py, which is the point:
the walk that decides who is still alive is written once and both endpoints
spend it.
"""

# What a single week did to an entry. Ordered here the way they are ordered in
# the walk, which is also the order of increasing bad news.
WIN, LOSS, TIE, PENDING, NONE, VOID = (
    "win", "loss", "tie", "pending", "none", "void")

# Why an entry is out. `nopick` is not a lesser death than `loss` -- both end
# the season -- but a standings row that just says "out" leaves the player
# wondering whether the site lost their pick.
OUT_REASONS = ("loss", "tie", "nopick")

ALIVE, OUT = "alive", "out"


def winner(game):
    """Who won one game outright: the winning abbreviation, 'tie', or None.

    None means "no verdict yet", and covers a game that has not finished as
    well as one that finished without a score reaching the board. It is NOT a
    tie: a tie is a real outcome that a real final score produced, and the two
    have opposite consequences for the entry riding on it.

    Note what is deliberately absent: `spread_home` and `result`. Those are the
    Pick 'Em's answer -- the ATS verdict against the frozen line -- and a game
    that never got a line is left ungraded there (see grade_season() in
    scripts/pickem_capture.py, which still records the score). Survivor reads
    the score itself, so such a game is on this board like any other.
    """
    away, home = game.get("away_score"), game.get("home_score")
    if away is None or home is None:
        return None
    if game.get("status") != "final":
        return None
    if int(home) > int(away):
        return game.get("home")
    if int(away) > int(home):
        return game.get("away")
    return "tie"


def outcome(pick_team, game):
    """What one week's pick did to the entry: WIN, LOSS, TIE or PENDING."""
    result = winner(game)
    if result is None:
        return PENDING
    if result == "tie":
        return TIE
    return WIN if pick_team == result else LOSS


def closed_weeks(games):
    """The weeks with no pick left to make: every game in them has kicked off.

    This is the trigger for a missed-week elimination, and it is the last
    kickoff rather than the last final whistle on purpose. The moment the last
    game of a week starts, an entry with nothing down cannot put anything down,
    and waiting three more hours to say so would only mean the standings
    disagreed with the pick page about whether the week was over.
    """
    by_week, out = {}, set()
    for game in games:
        by_week.setdefault(game["week"], []).append(game)
    for week, slate in by_week.items():
        if slate and all(g.get("locked") for g in slate):
            out.add(week)
    return out


def walk_entry(picks, games_by_id, board_weeks, shut):
    """Replay one entry's season. -> a dict describing where it stands.

    `picks`       {week: {"game_id": str, "team": "GB"}} -- one pick per week.
                  `team` and `game_id` may both be None, meaning "this entry
                  picked and you may not see what": a pick whose game has not
                  kicked off, in another player's row. It ends the walk exactly
                  where a real unreadable pick would.
    `games_by_id` game_id -> game dict, as api/_pickem/store.py shapes them.
    `board_weeks` every week the board knows about, ascending. Weeks the season
                  has not reached are simply not in it, so the walk stops at the
                  end of what has been played rather than at week 18.
    `shut`        the weeks from closed_weeks(): no pick left to make in them.

    -> {
         status:     'alive' | 'out'
         out_week:   the week it ended, or None
         out_reason: 'loss' | 'tie' | 'nopick', or None
         entered:    the week of the first pick, or None
         survived:   how many weeks it has actually won
         weeks:      {week: {team, game_id, outcome}}
         teams:      the abbreviations spent, in week order
       }

    THE WALK STOPS AT THE FIRST THING IT CANNOT SEE PAST

    A pending game ends the walk. Not because later weeks could not be graded --
    they might well be -- but because an entry's fate is a chain, and reporting
    week 6 as survived while week 5 is still being played would be answering a
    question that has not been asked yet. The same goes for a week with no pick
    that is still open: it is not yet a missed week, and nothing after it can
    matter until it is one.
    """
    state = {
        "status": ALIVE,
        "out_week": None,
        "out_reason": None,
        "entered": min(picks) if picks else None,
        "survived": 0,
        "weeks": {},
        "teams": [],
    }
    if not picks:
        return state

    for week in board_weeks:
        if week < state["entered"]:
            continue
        pick = picks.get(week)

        if pick is None:
            if week in shut:
                state["status"] = OUT
                state["out_week"] = week
                state["out_reason"] = "nopick"
                state["weeks"][week] = {"team": None, "game_id": None,
                                        "outcome": NONE}
            break

        game = games_by_id.get(pick["game_id"])
        verdict = outcome(pick["team"], game) if game else PENDING
        state["weeks"][week] = {"team": pick["team"],
                                "game_id": pick["game_id"],
                                "outcome": verdict}
        # A pick the caller was allowed to know exists but not to read carries a
        # null team (api/survivor-standings.py builds it that way). It counts as
        # a pick -- the week is not a missed one -- and it necessarily grades
        # PENDING, since a pick is unreadable only while its game is unstarted.
        # It is not a spent team, though: the spent strip must never grow an
        # entry nobody is allowed to name.
        if pick["team"]:
            state["teams"].append(pick["team"])

        if verdict == WIN:
            state["survived"] += 1
            continue
        if verdict == PENDING:
            break
        state["status"] = OUT
        state["out_week"] = week
        state["out_reason"] = TIE if verdict == TIE else "loss"
        break

    # Picks the walk never reached: weeks after an elimination, or after the
    # game it stopped on. They are shown rather than hidden -- somebody did make
    # them -- but marked void so nothing reads them as live.
    for week, pick in sorted(picks.items()):
        if week not in state["weeks"]:
            state["weeks"][week] = {"team": pick["team"],
                                    "game_id": pick["game_id"],
                                    "outcome": VOID}
            if pick["team"] and pick["team"] not in state["teams"]:
                state["teams"].append(pick["team"])
    return state


def rank_rows(rows):
    """Sort standings rows and stamp `rank` on each, in place.

    Alive above out, unconditionally: in survivor there is nothing an eliminated
    entry can do that beats being still in it, and an entry knocked out in week
    12 having won eleven does not outrank one that is alive in week 3. Within
    each group it is weeks survived, then username so the order is stable rather
    than whatever the database returned.

    Competition-style ranking, the same as api/_pickem/scoring.rank_rows: two
    entries on the same footing are both 1 and the next is 3.
    """
    def key(row):
        return (0 if row["status"] == ALIVE else 1,
                -row["survived"],
                (row.get("username") or "").lower())

    rows.sort(key=key)
    for i, row in enumerate(rows):
        prev = rows[i - 1] if i else None
        tied = prev is not None and prev["status"] == row["status"] \
            and prev["survived"] == row["survived"]
        row["rank"] = prev["rank"] if tied else i + 1
    return rows


def validate_pick(game_id, team, games_by_id, used_teams, my_week_pick):
    """Check one submitted pick. -> (clean, error_message).

    `games_by_id` is every game in the week being picked, `used_teams` maps an
    abbreviation to the week it was spent in (this entry's own picks, all
    seasons of it aside), and `my_week_pick` is what is currently stored for
    this week, if anything.

    Ordered so the message names the first thing actually wrong. Every one of
    these is checked again by the database or by the caller -- the unique index
    on (user_id, season, team) is what makes the reuse rule true -- but a
    constraint violation is not a sentence anybody wants to read.
    """
    game_id = str(game_id or "").strip()
    if not game_id:
        return None, "game_id is required"
    game = games_by_id.get(game_id)
    if game is None:
        return None, f"game {game_id} is not on the board for this week"

    team = str(team or "").strip().upper()
    if team not in (game["away"], game["home"]):
        return None, (f"{team or '(blank)'} is not playing in game {game_id} "
                      f"({game['away']} at {game['home']})")

    if game.get("locked"):
        return None, (f"{game['away']} at {game['home']} has already kicked off")

    # Re-picking the team already down for this week is a no-op, not a reuse.
    spent = used_teams.get(team)
    if spent is not None and not (my_week_pick and my_week_pick.get("team") == team):
        return None, (f"you already used {team} in week {spent} -- a team can "
                      f"only be picked once a season")

    return {"game_id": game_id, "team": team}, None
