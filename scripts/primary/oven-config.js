/* The Baker's Oven — feature configuration (window.OVEN).
 *
 * Tuning constants only. The league, the draft and the identity of "my" team
 * are NOT here: leagues are per-account data (see oven-leagues.js), the league
 * id comes from the URL, and draft_id is derived at runtime from the league
 * object so a new season or a redraft doesn't require a code change.
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

  };
})(window);
