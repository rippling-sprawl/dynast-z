/* Baker's Oven — feature configuration (window.OVEN).
 *
 * Tuning constants, plus the one shared vocabulary table (SLOT_ELIGIBLE) and the
 * pure derivation over it that more than one module needs. The league, the draft
 * and the identity of "my" team are NOT here: leagues are per-account data (see
 * oven-leagues.js), the league id comes from the URL, and draft_id is derived at
 * runtime from the league object so a new season or a redraft doesn't require a
 * code change.
 */
(function (global) {
  'use strict';

  global.OVEN = {
    // Sleeper sends `access-control-allow-origin: *`, so the browser polls it
    // directly — no proxy, and the rate limit applies per client IP.
    SLEEPER_API: 'https://api.sleeper.app/v1',

    // Sleeper documents "stay under 1000 calls/minute". 8s polling over a 2h
    // draft is 900 requests (7.5/min) — under 1% of that. Sleeper's own edge
    // sets s-maxage=30, so unchanged polls revalidate to 304/0 bytes anyway.
    POLL_MS: { drafting: 8000, pre_draft: 20000, complete: 0, paused: 15000 },
    STATUS_POLL_MS: 20000,
    BACKOFF_START_MS: 8000,
    BACKOFF_MAX_MS: 60000,

    // Persistence: localStorage first, reconciled with Supabase through
    // scripts/base/sync.js when logged in, so your board follows you to your
    // phone on draft night.
    //
    // These are KEY BASES, not keys. Every localStorage key is built by
    // OvenLeagues.localKey(), which suffixes `:{user_id}` and — for the
    // league-scoped slices — `:{leagueId}`. A fixed global key here leaked one
    // account's board into the next one to sign in on the same browser (see
    // the auto-migration branch in scripts/base/sync.js). The v1 -> v2 bump on
    // the board and targets bases retires those poisoned keys outright.
    SYNC_SPORT: 'football',

    LEAGUES_STORAGE_BASE: 'dz_oven_leagues_v1',
    LEAGUES_SYNC_KEY: 'oven_leagues',

    BOARD_STORAGE_BASE: 'dz_oven_board_v2',
    BOARD_SYNC_KEY: 'oven_board',           // + ':' + leagueId

    // Targets & Projections keeps its own synced slice — a list of board keys,
    // nothing else. Queuing a player must never rewrite the imported CSV, and
    // the queue should follow you from the league page to the board to your
    // phone. Per-league, because a queued key only resolves against the CSV
    // imported for that league and the projection is built from that league's
    // round plan.
    TARGETS_STORAGE_BASE: 'dz_oven_targets_v2',
    TARGETS_SYNC_KEY: 'oven_targets',       // + ':' + leagueId

    // Which league you looked at last, so the leagues page can preselect it in
    // the My board picker. Local-only — not worth a server round trip.
    LAST_LEAGUE_BASE: 'dz_oven_last_league',

    // What a grade is WORTH, in board positions, to the Targets projection —
    // `adjRank` in oven-targets.js is the only reader. Liking a player moves him
    // 24 spots up the simulated market; fading one moves him 24 down.
    //
    // The name is a fossil: this used to feed a heat model that colored the board
    // (a saturated left rail, a smoothed row wash) by blending a grade and the
    // rank-vs-consensus delta into one number. Both channels are gone — the board
    // states the delta as the Δ column and the grade on its own control, because
    // they were never the same claim and the blend made them indistinguishable.
    // Nothing here is a display scale any more; the Δ column takes its two colors
    // straight from bakers-oven.css.
    GRADE_HEAT: { like: 24, fade: -24 },

    // Three grades, not five. `love`/`like` and `fade`/`avoid` were two pairs of
    // near-synonyms, and the distinction inside each pair never survived contact
    // with a live board: mid-draft you know whether you want him, not whether
    // you want him at strength 1 or 2. Merged, the scale is one decision per
    // player. GRADE_LEGACY below carries the old boards over.
    //
    // Both grades wear an emoji instead of a word — at a 250-row scroll a mark
    // registers faster than four letters, and the two are opposites at a glance
    // rather than something to read.
    GRADE_ICON: { like: '❤️', fade: '❌' },

    // The row's grade control (the button next to the pin). Its own table, kept
    // separate from GRADE_ICON because it needs a `none` mark and the badge has
    // no such thing — a badge for "no grade" is 860 rows of nothing said.
    //
    // `none` is a dot rather than a dash because an ungraded board is the
    // default state and should be nearly silent — 860 dashes would read as a
    // column of missing data.
    GRADE_MARK: { like: '❤️', fade: '❌', none: '·' },

    // The menu, top to bottom: yes, neutral, no. One ordered list so the items,
    // their labels and the aria text can never disagree. `null` is "no grade" —
    // the same value clearing a grade writes to the row.
    GRADE_MENU: [
      { value: 'like', label: 'Like'     },
      { value: null,   label: 'No grade' },
      { value: 'fade', label: 'Fade'     },
    ],

    // Grades written by the five-grade board, mapped onto the three that
    // replaced them. Read at board-build time (normGrade in oven-board.js) and
    // on CSV import, so a synced board saved on another device — or a rankings
    // sheet exported before the merge — still lands with its opinions intact.
    // Anything not in the menu and not in here becomes `null` rather than an
    // unstyled class name on a row.
    GRADE_LEGACY: { love: 'like', avoid: 'fade' },

    // Round projections. Both weights are in board positions, on the same scale
    // as GRADE_HEAT: queuing a player is worth ~8 spots when the simulation
    // decides who I'd actually take, and a `like` grade is worth 12 (24 × 0.5).
    // Halving the grade keeps an opinion from outranking two full rounds of
    // rank — the CSV column is a thumb on the scale, not a replacement for it.
    PROJ_TARGET_BONUS: 8,
    PROJ_GRADE_WEIGHT: 0.5,
    PROJ_PROJECTED_SHOWN: 3,   // best-available rows offered per future pick
    PROJ_MAX_ENTRIES: 6,       // ceiling once targets are merged in

    // How far past a pick a player's rank may sit and still be worth listing
    // under it, in league sizes — 1.5 × teams, so a pick and a half. Deeper
    // than that and the row isn't a candidate for this pick, it's a candidate
    // for a pick two rounds from now that will have its own list. One-sided:
    // a faller ranked well ABOVE the pick is the whole point of the view.
    PROJ_REACH_ROUNDS: 1.5,

    // No color constants live here any more. They existed so JS could interpolate
    // a ramp for the heat rail and row wash; with both gone, the Δ column is the
    // only thing left that carries a hue and it takes --oven-flame / --oven-frost
    // straight from bakers-oven.css. Two states, two named vars, one file.

    FP_DATA: '/data/fp_redraft.json',
    FP_META: '/data/fp_redraft_meta.json',
    FP_STALE_DAYS: 3,

    // Last season's weekly finishes, scored by THIS league's settings.
    //
    // FantasyPros ECR is a half-PPR projection of the coming season — someone
    // else's scoring, and an average that hides shape. These counts answer the
    // other question: how many weeks did he actually finish top 12 at his
    // position, under my rules? Four WR8 weeks and twelve WR60 weeks average
    // out to the same ECR as a steady WR15, and they are not the same player.
    //
    // Sleeper has no endpoint for this — only pos_rank_ppr/half_ppr/std, three
    // fixed formats, and no stats field in their GraphQL schema takes a
    // league_id. Their own player card computes the number client-side. So do
    // we: scoring_settings keys map 1:1 onto the raw stat keys, which makes
    // fantasy points a dot product. See scripts/fetch_nfl_weekly.py.
    WEEKLY_SEASON: 2025,
    WEEKLY_DATA: '/data/nfl_weekly_2025.json',
    WEEKLY_META: '/data/nfl_weekly_2025_meta.json',

    // Where he actually finished: half-PPR positional rank for the two seasons
    // before this one, straight off Sleeper's player card. The sub-line under
    // every name.
    //
    // The one number here that is NOT scored by your league, deliberately. A
    // positional finish is a shared reference — "he was the WR7" means the same
    // thing in every conversation you've had about him — and half-PPR is the
    // format it's quoted in. Re-scoring it privately would produce a different
    // number wearing the same name, and the weekly counts above already answer
    // the under-my-rules question.
    //
    // No season constant beside it: which two years the file covers is stated
    // IN the file, so a re-fetch next August rolls the labels forward without a
    // code change. See scripts/fetch_pos_ranks.py.
    POSRANK_DATA: '/data/nfl_pos_ranks.json',

    // What the market expects of him THIS season: one consensus yardage line
    // and one consensus touchdown line, on the same sub-line as the finishes
    // and to the right of them.
    //
    // The other half of a sentence the finishes only start. Two positional
    // ranks say what he has already done; a season-long O/U says what three
    // sportsbooks are willing to take money on him doing next — priced, not
    // projected, which is a different kind of claim than anything else on the
    // row. Neither one answers the other, which is exactly why both are here
    // and why they are drawn as two groups with a rule between them.
    //
    // Consensus = the mean of the books' main lines, the same FMV the /odds
    // page computes and shows; yards and touchdowns are each SUMMED across the
    // markets a player is priced on, so a rushing quarterback's legs count.
    // ~100 players have a market at all, out of ~860 on the board — a blank
    // here is the normal case, not a gap. See scripts/build_prop_lines.py.
    PROPS_DATA: '/data/nfl_prop_lines.json',

    // The books, spelled the way a person says them. The file stores the short
    // codes it parses from ("fd"/"dk"/"score"); a tooltip that named a source
    // "score" would be naming nothing. An unmapped code falls through as-is
    // rather than being dropped — a new book should show up wrong-looking, not
    // invisible.
    PROPS_BOOKS: { fd: 'FanDuel', dk: 'DraftKings', score: 'ESPN' },

    // How many of each position get STARTED across a 12-team league — the
    // yardstick the finish line grades a rank against (posRankTier in
    // oven-board.js), so RB4 and WR4 are scored as what each actually was
    // rather than as the same number.
    //
    // Starters, not roster spots and not a percentile of everyone who played.
    // 253 wide receivers were ranked last season; a percentile over that pool
    // puts WR40 in the top fifth, when WR40 is a man nobody started. Against 30
    // starting WRs he lands where he belongs.
    //
    // RB 24 is two per team, WR 30 is two and a half (the flex mostly lands
    // here), and the four one-start positions are one apiece. Fixed at 12 teams
    // rather than read from the league: the league's own roster_positions can
    // say how many RBs IT starts, but this is grading a finish in a season that
    // has already happened, and "RB18 in 2025" meant the same thing to everyone
    // who watched it. A 10-team league doesn't retroactively make him worse.
    POSRANK_STARTERS: { QB: 12, RB: 24, WR: 30, TE: 12, K: 12, DEF: 12 },
    // A CSV can carry any position string it likes. One start per team is the
    // conservative reading of an unknown one — it grades that column harder
    // rather than painting it optimistically.
    POSRANK_STARTERS_DEFAULT: 12,

    // The three cutoffs shown per row. 12 is "positional starter in a 12-team
    // league", and the wider two say whether a low top-12 count means he was
    // useless or merely just off the top — a WR with 5/13/16 was startable all
    // year, a WR with 5/6/7 was a boom-bust dart.
    WEEKLY_TIERS: [12, 24, 36],

    // Positions that only ever show the first cutoff. Every league starts one
    // TE, one K and one defense, so nobody is ever choosing between TE20 and
    // TE30 — "top 24 at TE" describes a player you would not have started in
    // any week of any league, which makes the number decoration rather than
    // information. QB/RB/WR keep all three because their starter depth actually
    // reaches that far.
    WEEKLY_SINGLE_TIER_POS: ['TE', 'K', 'DEF'],

    /* ---------- the league's own lineup vocabulary ---------- */

    /* Which players a lineup slot accepts, keyed by Sleeper's `roster_positions`
     * vocabulary. A single-position slot is its own eligibility list, so an
     * unrecognized slot ('DL', a league-specific label) still behaves sanely by
     * only accepting its own name. Slot specificity is `elig.length` — that is
     * what makes a QB land at QB rather than in the SUPER_FLEX beside it.
     *
     * It sits here rather than inside either reader because it has two:
     * oven-targets fills the Team view's lineup from it, and
     * OVEN.startablePositions() below turns it into the set of positions a
     * league actually starts — which is what keeps kickers and defenses off the
     * board of a league that rosters neither. */
    SLOT_ELIGIBLE: {
      QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DEF'],
      FLEX: ['RB', 'WR', 'TE'],
      WRRB_FLEX: ['RB', 'WR'],
      REC_FLEX: ['WR', 'TE'],
      SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
      IDP_FLEX: ['DL', 'LB', 'DB'],
    },

    // Slots that hold a player but never start one, so they say nothing about
    // which positions a league uses. IR and TAXI are never drafted into either;
    // BN is, but by whoever the starters didn't fit.
    NON_STARTING_SLOTS: { BN: true, IR: true, TAXI: true },

  };

  /* Every position this league can actually start, derived from its own
   * `roster_positions` — the only authority on the question. A 'FLEX' contributes
   * RB/WR/TE, a bare 'QB' contributes QB, and BN/IR/TAXI contribute nothing.
   *
   * This is what a board filters on. A league with no K and no DEF slot cannot
   * start either, so a kicker on its big board is a row that can never become a
   * lineup decision — noise in the one place (draft night) where a row you skip
   * past still costs you a beat.
   *
   * Returns **null**, not an empty list, when the league declares no starting
   * slot at all — an unloaded league, a league that is all bench. Null means "no
   * opinion, show everything"; an empty list would mean "start nobody" and would
   * blank the board. Callers must treat the two differently. */
  global.OVEN.startablePositions = function (rosterPositions) {
    var O = global.OVEN, seen = {}, out = [];
    (rosterPositions || []).forEach(function (raw) {
      var slot = String(raw || '').toUpperCase();
      if (!slot || O.NON_STARTING_SLOTS[slot]) return;
      (O.SLOT_ELIGIBLE[slot] || [slot]).forEach(function (pos) {
        if (!seen[pos]) { seen[pos] = true; out.push(pos); }
      });
    });
    return out.length ? out : null;
  };
})(window);
