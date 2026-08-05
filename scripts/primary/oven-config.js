/* The Baker's Oven — feature configuration (window.OVEN).
 *
 * Single source of truth for the league, the identity of "my" team, and the
 * polling/tuning constants. The draft_id is deliberately NOT here: it's derived
 * at runtime from /league/{id}/drafts so a new season or a redraft doesn't
 * require a code change.
 */
(function (global) {
  'use strict';

  global.OVEN = {
    // Keepers & Weepers — 12 team, 16 round, half-PPR snake with keepers.
    LEAGUE_ID: '1384025526670233600',
    MY_USERNAME: 'baker28',
    MY_USER_ID: '631654820146761728',
    MY_ROSTER_ID: 1,

    // Sleeper sends `access-control-allow-origin: *`, so the browser polls it
    // directly — no proxy, and the rate limit applies per client IP.
    SLEEPER_API: 'https://api.sleeper.app/v1',

    // Sleeper documents "stay under 1000 calls/minute". 8s polling over a 2h
    // draft is 900 requests (7.5/min) — under 1% of that. Sleeper's own edge
    // sets s-maxage=30, so unchanged polls revalidate to 304/0 bytes anyway.
    POLL_MS: { drafting: 8000, pre_draft: 60000, complete: 0, paused: 15000 },
    STATUS_POLL_MS: 60000,
    BACKOFF_START_MS: 8000,
    BACKOFF_MAX_MS: 60000,

    // Board persistence: localStorage first, reconciled with Supabase through
    // scripts/base/sync.js when logged in, so the board follows you to your
    // phone on draft night.
    STORAGE_KEY: 'dz_oven_board_v1',
    SYNC_SPORT: 'football',
    SYNC_KEY: 'oven_board',

    // Targets & Projections keeps its own synced slice — a list of board keys,
    // nothing else. Queuing a player must never rewrite the imported CSV, and
    // the queue should follow you from the index to the board to your phone.
    TARGETS_STORAGE_KEY: 'dz_oven_targets_v1',
    TARGETS_SYNC_KEY: 'oven_targets',

    // Rank-vs-consensus delta (in board positions) that saturates the hot/cold
    // scale, and the window used to smooth per-row heat into visible regions.
    HEAT_MAX: 24,
    HEAT_WINDOW: 5,

    // Explicit CSV grades, mapped onto the same scale as the rank delta so a
    // graded row and a computed row are directly comparable.
    GRADE_HEAT: { love: 24, like: 10, fade: -10, avoid: -24 },

    // The two positive grades wear a glyph instead of a word — at a 250-row
    // scroll a heart registers faster than four letters, and the pair reads as
    // one scale (deeper red = stronger). `fade` still has no badge at all, and
    // `avoid` stays a word: it's the rare one, and it should cost a beat to read.
    GRADE_ICON: { love: '❤️', like: '🩷' },

    // Round projections. Both weights are in board positions, on the same scale
    // as GRADE_HEAT: queuing a player is worth ~8 spots when the simulation
    // decides who I'd actually take, and a `love` grade is worth 12 (24 × 0.5).
    // Halving the grade keeps an opinion from outranking two full rounds of
    // rank — the CSV column is a thumb on the scale, not a replacement for it.
    PROJ_TARGET_BONUS: 8,
    PROJ_GRADE_WEIGHT: 0.5,
    PROJ_PROJECTED_SHOWN: 3,   // best-available rows offered per future pick
    PROJ_MAX_ENTRIES: 6,       // ceiling once targets are merged in

    // Thermal ramp endpoints. The source spreadsheet used green/salmon
    // (#57BB8A / #EB9891) and both halves of that were wrong here: the fills
    // were alpha-over-white so they composite muddy on a near-black page, and
    // green/red is the single pair that collapses under deuteranopia — on the
    // one screen where the color IS the signal.
    //
    // Frost -> flame is colorblind-safe, survives the dark background at low
    // alpha, and is what a board called The Baker's Oven should have measured
    // in from the start. Must stay in sync with styles/primary/bakers-oven.css.
    HEAT_POS_RGB: [255, 122, 24],   // --oven-flame  #FF7A18 — I'm higher than consensus
    HEAT_NEG_RGB: [106, 169, 208],  // --oven-frost  #6AA9D0 — the market's higher than me

    FP_DATA: '/data/fp_redraft.json',
    FP_META: '/data/fp_redraft_meta.json',
    FP_STALE_DAYS: 3,
  };
})(window);
