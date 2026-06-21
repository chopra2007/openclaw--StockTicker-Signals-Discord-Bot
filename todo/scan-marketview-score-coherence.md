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

### Issue C — TWO scoring formulas exist; the number and the dot are different scales (a BUILT switch already collapses them — currently OFF)
The engine runs the **same inputs** through **two different score formulas that were never merged**:
- **Formula 1 — additive cross-reference total** (`xref.final_score` = `ScoreBreakdown.total`): every source adds raw points (news+15, tech+12, options+10, llm+15…), summed with **no ceiling**, can exceed 100. This is the original score.
- **Formula 2 — precision-gated 0-100 score** (`engine.analyze_signal` → `precision["total_score"]`, classification via cutoffs `high_confidence 80` / `medium_confidence 65`, `config/consensus.yaml:650-651`): a separate bounded "is this actually strong?" gate added later. This produces the ALERT/WATCHLIST/IGNORE 🟢/🟡/🔴 **dot**.

What each surface shows:
- `!scan` → **Formula 1 only** (`xref.final_score`, `commands.py:580-581`); runs no precision gate, shows **no dot**.
- `!market-view` → the **dot** = `classification` (Formula 2, written at `main.py:1583` `decision=classification.value`), but the **number** = `final_score`. So on one line the digits and the dot are from two different formulas → they can look out of step.

**THE BUILT SWITCH (verified 2026-06-21, currently OFF):** `features.single_score.enabled` — reconciliation block at **`main.py:1500-1517`**. When ON, it makes `final_score` = the **precision-gated total** (`_p_total`) — "the ONE number used in both headline and decision logging" (the code comment at `main.py:1493-1496`), with a never-contradict floor (a STRONG class can't show a sub-`high` number). Budget-depressed runs (a paid source skipped) fall back to the xref total on purpose. This flag is the historical "I4-full" unification; it is **OFF by default** (`config/consensus.yaml`, single_score `enabled: false` ~L812). The partial honesty flag `score_display_honesty` (~L803) **is** ON but does NOT fully unify the two formulas.
- Same root as TODO #46 (display-scale). #46's display slice shipped 2026-06-21 (regime + disagreement readable); the score-family unification was deferred to this `single_score`/I4-full flag (tracked in the go-live list under #32/#36, "flip one at a time after I4-full soaks"). Do NOT duplicate — Issue C = flip `single_score`.

## Possible next steps (priority-ordered)

1. **Quick win — fix the help text (Issue B).** Either (a) make `!market-view` not tell users to run `!scan` (point them at what actually creates a verdict — a real signal, or nothing), or (b) reword to be accurate. ~1 line in `commands.py:1095`. Confirm no test pins the old string first.
2. **Decide the intended relationship (Issue A).** Two clean options — pick one with the user:
   - **(a) Make `!scan` persist** its result as a snapshot so `!market-view` reflects the most recent on-demand scan (then "run !scan first" becomes TRUE and the two agree). Caveat: a neutral synthetic scan would overwrite a real-signal verdict — decide whether that's desired.
   - **(b) Keep them separate but relabel** so it's unmistakable they're different things (e.g. `!scan` → "Fresh check (Strength N)", `!market-view` → "Last saved verdict from <age> ago"), and stop both calling it bare "Score."
3. **Unify the score scale (Issue C) — the real fix, and it's already BUILT.** Flip `features.single_score.enabled` to `true` (reconciliation at `main.py:1500-1517`, currently OFF) so `final_score` becomes the precision-gated 0-100 number everywhere (headline + decision logging), with the never-contradict floor. That makes `!market-view`'s number and dot the same scale, and — if step 2a is also done so `!scan` runs the precision gate — makes scan and market-view comparable. This is the I4-full go-live decision (flip one at a time after soak, per the #32/#36 list), not new code. NOTE: it changes live alert numbers, so do a shadow/staged check before flipping.

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

### Session notes — 2026-06-21
- **Worked on:** Issue C only — flipped `features.single_score.enabled` false→true (consensus.yaml:813) per user "flip on the switch so we can monitor it". Engine restarted clean (active, 0 restarts, no errors, gateway up, symlink intact); flag loads True; 13/13 `test_i4_full_single_score.py` pass.
- **Decisions:** flipped during the weekend pause on purpose — live signals resume Sun 11:00 PDT / 14:00 ET, so the first real reconciliations (and any alert-number change) start this afternoon, a clean observation window. Evidence file: `.claude/go-live-evidence/features_single_score_enabled.md`. Scheduled capture task (`task_1782039195_8cb9a9`, 11:30 PDT) writes the first `[I4-full shadow]` lines to notifications.log.
- **Effect / limits:** this fixes Issue C's *market-view* half — `decision_snapshots.final_score` (what `!market-view` shows) is now the precision-gated 0–100 number, so its number and dot finally share a scale. It does NOT make `!scan` and `!market-view` agree (Issue A, step 2) and does NOT touch the wrong "run !scan first" help text (Issue B, step 1) — both still open.
- **Next:** after Sun resume, watch `journalctl -u consensus-engine.service | grep 'I4-full shadow'` + a real `!market-view` on a freshly-alerted ticker (number on the 0–100 scale, no STRONG under 80). Then decide Issue B (1-line help fix) and Issue A (persist scan vs relabel) with the user.

### Session notes — 2026-06-21 (follow-up: Issue B DONE)
- **Issue B (Step 1) DONE + live-verified.** Reworded `commands.py:1095` (the no-snapshot `!market-view` reply). Old text falsely said "run `!scan` first" (scan never writes a snapshot). New text: "No saved verdict for `$TICKER` yet — the bot logs one only when a live signal fires for it (not from `!scan`). For an on-demand read now, try `!scan TICKER` (quick check) or `!all TICKER` (full analysis)." No test pinned the old string; compile clean.
- **Live proof:** restarted engine, posted `!market-view ADP` (ADP has 0 snapshots) as a bot verification-probe to the commands channel, captured the bot's actual reply = the new text. Test messages deleted after.
- **Still open:** Issue A only (make `!scan` and `!market-view` show the same number — persist scan vs relabel). Issue C is flipped+soaking. When Issue A is decided + done, this item can be marked DONE.
