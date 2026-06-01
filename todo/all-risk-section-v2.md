# Round 2: sharpen the !all "Risk Considerations" section

**Status:** OPEN
**Created:** 2026-06-01

## The goal (plain English)

Round 1 (shipped 2026-05-31, commits f83e3d0 + d596453) merged the three overlapping risk sections into one, killed the repeated stop-loss price, and added a real macro/regulatory news bullet (the China/Taiwan export story). This round fixes the quality defects that a head-to-head against Gemini's NVDA bear case exposed — without bloating the compact 2–4 bullet Discord section.

## How we got here

Compared our live `!all NVDA` risk section (Discord msg 1510903036745220166) to a Gemini "senior equity analyst" bear case. Full analysis + adversarial verification in the background workflow output; key context in `.claude/discover/all-risk-section/` (pass-0 through pass-5).

**Fair framing (important — don't over-correct):** Gemini answered a *12–24 month investment* bear case (5 structural categories: hyperscaler capex/ROI, custom-ASIC competition, TSMC single-sourcing, valuation, power-grid/rates). Ours is a *4–6 day swing* risk note. Most of Gemini's substance is real but moves on a multi-quarter clock — it will NOT resolve inside a 4–6 day hold. Importing it would make our card worse (bury the actionable risk, and we're already at the 4000-char embed limit). So those are **out of scope**, not gaps. Our section is correctly scoped, every bullet is evidence-cited, and it carries live data Gemini can't see (dated macro headline, short interest, peer RS, options snapshot, SL/TP).

But the comparison found **genuine, fixable defects in ours** — that's what this TODO is for.

## What to fix (priority-ordered, all verified against the code)

1. **[correctness] Magnitude-guard the positioning bullet.** `narrator.py:~646-649` hands the model the template `short interest <X>% of float → squeeze/unwind risk` with NO magnitude guard, and short interest is fed unconditionally (`~769-771`). So a *trivial* 1.3% short interest fired a "squeeze risk" bullet — that's noise (1.3% is low; no squeeze setup). Only emit a squeeze/crowding bullet when short interest is actually elevated (e.g. ≥ ~8–10% of float OR days-to-cover ≥ ~5). 1–2 line prompt edit, no new data.

2. **[substance] Use the freed slot for a real positioning/overextension bullet** from data already in the pipeline (`recent_run_pct` + RSI/rvol from technical). Add a "distance from recent high" clause ONLY if `levels` actually carries a recent-high value — don't assert "~10% off the high" unless that field exists. (Gemini's one genuinely swing-useful point was the "pulled back from the $236.54 record" context.)

3. **[correctness bug] The hard gate doesn't re-check its own retry.** `narrator.py:~1022-1026` adopts the corrective re-prompt output (`raw = retried_risk`) WITHOUT re-running `quality_bar.risk_section_violations()`. A stubborn weak model can leak the stop price twice and still pass. Fix: re-validate `retried_risk`; keep the original `raw` if the violation isn't actually gone.

4. **[reliability] Make the no-price prompt rule MECHANICAL, not longer.** This is the answer to "explain it once clearly": weak free-tier models follow concrete format rules better than rationale. Replace the explanatory ban (`narrator.py:~621-625`) with something like: *"BANNED IN THIS SECTION: any price level. Before writing each bullet, if it contains a `$`, the word 'stop'/'buy zone', or a standalone number that could be a share price, delete it and write a different risk."* KEEP the gate as the deterministic backstop — it's free on clean output (pure regex, no LLM call; the re-prompt only fires on an actual violation), and live evidence proved prompt-alone fails on this model chain (stop price restated 6× despite the prompt forbidding it).

5. **[polish] Strip internal tags from user-facing prose.** The live output leaked raw pipeline labels into Discord text: *"per [macro_risk] news"* and *"as indicated by the COMPUTED SIGNAL"*. `output_filter.py` has NO scrub for these. Add a post-render scrub so `[macro_risk]`, `COMPUTED SIGNAL`, `[evidence:N]` etc. never reach Discord. Also drop/relocate the `(0.7×ATR×√5; high-vol data unavailable)` parenthetical from the prominent view.

6. **[structure] Lock the section to 2–3 bullets, fixed priority:** (1) dated `[macro_risk]` news when present (the differentiator — keep first); (2) the strongest available positioning/setup risk — prefer a real options put-flow signal or genuine overextension over a weak squeeze line (the live run HAD options flow available but spent the slot on the weak 1.3% squeeze bullet); (3) a dated binary-event line ONLY when a catalyst falls inside the window — and when it does, phrase it as *"expectations stretched → outsized downside on any miss"* (this absorbs Gemini's asymmetric-reaction point as wording, not a new bullet).

## Explicitly DROPPED (do not build)
- A valuation / "priced for perfection" bullet — fwd P/E resolves nothing in a 4–6 day window; out of scope for swing.
- Gemini's ASIC-competition / TSMC-concentration / hyperscaler-capex / power-grid breadth — all real but 12–24mo structural; out of scope for a swing card and would blow the embed length.

## Files involved
- `consensus_engine/alerts/all_command/narrator.py` — `_build_constraints_block` (merged section ~610-650, mechanical rule ~621-625, positioning template ~646-649), computed_signal wiring (~769-785), gate retry (~1022-1026).
- `consensus_engine/alerts/all_command/quality_bar.py` — `risk_section_violations` (the gate, ~142-187).
- `consensus_engine/alerts/all_command/output_filter.py` — add the user-facing tag scrub (none today).

## Open questions
- Does `levels` carry a recent-high value (for rec #2's "distance from high" clause)? Verify before relying on it.
- Should put-flow be auto-preferred over short-interest for the positioning bullet, or ranked by a magnitude score?
