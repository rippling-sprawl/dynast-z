# Historical Decisions Log — Dynast-Z

> **What this file is:** the searchable record of *why* the system is the way it is — architectural and strategic choices, tradeoffs, and rejected alternatives behind the live code. Two uses: **(1)** when weighing a design choice, grep here for the subsystem to see what was already decided and why before re-litigating it; **(2)** to catch when a proposed change would **regress a deliberate past decision**. You are not expected to read it end-to-end — search it by subsystem/concept; each entry stands alone.
>
> **What belongs here:** **architectural** choices (schema/data-model, where a behavior lives, tech/library picks, pipeline ordering, invariants other code must respect); **strategic** choices (methodology, validation policy, scope in/out, build-vs-defer, what was deliberately NOT built); and the **why + rejected alternative** behind any non-obvious code change. *Not* routine fixes the diff already explains, *not* change history (`CHANGE_LOG.md`), *not* open work (`HANDOFF.md`).
>
> Add entries via `/change-log` (step 5b). Crisp architectural/tech choices → the Key Technical Decisions table; choices needing a paragraph (a tradeoff, a rejected approach, a "don't do X because Y") → the Design-Rationale Notes section. Lead each with the subsystem/file/concept by name so a future grep lands on it.

---

## Key Technical Decisions

| Decision | Why (incl. the alternative rejected) |
|----------|--------------------------------------|
| **Bets CSS colors use theme tokens from `styles/base/theme.css`, never hex** | Light Mode swaps the tokens under `:root[data-theme="light"]`; hex stays dark-themed. **Invariant:** new rules in `styles/primary/bets.css` (and inline `style=` in bets views) use `var(--…)`; if no exact token exists, use the nearest existing one rather than hex. Rejected (2026-09-11 merge): keeping the Settle Up branch's hex colors. |
| **Settle Up bulk settle uses awaited per-bet writes (`betsApiUpsertAwaited`)** | Only bets the server accepts are flipped to `wager_status: 'settled'` in the local cache, and partial failures are reported. Rejected: the fire-and-forget `betsApiUpsert` used elsewhere, which would show bets as settled before persistence is confirmed. |

---

## Design-Rationale Notes

- **Settle Up (`views/bets/settle.html`) — summary cards + "Settle Final Outcomes" replaced main's grouped `settle-table`.** When `main` was merged into the Settle Up branch (2026-09-11), main's table render was dropped rather than kept alongside: the branch's summary (Net P/L owed + Unpaid Stakes, per-bet Payment Amount) is its intended replacement, and `/bets/history` remains the place for the full breakdown. Only final outcomes (win/loss/push/void) are ever settled; pending bets stay open so their stakes keep counting toward Unpaid Stakes. Revisit if a per-wager-status grouped view is wanted on this page again.
