# Next Steps After Milestone 0

**Date:** 2026-04-24
**Branch:** `claude/multi-agent-tmux-setup-zWYEQ` — milestone 0 already pushed.
**Last commits:** `2c8a046` (drafts + gitignore), `e5171fd` (ralplan-state cleanup), `e429e61` (milestone 0).
**Audit source:** `plans/AUDIT_RESEARCH_2026-04-24.md`.
**Specs:** `.omc/specs/milestone0/` (5 specs + SUMMARY.md, all Codex-approved).

---

## Pick up here (next session — top-of-mind)

The audit's own "Part 7 — Next step" section names **Q9 (conviction parser fix)** as the natural next question, because Q9 unblocks **M6** and **M1** — two of the highest-lift remaining proposals.

**Recommended split:**
- **Track A — operational soak (2 weeks of running with milestone-0 changes).** Run the post-deploy SQL probes from each spec at the 24 h / 7 d / 30 d marks. Confirm `shadow_predictions` accumulates and `actual_hit` gets backfilled. After ~2 weeks, decide whether to graduate calibration from shadow to live.
- **Track B — start Q9 spec immediately.** Sizing is unknown; that is precisely why it goes to ralplan first. Don't write code yet — just produce a Q9 spec under `.omc/specs/milestone1/01-conviction-parser.md` so we know how big it is before committing.

If Q9 turns out small (≤2 days), bundle it with **M6** (one-line `market_ok` exemption) into a single PR. If Q9 turns out big, switch to **Q5** (volume_scanner wire-up — independent, ~20 LOC, +15–25 pp recall).

---

## Operational soak checklist (Track A)

Run these from the workspace root after deploy. Every spec under `.omc/specs/milestone0/` has its own `## Verification` section with the exact SQL — paste from there.

- [ ] **24 h after deploy.**
  - Spec 02: `signal_events` shows `source_type='twitter'` rows (≠ 0); `apewisdom` count still 0.
  - Spec 02: `alert_messages.followup_msg_id IS NULL` rate has dropped materially below the 78.4 % baseline.
  - Spec 04: `youtube_level_alerts` per-(ticker, level) repeat-fire query returns 0 rows.
- [ ] **7 d after deploy.**
  - Spec 03: `shadow_predictions` has rows for every Phase-2 alert × 2 horizons; `actual_hit` is being labelled by `price_outcome_loop`.
  - Spec 03: `decision_snapshots.outcome_price_1h` and `outcome_price_24h` are non-NULL for resolved alerts.
  - Spec 05: a high-precision analyst's confirming tweet is no longer suppressed by a low-precision analyst (probe (a) in the spec).
- [ ] **14–30 d after deploy.**
  - Decide whether to flip `calibration.shadow_mode.retrain_on_startup` → live mode (graduate from shadow). Requires `MIN_SAMPLES` rows in `decision_snapshots` with non-NULL `outcome_price_*`.
  - Re-run the audit's "Rubric empirical audit" SQL on fresh data; check whether the inverted monotonicity (94 % @ 30-band vs 21 % @ 60-band) has moved.

---

## Audit roadmap (Track B candidates, ranked by lift / cost)

From `plans/AUDIT_RESEARCH_2026-04-24.md` Parts 4–5. Milestone-0 items are crossed out.

### Quick wins (≤3 d, ≤2 files, no new dep)

- ~~**Q1 — Calibration ON in shadow mode.**~~ (milestone 0)
- ~~**Q2 — Phase-2 timeout + signal_events fix.**~~ (milestone 0)
- ~~**Q3 — Kill `max_alerts_per_hour`.**~~ (milestone 0 phantom-killer)
- **Q4 — SearXNG `content` body enrichment.** `scanners/searxng.py` + `scanners/news.py:279–302`. ~25 LOC. +3–5 pp precision, +1–2 pp recall. Independent.
- **Q5 — Wire `volume_scanner.py` into main loop.** `main.py` + existing `scanners/volume_scanner.py`. ~20 LOC. +15–25 pp **recall** (entire source currently dead). Independent.
- **Q6 — Wire OR delete `regime_detector`.** Audit picked delete-from-yaml in milestone 0; module file still on disk. Decide in this milestone whether to wire it (~50 LOC) or delete the module (`consensus_engine/analysis/regime_detector.py`) outright.
- **Q7 — Reddit upvote / comment-velocity weighting.** `scanners/social.py` or `reddit_trend.py`. ~40 LOC. +3–4 pp precision.
- ~~**Q8 — YouTube level dedup.**~~ (milestone 0 — spec 04)
- **Q9 — Fix conviction parser to actually distribute 20/25/30.** `analysis/tweet_parser.py`. Sizing unknown — **start here for milestone 1**. Currently 99.1 % of alerts are `base_score=25`, so every conviction-keyed gate is inert until this lands.

### Medium bets (1–4 weeks, kill-switch required)

- **M1 — Re-enable SEC watcher with item-type + dollar filter.** `scanners/sec_watcher.py` + `sec_edgar.py` + `config/consensus.yaml:94`. ~200 LOC. +6–10 pp precision, +10–15 pp recall. **Depends on M6** (otherwise SEC alerts get killed by `require_market_confirmation`).
- **M2 — Options IV rank + put/call skew + term-structure.** `scanners/options.py` + new `analysis/options_features.py`. ~150 LOC. Needs CBOE free daily CSV. +8–12 pp precision.
- ~~**M3 — Per-analyst cooldown.**~~ (milestone 0 — spec 05)
- **M4 — Claude Haiku 4.5 for tie-break LLM scoring.** `analysis/llm_scorer.py`. ~60 LOC. Needs `ANTHROPIC_API_KEY`. +4–7 pp on the 18–25 score band.
- **M5 — Delete dead calibration/regime/reliability code paths.** Now mostly moot — milestone 0 turned calibration on (Q1) and removed the YAML phantoms; remaining cleanup = decide whether to delete the unwired regime_detector module file. Tiny.
- **M6 — Exempt HIGH-conviction from `require_market_confirmation`.** `engine.py:294–308`. ~15 LOC. **Depends on Q9.** +8–12 pp precision, +10–15 pp recall once Q9 distributes the conviction tiers.

### Moonshots (> 1 month, research-cited)

- **X1 — Cross-asset confirmation layer.** Sector ETF + correlated-pair divergence. ~300 LOC.
- **X2 — Self-play backtest auto-tuner.** ~800 LOC. **Needs ≥ 1000 labelled alerts.** DB had 575 at audit time — wait for ~1500 before starting.
- **X3 — Positioning-extreme feature** (CBOE put/call + CFTC COT). ~250 LOC.
- **X4 — LLM-adjudicated contradiction resolver.** Haiku over Phase-2 source dump. ~400 LOC.

### Explicit kills already decided (audit Part 4.4)

- Reliability_engine: source missing, flag removed in milestone 0. Decide: delete the `.pyc` artifact + the module-load comment, or restore the module. Currently in limbo.
- Regime_detector: yaml stanza removed in milestone 0; source file preserved per discovery-2026-04-24/40-implementation-plan.md. Decision still pending: wire (~50 LOC) or delete the source file.

---

## Other open items (from project memory)

These are pre-milestone-0 and may overlap with the audit roadmap:

- `requirements.txt` + timeout counters — open per `project_outstanding_work.md`.
- TUI input-clear bug — open per `project_outstanding_work.md`.

Confirm against `/root/.claude/projects/-root--openclaw-workspace/memory/project_outstanding_work.md` at session start; the file may have moved on.

---

## Suggested first move next session

```
1. cd /root/.openclaw/workspace
2. git status                                        # confirm clean tree, branch up to date
3. cat plans/NEXT-STEPS-2026-04-24.md                # this file
4. cat .omc/specs/milestone0/SUMMARY.md              # what shipped
5. (Track A) run the 24h SQL probes from spec verification sections
6. (Track B) /ralplan Q9 conviction parser
   → produces .omc/specs/milestone1/01-conviction-parser.md
   → if small (≤2 d), bundle Q9 + M6 in one PR
   → if big, switch to Q5 (volume_scanner wire-up, ~20 LOC, independent)
```

---

## Where to look

- **Tracked in git:** this file, `plans/AUDIT_RESEARCH_2026-04-24.md`, `.omc/specs/milestone0/`, the three audit drafts.
- **Auto-memory pointers:** `/root/.claude/projects/-root--openclaw-workspace/memory/MEMORY.md` index + the `project_milestone0_shipped.md` and `project_next_steps.md` entries added 2026-04-24.
- **CLAUDE.md (project):** `/root/.openclaw/workspace/CLAUDE.md` — alert philosophy, commit convention, key design decisions.
