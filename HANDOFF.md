# Handoff — Dynast-Z

**Date:** 2026-09-11 · **Purpose:** the minimum context a new session needs to pick up this project.

> **Scope of this file:** forward-looking work + non-obvious operational knowledge only. It does **not** recap change history (that's `CHANGE_LOG.md`) or design rationale (that's `HISTORICAL_DECISIONS_LOG.md`). Keep it short enough to read end-to-end.

## Current state & where to pick up

**Where things are (v0.02):** Branch `feature-enhancement-kwok-settle-up` is caught up with `main` and pushed. PR #1 (Settle Up balances + bulk settle workflow) targets `main` with Vercel checks green and a clean merge state — it is waiting to be merged.

**Pick up here:**
- Merge PR #1.
- Then the two small Settle Up cleanups under open items.

---

## What This Project Is

Dynast-Z (dynastz.com) is a sports / fantasy web app: static HTML views in `views/` with client JS in `scripts/`, served locally by `server.py` (`python3 server.py` → http://localhost:8000) and deployed on Vercel with Python handlers in `api/`. It spans dynasty/fantasy tools, NFL odds and games, Pick 'Em / Survivor pools, and a per-user bet tracker under `/bets` with admin audit.

---

## Resume Here — open items

- **Merge PR #1** — https://github.com/rippling-sprawl/dynast-z/pull/1
- **Remove unused `WAGER_STATUS_MISSING`** (`scripts/primary/bets.js:38-39`) — its comment says Settle Up groups missing wager statuses under it, but the page now treats a missing status as `unpaid` ("Assumed Unpaid" chip) and nothing references the constant.
- **Remove dead `.settle-table` CSS** in `styles/primary/bets.css` — left from main's old table-based Settle Up; no view renders it anymore.

---

## Important Gotchas

1. **`/bets/settle?demo=1` works only on `localhost` and overwrites the browser's bets cache** with 10 demo bets (every paid/unpaid × outcome combo). It never writes to the server; the next non-demo load re-hydrates from `/api/bets`. Use it to test settle math without real data.
2. **A local `404` for `/_vercel/insights/script.js` is expected** — Vercel injects that route at deploy time. Ignore it when reading the console.
3. **Playwright MCP writes only inside the repo** (screenshots land in the repo root or `.playwright-mcp/`) and its browser window is headed. Delete those artifacts before committing, and don't read a dialog closing mid-test as a bug if someone may be clicking in that window.

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `CHANGE_LOG.md` | Versioned history — read to retrace why a past change was made |
| `HISTORICAL_DECISIONS_LOG.md` | Why the code is shaped this way — architectural/strategic decisions, tradeoffs, rejected alternatives |
| `HANDOFF.md` | This file — current project context for new sessions |
| `ARCHITECTURE.md` | Architecture + activity diagrams and a file/responsibility summary |
| `docs/bets-persistence-supabase.md` | How bets persist server-side (`/api/bets`) |
