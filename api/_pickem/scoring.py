"""Grading and validation for the confidence Pick 'Em. Pure: no I/O, no
network, no environment, stdlib only.

The whole of the game's rules is in this file:

  * A pick is graded against the spread as it stood at the Tuesday 3:00am ET
    freeze, not against the outright winner.
  * A correct pick scores its confidence value. A wrong pick, a push and an
    ungraded game all score nothing.
  * Within one week a player's confidences are distinct integers in 1..N, where
    N is how many games the week has a line for. A full week therefore uses
    exactly 1..N. A partial week uses any k of those values -- picking three
    games and putting them on 16, 15 and 14 is legal, and so is 3, 2, 1.

    THE RANGE IS 1..N AND NOT 1..k, AND THAT IS FORCED

    A gapless 1..k reads more tidily, and it cannot survive per-game locking.
    Pick four games ranked 1-4, let the Thursday game holding 4 kick off, then
    drop a Sunday game holding 2: the remainder is {1, 3, 4}, which is not
    gapless, and the 4 belongs to a locked pick that must not be renumbered.
    There is no repair -- the two rules simply cannot both hold. Widening the
    range to 1..N dissolves the conflict rather than papering over it, and it
    costs nothing: a full week is still exactly 1..N, and picking every game
    still dominates (16 correct at 1..16 is 136; three correct at 14-16 is 45).

Imported by api/pickem.py, api/pickem-standings.py and
scripts/pickem_capture.py, which is the point: the capture job stores the
verdict grade() returns, and the endpoints spend it through points_for(). One
definition, three callers.
"""

# The three verdicts a graded game can carry, plus None for "not yet graded".
# Stored on pickem_games.result.
RESULTS = ("away", "home", "push")

# A hard ceiling on a submitted week, well above the 16 a real week has. This is
# a request-size guard rather than a rule -- rule 6 in validate_week_picks is
# what actually constrains the confidences.
MAX_PICKS = 20


def grade(spread_home, away_score, home_score):
    """The ATS verdict for one game: 'home', 'away', 'push', or None.

    `spread_home` is written from the home team's side, the way a book quotes
    it: -3.5 means the home team lays 3.5 and has to win by 4 to cover, +3.5
    means they get 3.5 and can lose by 3 and still cover. Adding it to the home
    margin therefore gives a number whose sign is the answer.

    None whenever any input is missing, which covers both an unplayed game and
    a game whose line never got frozen. A missing verdict is not a push -- a
    push is a real outcome that a real line produced.
    """
    if spread_home is None or away_score is None or home_score is None:
        return None
    adjusted = (float(home_score) - float(away_score)) + float(spread_home)
    if adjusted > 0:
        return "home"
    if adjusted < 0:
        return "away"
    return "push"


def winner_abbr(game):
    """The team abbreviation that covered, or None on a push/ungraded game."""
    result = game.get("result")
    if result == "home":
        return game.get("home")
    if result == "away":
        return game.get("away")
    return None


def points_for(pick_abbr, confidence, game):
    """What one pick is worth. 0 for wrong, for a push and for ungraded."""
    winner = winner_abbr(game)
    if winner is None:
        return 0
    return int(confidence) if pick_abbr == winner else 0


def score_pick(pick_abbr, confidence, game):
    """-> {points, correct}. `correct` is None while the game is ungraded,
    which is what lets a caller tell "wrong" apart from "not yet" -- the row
    renders differently and the standings count them differently.

    A push is `correct: False` rather than None: the game *is* graded, nobody
    got it, and counting it as pending would leave a finished week showing
    outstanding games forever.
    """
    winner = winner_abbr(game)
    if game.get("result") is None:
        return {"points": 0, "correct": None}
    if winner is None:                      # a push
        return {"points": 0, "correct": False}
    hit = pick_abbr == winner
    return {"points": int(confidence) if hit else 0, "correct": hit}


def score_set(picks, games_by_id):
    """Total one collection of picks. `picks` is an iterable of
    (game_id, pick_abbr, confidence); `games_by_id` maps game_id -> game dict.

    -> {points, correct, picked, pending}. `pending` is how many of those picks
    are still waiting on a verdict, which is what the pages print next to a
    total so a Sunday-afternoon leaderboard reads as provisional rather than
    final.

    A pick on a game the caller did not supply is skipped rather than raising:
    the standings read games and picks in two queries, and a game deleted
    between them should cost one row, not the request.
    """
    total = {"points": 0, "correct": 0, "picked": 0, "pending": 0}
    for game_id, pick_abbr, confidence in picks:
        game = games_by_id.get(game_id)
        if game is None:
            continue
        scored = score_pick(pick_abbr, confidence, game)
        total["picked"] += 1
        total["points"] += scored["points"]
        if scored["correct"] is None:
            total["pending"] += 1
        elif scored["correct"]:
            total["correct"] += 1
    return total


def rank_rows(rows):
    """Sort a standings list and stamp `rank` on each row, in place.

    Points, then correct picks as the tiebreaker, then username so the order is
    stable rather than whatever the database happened to return. Ranking is
    competition-style: two players tied for first are both 1 and the next is 3,
    because calling one of them second is a claim the scoreboard cannot support.
    """
    rows.sort(key=lambda r: (-r["points"], -r["correct"], (r.get("username") or "").lower()))
    for i, row in enumerate(rows):
        prev = rows[i - 1] if i else None
        tied = prev is not None and prev["points"] == row["points"] \
            and prev["correct"] == row["correct"]
        row["rank"] = prev["rank"] if tied else i + 1
    return rows


def validate_week_picks(picks, games_by_id):
    """Check a submitted week. -> (clean, error_message).

    `picks` is the list off the wire and `games_by_id` is every pickable game in
    that week, keyed the same way the wire keys them (as strings). `clean` is
    the list re-read field by field, so nothing the client sent reaches the
    database unexamined.

    The checks are ordered so the message names the first thing actually wrong
    rather than a downstream symptom of it.
    """
    if not isinstance(picks, list):
        return None, "picks must be a list"
    if len(picks) > MAX_PICKS:
        return None, f"at most {MAX_PICKS} picks per request"

    # The ceiling is the week's pickable games, not the number submitted -- see
    # the note at the top of this file on why it cannot be 1..k.
    n = len(games_by_id)
    if len(picks) > n:
        return None, f"this week has only {n} pickable games"
    clean = []
    seen_games = set()
    seen_conf = set()

    for entry in picks:
        if not isinstance(entry, dict):
            return None, "each pick must be an object"

        game_id = str(entry.get("game_id") or "").strip()
        if not game_id:
            return None, "game_id is required on every pick"
        game = games_by_id.get(game_id)
        if game is None:
            return None, f"game {game_id} is not a pickable game in this week"
        if game_id in seen_games:
            return None, f"game {game_id} appears twice"
        seen_games.add(game_id)

        pick = str(entry.get("pick") or "").strip().upper()
        if pick not in (game["away"], game["home"]):
            return None, (f"{pick or '(blank)'} is not playing in game {game_id} "
                          f"({game['away']} at {game['home']})")

        # bool is a subclass of int, and True would otherwise sail through as a
        # confidence of 1.
        confidence = entry.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, int):
            return None, f"confidence must be a whole number (game {game_id})"
        if not 1 <= confidence <= n:
            return None, (f"confidence must be 1 to {n}, got {confidence}")
        if confidence in seen_conf:
            return None, f"confidence {confidence} is used twice"
        seen_conf.add(confidence)

        clean.append({"game_id": game_id, "pick": pick, "confidence": confidence})

    return clean, None
