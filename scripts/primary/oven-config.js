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

    // Rank-vs-consensus delta (in board positions) that saturates the hot/cold
    // scale, and the window used to smooth per-row heat into visible regions.
    HEAT_MAX: 24,
    HEAT_WINDOW: 5,

    // Explicit CSV grades, mapped onto the same scale as the rank delta so a
    // graded row and a computed row are directly comparable.
    GRADE_HEAT: { love: 24, like: 10, fade: -10, avoid: -24 },

    // Endpoint colors lifted from the source spreadsheet's conditional format.
    HEAT_POS_RGB: [87, 187, 138],   // #57BB8A
    HEAT_NEG_RGB: [235, 152, 145],  // #EB9891

    FP_DATA: '/data/fp_redraft.json',
    FP_META: '/data/fp_redraft_meta.json',
    FP_STALE_DAYS: 3,
  };
})(window);
