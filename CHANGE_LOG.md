# Change Log — Dynast-Z

> Lean, newest-first. Each entry captures the decision and *why* — not the file list (git has that). Older entries auto-archive to `Old Documentation/CHANGE_LOG-archive.md`.

---

## v0.02 — 2026-09-11 — Settle Up branch caught up with main; styles moved to theme tokens

### Decision: Keep the Settle Up summary flow; port its styles to theme tokens

Merged `main` into `feature-enhancement-kwok-settle-up` (PR #1). In `views/bets/settle.html` we took main's `<head>` (theme, PWA meta, analytics, lightbox) and unversioned asset URLs but kept the branch's summary cards + confirm-settle flow, dropping main's grouped `settle-table` render — the branch's flow is its intended replacement, and the two can't coexist. The branch's new Settle Up CSS auto-merged with hard-coded dark hex that would ignore Light Mode, so it was ported to `styles/base/theme.css` tokens (nearest token where none matched exactly, e.g. `#56d364` → `--good`). A "confirm dialog won't open" scare during local Playwright testing was not a bug — someone was clicking in the headed browser window, and backdrop clicks close the dialog by design — so no code was changed for it.

---

## v0.01 — 2026-09-11 — Project scaffolding

### Feature: Project scaffolding

Initial living docs — added `CHANGE_LOG.md`, `HANDOFF.md`, and `HISTORICAL_DECISIONS_LOG.md` to carry context between sessions. The `/change-log` command is installed at user level, so no project copy under `.claude/skills/` was added.

---
