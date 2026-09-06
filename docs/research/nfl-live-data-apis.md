# Live NFL box scores & odds — provider evaluation

**Accessed 6 September 2026.** Companion to [`nfl-live-data-apis.html`](nfl-live-data-apis.html),
which carries the full side-by-side tables and the per-service design cards. This file is the
grep-able version: the recommendation, the request-budget arithmetic, and every source URL.

Scope: **NFL only**. Other sports were not evaluated and are not a tiebreaker anywhere below.

---

## Recommendation

**balldontlie GOAT — $39.99/month** for box scores *and* odds on one bill.

It is the only provider that clears every stated constraint on published, primary-source terms:

- Static API key in an `Authorization` header over plain GET — no cookies, no OAuth, no browser.
- 600 req/min, and **no monthly request cap** of any kind.
- Live in-game data is **not** tier-gated; `/games` is documented "updated in real-time for games
  currently in progress" and is on the free tier.
- ToS §6 expressly permits "use, copy, cache, store, archive, modify, combine, analyze, publish,
  display, distribute, sublicense, and create derivative works, products, services, or databases",
  with permitted uses naming "lawful sportsbook and wagering products". No other provider here
  grants storage rights that clearly.

`ALL-STAR` at **$9.99/mo** already covers score, quarter, team stats and player stats. Step up to
GOAT only for the game clock, live possession (`/plays`), odds, and player props.

**Pair with:**

- **ESPN** — free opening *and* closing lines from DraftKings, in the same scoreboard payload the
  schedule fetcher already uses. Pregame-only, but that is most of what CLV needs.
- **The Odds API $59/mo** — only if multi-book in-play prices at 40s matter. See the credit maths below.

### The one test worth running first

balldontlie's **actual** latency was never measured — it needs a key. Its 48-hour GOAT trial would
settle it against a live slate. Measure against the three thresholds (25s score/period, 2 min player
stats, 3–5 min team stats) before committing. This is the single largest remaining unknown.

---

## Request budget

Window: Sunday **8:00am–11:55pm ET** = 15h55m = **57,300s**. ~4.3 Sundays/month.
Generator: [`scripts/`-adjacent scratch](#) — arithmetic reproduced here.

```
score + period @ 25s     57,300 / 25          =  2,292   (scoreboard-wide, 1 call covers the slate)
player stats   @ 2 min   478 snapshots × 14   =  6,692   (box score is a PER-GAME endpoint)
team stats     @ 4 min   —                    =      0   (arrives in the same box-score response)
                                                -------
NAIVE                                             8,984 / Sunday   →  ~38,600 / month

gated scoreboard         46,800s live / 25    =  1,872
gated box score          16 games × 98        =  1,568
                                                -------
GATED to live games                               3,440 / Sunday   →  ~14,800 / month   (2.6× cheaper)

PEAK RATE  60/25 + 14/2  =  9.4 req/min       ← the number that actually filters providers
```

Only **82%** of the stated window has football in it: four kickoff waves (9:30am international,
1:00pm ×10, 4:25pm ×4, 8:20pm SNF) with dead air between them.

**9.4 req/min** is the binding figure, not the monthly total. It clears balldontlie's 60/min and
OpticOdds' 2,500/15s; it saturates API-SPORTS' free 10/min before retries; it is 34× SportsDataIO's
100 calls *per day*.

---

## Verdicts

| Provider | Box scores | Odds | Why |
|---|---|---|---|
| **balldontlie** | ✅ $9.99–39.99/mo | ✅ included at GOAT | Recommended. Book list undocumented; props have no history |
| **ESPN** | ⚠️ free, complete | ⚠️ pregame only, DraftKings only | 26–33s lag; Disney ToS bans automated access + DB building + business use |
| **The Odds API** | ✕ scores only | ✅ $59/mo, 40s in-play | Credits = markets × regions; props blow the quota |
| **TheRundown** | ✕ | ⚠️ $49/mo | 60-second delay is contractual below $399 |
| **Sportradar** | ⚠️ best-in-class, 3s TTL | ⚠️ separate product | Quote only. Trial = 1,000 req / 30 days = ⅓ of one Sunday |
| **SportsGameOdds** | ✕ | ⚠️ unresolved | Free tier 2,500 objects/mo; paid pricing failed verification 0–3 |
| **SportsDataIO** | ✕ next-day | ✕ 100 calls/day | $99/mo is in budget but the feeds are next-day and the cap is 34× short |
| **OpticOdds / OddsJam** | ✕ unpriced | ✕ unpriced | Same company now. Technically excellent, quote-only, ToS bars revenue use |
| **Stats Perform** | ✕ | ✕ | Developer-portal registration is switched off. No self-serve path at any price |
| **API-SPORTS** | ✕ | ✕ | NFL odds are pre-match only, 4×/day. Free tier 100 req/day |
| **MySportsFeeds** | ✕ | — | Every published tier is "Non-Live access"; box scores are an unpriced add-on |
| **nflverse** | ✕ batch | — | Refuses by design to publish a season with an unfinished game |
| **NFL shield API** | ✕ | — | Partner-only. Every path 401s; ToS §1.3 bans systematic retrieval |
| **Pro Football Reference** | ✕ | — | 20 req/min block, ToS ban, permanent refusal to offer an API |
| **Action Network** | ✕ | ✕ | No keyed API. `developer.actionnetwork.com` does not resolve |
| **VegasInsider** | ✕ | ✕ | No API, no JSON layer. ToS bans scraping; robots.txt bans query-string URLs |
| **Pikkit** | ✕ | ✕ | No API. `api.pikkit.com` does not resolve |
| **JuiceReel** | ✕ | ✕ | Real OAuth API, but returns only the connected user's own bet slips |

Legend: ✅ recommended · ⚠️ viable with a caveat · ✕ ruled out · — not applicable

---

## Things that will bite

**The Odds API bills multiplicatively.** `cost = markets × regions`. ML+spread+total in `us` is
3 credits per call, not 1. US books are split across two billable region keys — reaching both
DraftKings and theScore Bet needs `regions=us,us2`, doubling every call to 6. Featured-market
polling at 40s ≈ 17k–43k credits/month (fits the 100k tier). Player props are per-event only:
14 games × 5 prop markets at 60s ≈ **67,200 credits in one Sunday**. Historical/closing endpoints
carry a **10×** multiplier and are paid-only.

**Caesars' bookmaker key is `williamhill_us`**, not `caesars`. A pipeline requesting
`bookmakers=caesars` silently returns nothing.

**TheRundown meters "data points", not calls** — one point = one returned price row
(outcome × line × book). The vendor's own "expanded snapshot" example needs the $149 tier.

**Closing line value is a storage problem.** balldontlie states it does *not* store historical prop
data. The Odds API charges 10× for history. ESPN gives opening *and* closing lines free. Snapshot
lines yourself on a schedule; buying history back later is the expensive path everywhere.

**ESPN's exposure is contractual, not technical.** Measured here: 100 GETs at 67.8 req/s, zero
throttling, box score confirmed populating during a live game. But the Disney Terms of Use (which
name ESPN, last updated 24 May 2024) prohibit automated access by "robot, spider, script";
"compiling, building, creating or contributing to any collection of data, data set or database";
and any "commercial or business-related use … whether or not for profit". This is the same class of
objection that disqualified Pro Football Reference.

---

## Measured here, not read

Run on this machine, 2026-09-06:

- ESPN scoreboard: HTTP 200, keyless, ~200 KB, 267 ms, 16 events; `status{clock,displayClock,period}`,
  team logos + records, inline DraftKings odds with `open` and `close`.
- ESPN `/summary?event=401772510`: 411 KB; `boxscore.teams[].statistics` = 25 team stats;
  `boxscore.players[].statistics` = 10 categories with per-athlete lines.
- ESPN burst: 40 sequential GETs → 40/40 HTTP 200 in 6s (~6.6 req/s), zero 429.
  A verifier independently ran 100 GETs at concurrency 20 → 100/100 in 1.47s (67.8 req/s).
- ESPN propagation: **26–33s** from ESPN's own play wallclock to the summary endpoint, on a live game.
- `www.espn.com/nfl/scoreboard` → HTTP 202, 1,987-byte bot interstitial. The API hosts serve fine.
- Pro Football Reference → Cloudflare "Just a moment…" managed challenge on a plain `robots.txt` GET.
- Auth probes (no key): The Odds API 401 · SportsDataIO 401 · Sportradar 403 · API-SPORTS 403 ·
  balldontlie 401 · SportsGameOdds 401 · api.nfl.com 401 · ESPN core `/odds` → `count=1`, DraftKings.
- nflverse release assets: `play_by_play_2025.csv.gz` last updated 2026-08-13; no 2026 asset exists.
- Brand assets and palettes for all 14 services → `assets/research/<service>/palette.json`.

---

## Primary sources

| Claim | Source |
|---|---|
| balldontlie tiers, endpoints, ToS §6 data licence | https://nfl.balldontlie.io |
| balldontlie per-sport pricing | https://www.balldontlie.io/ |
| Disney ToS §2.A / 2.B.viii / 2.B.x (governs ESPN) | https://disneytermsofuse.com/english/ |
| The Odds API plans and credit costs | https://the-odds-api.com/#get-access |
| The Odds API — "1 per region per market" | https://the-odds-api.com/liveapi/guides/v4/ |
| The Odds API in-play intervals (40s / 60s) | https://the-odds-api.com/sports-odds-data/update-intervals.html |
| The Odds API bookmaker + region keys (`us2`) | https://the-odds-api.com/sports-odds-data/bookmaker-apis.html |
| The Odds API historical, 10× multiplier | https://the-odds-api.com/historical-odds-data/ |
| TheRundown pricing, delay tiers, data points | https://therundown.io/pricing/api |
| TheRundown rate limits | https://docs.therundown.io/rate-limits.md |
| Sportradar trial: 1,000 req / 30 days, 1 QPS | https://developer.sportradar.com/getting-started/docs/your-account.md |
| SportsDataIO published NFL prices + 100 calls/day | https://discoverylab.sportsdata.io/personal-use-apis/nfl |
| nflverse update cadence | https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html |
| nflfastR `fast_scraper` (~15 min post-game) | https://nflfastr.com/reference/fast_scraper.html |
| Sports Reference bot policy, 20 req/min, no-API stance | https://www.sports-reference.com/bot-traffic.html |
| MySportsFeeds CAD pricing, "Non-Live access" | https://www.mysportsfeeds.com/feed-pricing/ |
| API-SPORTS OpenAPI spec v1.4.7 (pre-match only) | https://api-sports.io/public/documentations/nfl-v1.yaml |
| OpticOdds auth, rate limits, sportsbook list | https://developer.opticodds.com/ |
| SportsGameOdds pricing + free-tier object cap | https://sportsgameodds.com/pricing |
| Stats Perform developer portal (registration off) | https://developer.stats.com/ |
| JuiceReel OAuth API docs | https://www.juicereel.com/api-docs |

---

## Method

Two parallel deep-research runs (203 agents) mapped the landscape; both flagged the same gap — the
most likely winners had produced zero verified claims. A third round (18 agents, after one
session-limit restart) closed it. Load-bearing price and quota claims were re-fetched by independent
adversarial verifiers instructed to refute them; claims that survived fewer than 2 of 3 are marked
unresolved rather than stated.

**Not established, and not guessed:** Sportradar, Stats Perform, OpticOdds and the NFL publish no
price at all. SportsGameOdds' paid tiers remain unresolved (3 of 4 claims refuted). balldontlie's
observed latency and sportsbook coverage are undocumented. API-SPORTS' paid tier prices could not be
read from any primary page — the widely-repeated $19/$29/$39 figures were refuted 0–3.

One subagent investigating Action Network was flagged for probing undocumented endpoints and testing
user-agent variation. Those results were discarded; no bypass technique is documented here, and
Action Network is recorded simply as having no sanctioned programmatic access.
