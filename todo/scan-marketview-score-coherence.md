# Make !scan and !market-view scores coherent (and fix the misleading help text)

**Status:** OPEN
**Created:** 2026-06-21

## The problem (user, 2026-06-21)

The user ran `!scan NVDA` and `!market-view NVDA` for the **same ticker within ~1 minute** and got **two different "Score" numbers** (e.g. 63 vs 75), with `!market-view` also slapping a 🟡 WATCHLIST band on its number. Their question: how can the same stock at the same moment show two different scores on two different scales — and does that seem reliable? It does not. This item captures the three real defects the investigation surfaced.

## What the investigation found (all verified in code, 2026-06-21)

**Root cause: `!scan` and `!market-view` are two completely independent computations that never share state.**

- `!market-view` reads the latest row from the `decision_snapshots` table (`commands.py:1091`, `db.get_recent_decision_snapshots`).
- `decision_snapshots` is written in **exactly one place**: `main.py:1581` (`db.record_decision_snapshot`), inside the **live signal pipeline** — i.e. only when a **real tweet/signal** flows through the engine.
- `!scan` (`_scan_and_reply`, `commands.py:551-596`) runs a fresh `cross_reference()` with a **synthetic NEUTRAL trigger** (`fake_tweet`, `Direction.NEUTRAL`, `Conviction.MEDIUM`), prints the result, and **persists nothing**. `cross_reference.py` writes no snapshot either.
- ∴ `!market-view` one second after `!scan` shows the **last real-signal verdict** (could be hours/days old, or absent) — **NOT** the scan the user just ran.

### Issue A — two unrelated "Score" numbers, different scales, same word
- `!scan` "Score" = `xref.final_score` = the **additive** cross-reference total (base + news + tech + social + llm + options + …), uncapped, can exceed 100 (`commands.py:580-581`).
- `!market-view` "Score" = `s["final_score"]` = also the additive total, but from a **different (real-signal) computation at a different time** (`commands.py:1101,1125`).
- Both are labeled just "Score" with no "here's what's high," so the user reasonably compares them — but they are not the same measurement. A cold neutral scan landing at 60 next to a saved strong-signal verdict at 80 is expected, not a bug — but it **looks** like a contradiction.

### Issue B — the "run !scan first" help text is WRONG (quick fix)
- When no snapshot exists, `!market-view` replies: *"No decision snapshots for `$TICKER` yet — run `!scan TICKER` first."* (`commands.py:1095`).
- This is misleading: `!scan` **does not create a snapshot**, so following the instruction leaves `!market-view` still saying "none." The instruction points at a command that can't do what it claims.

### Issue C — on one market-view line, the number and the dot are different scales (already tracked)
- `!market-view` shows `Score: {final_score}` (additive) next to a 🟢/🟡/🔴 dot from `s["decision"]`, whose ALERT/WATCHLIST/IGNORE cutoffs (80 / 65, `config/consensus.yaml:650-651`) are applied to the **precision-engine gated 0-100 score** — a *different* number. So the number and the dot can look out of step.
- This is the **same root as TODO #46 / the I4-full unification** (display-scale work). #46's display slice shipped 2026-06-21 (regime + disagreement readable); the score-family unification was explicitly deferred to the **I4-full flag** (tracked in the go-live list under #32/#36). Do NOT duplicate — fold Issue C into that.

## Possible next steps (priority-ordered)

1. **Quick win — fix the help text (Issue B).** Either (a) make `!market-view` not tell users to run `!scan` (point them at what actually creates a verdict — a real signal, or nothing), or (b) reword to be accurate. ~1 line in `commands.py:1095`. Confirm no test pins the old string first.
2. **Decide the intended relationship (Issue A).** Two clean options — pick one with the user:
   - **(a) Make `!scan` persist** its result as a snapshot so `!market-view` reflects the most recent on-demand scan (then "run !scan first" becomes TRUE and the two agree). Caveat: a neutral synthetic scan would overwrite a real-signal verdict — decide whether that's desired.
   - **(b) Keep them separate but relabel** so it's unmistakable they're different things (e.g. `!scan` → "Fresh check (Strength N)", `!market-view` → "Last saved verdict from <age> ago"), and stop both calling it bare "Score."
3. **Unify the score scale (Issue C)** via the existing I4-full path — one calculation, one 0-100 number, same meaning across `!scan`, `!market-view`, and auto-alerts, with the dot driven by the same scale. This is the big one; it's the I4-full go-live decision, not new work.

## Files / code involved
- `consensus_engine/alerts/commands.py` — `_scan_and_reply` (551-596), `_handle_market_view` (1086-1128; help text :1095, Score+dot :1125, disagreement :1127).
- `consensus_engine/main.py:1581` — the ONLY `record_decision_snapshot` caller (live pipeline).
- `consensus_engine/cross_reference.py` — `cross_reference()` (no persistence).
- `consensus_engine/db.py:3039` — `record_decision_snapshot` writer.
- `config/consensus.yaml:650-651` — high/medium confidence cutoffs (80/65) for the dot.
- Related: TODO #46 (`unified-display-scale.md`) + the I4-full flag in the go-live list (#32/#36).

## Open questions
- Is `!scan`'s neutral-trigger score even meant to be comparable to a real-signal verdict, or should `!scan` be reframed as "what would this score on its own merits, ignoring any tweet"?
- Should `!scan` persist (option 2a) — and if so, should a manual scan be allowed to overwrite a real-signal verdict in `decision_snapshots`?

## Anything else a cold session needs
- Surfaced during discover run `todo-20-46` (the #20/#46 completion session). The scale-readability half of this (regime/disagreement) already shipped under #46; THIS item is the cross-surface *coherence* half that #46 did not touch.
- Lesson logged in memory `comm-check-fail-2026-06-21-section-3` (an in-code help string is a claim, not evidence — grep the writer before explaining how commands relate).
