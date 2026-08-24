# TODO #93 — Auction Pressure and Price Response Research Plan

**Status:** READY FOR EXECUTION
**Date:** 2026-08-24 Pacific
**Scope:** Historical research only until every final gate passes
**Budget:** $0. Use only the records already downloaded. Do not read `DATABENTO_API_KEY`, request an online cost estimate, or place any Databento order.

## Outcome

Find out whether either of two genuinely different auction mechanisms produces a stable, tradeable stock edge:

1. **Pressure versus price response:** changing auction pressure is absorbed, exhausted, or confirmed by the opening price.
2. **Closing-to-opening pressure transfer:** institutional pressure at the prior close persists, flips, or unwinds at the next open.

The result must support zero to four stock setups during 6:15–6:45 a.m. Pacific, survive a five-minute human reaction delay, and remain profitable after realistic costs. If neither mechanism passes internal validation, stop and close TODO #93. Do not search more versions of the same fields.

## Evidence already established

- TODO #93 defines the goal, the two new mechanisms, the zero-to-four daily cap, and the stop rule ([ticket lines 6–38](../../todo/opening-auction-high-conviction-edge.md)).
- The prior test only examined the final signed opening imbalance. It failed both directional spread gates, while entry fillability passed ([prior verdict lines 20–85](../../.omc/research/opening-auction-imbalance/final-research-verdict.md)).
- The final 182 trading dates have not been used for outcome evaluation and remain reserved for one final test ([prior verdict lines 113–134](../../.omc/research/opening-auction-imbalance/final-research-verdict.md)).
- The imbalance file contains both opening and closing auction messages. The useful fields are `total_imbalance_qty`, `paired_qty`, and `side`; the price-like auction fields are empty and must not be used ([data audit lines 48–92](../../.omc/research/opening-auction-imbalance/data-capability-audit.md)).
- Reliable entry liquidity begins at 6:30 a.m. Pacific, and the previously verified delayed entry price is the one-minute bar ending at 6:35 a.m. Pacific ([data audit lines 111–129](../../.omc/research/opening-auction-imbalance/data-capability-audit.md)).
- The local files contain 45,313,852 imbalance records and 40,278,360 one-minute price records. They cost $116.528388, leaving $8.471612 unused ([manifest lines 66–127](../../../research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/manifest.json)).
- The existing research code already streams the compressed records, applies halted/degraded-date exclusions, builds market-adjusted 60-minute returns, and avoids loading the complete store into memory ([existing research script lines 21–172](../../scripts/research/phase1c_feasibility_probe.py)).
- `pandas` and `scikit-learn` are already installed; no new package is allowed ([requirements lines 10–19](../../requirements.txt)).

## Hard boundaries

- Research files may be added under `.omc/research/opening-auction-pressure-response/`, `scripts/research/`, and `tests/research/` only.
- Do not change production code, configuration, the live database, background programs, Discord behavior, or alert switches.
- Do not make network calls or download data. All readers must use `databento.DBNStore.from_file(...)` against the existing local files.
- Do not use the four empty auction price fields named in the data audit.
- Do not reuse the rejected rule that the final imbalance sign alone predicts the same-direction move.
- Do not describe a model score as a probability or confidence percentage.
- Stock results do not prove option returns.
- All owner-facing times and reports use Pacific time only.
- No live scanner is built by this plan. A final pass only earns a separate production decision.

## Frozen data split

Use the same 912 ordered trading dates already established:

- **Development:** first 730 dates, ending 2025-11-28.
- **Final evaluation:** remaining 182 dates. No evaluation outcomes, summaries, plots, or model scores may be produced before the internal gate passes.

Inside the 730 development dates, use four expanding walk-forward folds:

1. Train on dates 1–250; validate on 251–370.
2. Train on dates 1–370; validate on 371–490.
3. Train on dates 1–490; validate on 491–610.
4. Train on dates 1–610; validate on 611–730.

Every trailing statistic uses only dates strictly before the event date. No random split is allowed.

## Frozen clock and trade definitions

- Opening-pressure snapshots: latest opening-auction message received at or before 6:15, 6:20, 6:25, 6:29:30, and 6:30 a.m. Pacific.
- Prior closing pressure: final closing-auction message from the immediately preceding trading session.
- **Lane A signal time:** 6:35 a.m. Pacific after the first five regular-session minutes are complete. Entry is the price from the bar ending at 6:40 a.m. Pacific.
- **Lane B signal time:** 6:31 a.m. Pacific, because the local historical opening-minute record is not complete until then. Entry is the price from the bar ending at 6:36 a.m. Pacific.
- Primary exit: 60 minutes after the lane's entry.
- Secondary diagnostics: 30-minute exit, maximum favorable move, and maximum adverse move. They cannot override the primary result.
- Entry requires more than 500 shares in the entry minute, matching the previously verified fillability rule.
- Base round-trip trading cost: 15 basis points. Also report 10- and 25-basis-point sensitivity.
- Primary return: proposed-direction return minus the ticker's trailing beta times the equal-weighted return of the other available names, then subtract the base cost.
- Win: primary net market-adjusted return greater than zero.
- One independent event per ticker and trading date. If more than one rule fires, merge them into one candidate and retain all firing rule IDs.
- Lane A requires all five pressure snapshots plus its required price records. Lane B requires the prior closing pressure, the 6:30 pressure snapshot, and its required price records. Missing inputs exclude the row with an explicit reason; do not fill missing source observations.

## Frozen feature definitions

For every magnitude threshold, use the ticker's trailing 60 valid trading sessions, never the same or future day. Require at least 20 prior sessions.

- `signed_pressure`: signed `total_imbalance_qty / paired_qty`.
- `pressure_extreme`: absolute signed pressure at or above its trailing 90th percentile.
- `closing_pressure_extreme`: absolute prior-closing pressure at or above its trailing 90th percentile.
- `persistence`: share of the five opening snapshots whose sign matches the 6:30 sign.
- `persistent`: persistence is at least 0.80 and there is no sign flip after 6:25.
- `flip_count`: number of sign changes across consecutive snapshots.
- `growth`: absolute 6:30 pressure minus absolute 6:15 pressure.
- `cancellation`: `(largest absolute pressure before 6:30 - absolute 6:30 pressure) / largest absolute pressure before 6:30`; zero when the denominator is zero.
- `earlier_pressure_sign`: sign of the largest absolute snapshot before 6:30.
- `late_flip`: the 6:30 sign differs from `earlier_pressure_sign`.
- `paired_size`: 6:30 paired quantity divided by its trailing 60-session median.
- `prior_close`: close of the broad-market one-minute record ending at 1:00 p.m. Pacific in the preceding trading session.
- `opening_price`: the opening value of the broad-market one-minute record beginning at 6:30 a.m. Pacific; treat it as available at 6:31, when that historical record is complete.
- `opening_gap`: opening price versus `prior_close`.
- `first_five_return`: opening price through the bar ending at 6:35.
- `large_gap`: absolute opening gap at or above its trailing 75th percentile.
- `calendar_group`: ordinary day, month-end trading day, or quarter-end trading day. Calendar membership is computed mechanically, not selected from results.
- `follows(direction, value)`: `direction * value > 0`; `fails_to_follow(direction, value)`: `direction * value <= 0`.

Winsorize continuous model inputs at the 1st and 99th percentiles learned from the current training fold only. Store the learned cut points with each fold.

## Six hypotheses, fixed before new results

### Lane A — pressure versus price response

1. **A1 — absorbed pressure:** 6:30 pressure is extreme and persistent; both the opening gap and first-five-minute return satisfy `fails_to_follow` for its sign. Trade opposite the 6:30 pressure at 6:40.
2. **A2 — exhausted pressure:** the largest pre-6:30 pressure is extreme; `cancellation >= 0.50` or `late_flip` is true; the opening gap follows `earlier_pressure_sign`; and the first-five-minute return follows the opposite sign. Trade opposite `earlier_pressure_sign` at 6:40.
3. **A3 — confirmed pressure:** 6:30 pressure is extreme and persistent; both the opening gap and first-five-minute return satisfy `follows` for its sign. Trade with the 6:30 pressure at 6:40. This tests whether enough move remains after confirmation; failure does not revive the rejected final-imbalance-only rule.

### Lane B — closing-to-opening pressure transfer

4. **B1 — persistent institutional pressure:** prior closing pressure and current 6:30 opening pressure are both extreme and share a sign; the opening gap satisfies `follows` for that sign. Trade with the shared sign at 6:36.
5. **B2 — overnight pressure flip:** prior closing and current opening pressure are both extreme but have opposite signs; the opening gap satisfies `follows` for the current opening sign. Trade with the current opening pressure at 6:36.
6. **B3 — calendar rebalance exhaustion:** on a month-end or quarter-end trading day, current opening pressure is extreme and the opening gap is large and satisfies `follows` for the current opening sign. Trade opposite the current opening pressure at 6:36.

Do not add a seventh rule. A correction to a broken definition creates a clearly versioned replacement and retires the broken version; it does not permit both versions to compete.

## Ranking model

The six rules generate candidates. A deliberately small model ranks them; it does not invent candidates.

- Use `SimpleImputer(strategy="median", add_indicator=True)`, `StandardScaler`, and `LogisticRegression(penalty="l2", C=1.0, max_iter=2000, random_state=20260824)` from the existing `scikit-learn` installation. The missing-value step is for model columns that do not apply to a lane; it must never invent a missing source observation required for candidate eligibility.
- Target: whether the candidate's proposed direction wins under the frozen primary definition.
- Inputs: one-hot rule IDs plus the frozen pressure, persistence, cancellation, paired-size, gap, first-five-minute, prior-closing-pressure, same/flip, and calendar features. Lane B rows must mark first-five-minute inputs unavailable; they cannot use them.
- Train separately inside each expanding fold. Never fit scaling, clipping, missing-value replacements, thresholds, or coefficients on validation dates.
- A candidate is selected only when its training-fold precision at that score or higher is at least 60% with at least 50 earlier examples. Select no more than the four highest-ranked qualifying candidates per day. Zero is valid.
- Compare the ranked strategy against every plain rule, all generated candidates, the middle-ranked candidates, matched no-signal ticker-days, and a direction-shuffled control repeated 1,000 times by trading date.

## Statistical rules

- The ranked combined strategy is the single primary test.
- The six plain-rule results are secondary tests and use Holm correction across their six primary p-values.
- Confidence ranges use 10,000 bootstrap samples clustered by trading date, because same-day stocks are not independent.
- Direction-shuffle controls shuffle within trading date so broad market direction is preserved.
- Use random seed `20260824` for every bootstrap, shuffle, sample, and model operation; save it in every result file.
- Report mean, median, win rate, loss rate, profit factor, average winner, average loser, maximum drawdown, candidate days, no-trade days, trades per day, long/short split, ticker concentration, and results by fold.
- Show all exclusions and missing-data counts. No silent row drops.

## Internal validation gate

The combined ranked strategy advances only if every condition passes across the four walk-forward validation blocks together:

1. At least 200 independent selected trades and at least 30 distinct tickers.
2. No more than four selected trades on any day.
3. Win rate at least 60%, with the clustered 95% lower bound above 50%.
4. Mean primary return at least +20 basis points after the 15-basis-point base cost, with the clustered 95% lower bound above zero.
5. Profit factor at least 1.25.
6. Positive mean primary return in at least three of four validation blocks, with no block worse than -5 basis points.
7. No ticker contributes more than 10% of total net profit.
8. The selected group beats the middle-ranked group and matched no-signal days by at least 15 basis points after costs.
9. The observed mean exceeds the 95th percentile of the 1,000 direction-shuffled controls.
10. Mean return remains non-negative under the 25-basis-point stress cost.

If any condition fails, write the negative or insufficient-data verdict, update TODO #93, and stop. Do not open the final evaluation outcome file and do not tune another version.

## Final evaluation gate

If the internal gate passes:

1. Refit the unchanged pipeline once on all 730 development dates, choose its score threshold by the same frozen training-only precision rule, then freeze and hash the hypothesis file, feature code, ranking code, coefficients, learned transformations, score threshold, exclusions, and internal result.
2. Make one final-evaluation run over the 182 reserved dates. No rerun is allowed except to correct a documented mechanical defect found by the independent auditor; a corrected run must replace and invalidate the first run, never compete with it.
3. Require at least 100 independent selected trades, no more than four per day, at least 60% wins with the 95% lower bound above 50%, at least +20 basis points mean after base cost with the 95% lower bound above zero, profit factor at least 1.25, no ticker above 15% of net profit, and non-negative mean under the stress cost.
4. Require the ranked group to beat the middle-ranked, matched no-signal, and shuffled controls in the predicted direction.

Anything short of all four conditions is not a proven edge. Mark the result rejected or insufficient and close TODO #93 without production work.

## Execution phases and required files

### Phase 0 — safety and reproducibility

- Read `docs/agents/PROJECT_RULES.md`, TODO #93, this plan, the manifest, data audit, prior verdict, and existing research scripts.
- Record the current Git state without altering unrelated files.
- Verify all four downloaded file hashes against the manifest.
- Record Python and package versions.
- Add tests that fail if a research script tries to instantiate an online Databento client, reads an API key, or writes outside the allowed research paths.
- Output: `.omc/research/opening-auction-pressure-response/phase0-gate.json`.

### Phase 1 — immutable development panel

- Add `scripts/research/auction_pressure_build_dev.py`.
- Stream the local files and build one row per eligible ticker-date with the five snapshots, prior closing pressure, price fields, frozen features, entry/exit prices, exclusions, and development-fold number.
- Preserve source timestamps in the row so an audit can prove every input existed by the lane's signal time.
- Store compact Parquet plus a CSV sample and a machine-readable data dictionary.
- Output: `dev-panel.parquet`, `dev-panel-sample.csv`, `data-dictionary.json`, `phase1-gate.json`.

### Phase 2 — hypothesis and leakage lock

- Write `hypotheses-v1.md` and `hypotheses-v1.json` containing the six rules exactly as above.
- Add `scripts/research/check_auction_pressure_gate.py` with mechanical checks for file presence, hashes, date limits, clock limits, six-rule maximum, allowed features per lane, and zero evaluation-result artifacts before advancement.
- Add unit tests for every feature, snapshot cutoff, prior-session join, fold boundary, cost calculation, and duplicate merge.
- Output: `phase2-gate.json`.

### Phase 3 — walk-forward builder result

- Add `scripts/research/auction_pressure_walkforward.py`.
- Generate all-candidate, plain-rule, selected-strategy, matched-control, and shuffled-control event files.
- Save each fold's fitted scaling values, coefficients, score threshold, and input hashes.
- Output: `internal-events.parquet`, `internal-summary.json`, `internal-report.md`, `phase3-gate.json`.

### Phase 4 — independent audit

- A reviewer who did not write the builder must independently reproduce the feature values and outcomes from raw DBN records, not from the builder's panel.
- Recompute all headline statistics with a separate audit script.
- Inspect at least 50 randomly chosen events, every exclusion category, all date boundaries, all cases with duplicate rule fires, and the ten largest winners and losers.
- Prove Lane B never uses first-five-minute data or enters before 6:36, and Lane A never enters before 6:40.
- Output: `audit-recompute.json`, `audit-event-checks.csv`, `audit-report.md`, `phase4-gate.json`.
- Any material timing, leakage, direction, join, or cost defect fails the gate. Fixing one creates a versioned rerun followed by a new independent audit.

### Phase 5 — internal decision

- Extend the mechanical gate checker to recompute every internal gate directly from `internal-events.parquet` and the audit output.
- If any gate fails, write `final-research-verdict.md`, update TODO #93 as rejected or insufficient, and stop.
- If all gates pass, write `frozen-final-spec.json` containing hashes and enable the final-evaluation phase.
- Output: `phase5-gate.json`.

### Phase 6 — one-time final evaluation

- Add a separate `scripts/research/auction_pressure_eval_once.py` that refuses to run unless `frozen-final-spec.json` passes its hash checks.
- Apply the frozen transformer, rules, model, threshold, daily cap, costs, and exclusions to the 182 reserved dates once.
- Output: `final-events.parquet`, `final-summary.json`, `final-report.md`, `phase6-gate.json`.

### Phase 7 — final independent verdict

- A separate reviewer independently recomputes the final headline numbers and checks raw timestamps and prices.
- The mechanical checker decides pass/fail from the frozen final thresholds.
- Write a plain-language `final-research-verdict.md` explaining what passed, failed, or remained insufficient.
- Update TODO #93 with exact counts, results, paths, and the next state.
- Output: `final-audit-report.md`, `phase7-gate.json`.

### Phase 8 — conditional production decision, no automatic build

Only after a fully passing final verdict:

- Determine the exact ongoing price and licensing terms for a live opening/closing auction feed without purchasing it.
- Write a separate production plan for a shadow-only scanner using the existing candidate/decision/outcome measurement chain.
- Report the cost and proof to the owner. Do not buy access, change live behavior, or send alerts in this research run.

## Acceptance criteria

- All work stays inside the allowed research paths, except the required TODO #93 status update.
- No paid-data request, API-key read, production edit, service restart, live database write, Discord post, or order occurs.
- Every new feature and trade can be reconstructed from source timestamps and local records.
- The development/evaluation boundary and both lane clocks have automated tests.
- The six rules, feature list, model settings, costs, and gates are frozen before validation results are produced.
- Internal and final decisions are made by mechanical gate files, not narrative judgment.
- A separate reviewer reproduces both internal and final headline results.
- Production planning occurs only after every final condition passes.
- The run ends with either a proven result plus a production decision packet, or a clear closure of TODO #93. It must not end with an open-ended request to collect more data.

## Risks and controls

- **Multiple testing creates a fake winner:** six-rule maximum, one primary combined test, Holm correction, shuffled controls, and one final evaluation.
- **Future information leaks into a signal:** preserved timestamps, lane-specific feature allowlists, entry-clock tests, raw-event audit.
- **Same-day market moves inflate certainty:** beta adjustment, same-day matched controls, and date-clustered bootstrap.
- **One ticker or calendar event drives all profit:** concentration gates and four chronological validation blocks.
- **The ranking model memorizes the past:** fixed simple model, expanding walk-forward fitting, training-only transforms, no hyperparameter contest.
- **The final period becomes another tuning set:** one-time runner, frozen hashes, and no rerun except a documented mechanical correction.
- **The session spends remaining credit:** local-file-only tests and a hard ban on online Databento clients and API-key reads.

## Verification commands

The executor should create the exact new test and gate commands during Phase 2. At minimum, the final evidence packet must include successful results for:

```bash
python3 -m pytest tests/research/ -v
python3 scripts/research/check_auction_pressure_gate.py phase0
python3 scripts/research/check_auction_pressure_gate.py phase1
python3 scripts/research/check_auction_pressure_gate.py phase2
python3 scripts/research/check_auction_pressure_gate.py phase3
python3 scripts/research/check_auction_pressure_gate.py phase4
python3 scripts/research/check_auction_pressure_gate.py phase5
```

Run Phase 6 and Phase 7 commands only if Phase 5 reports an exact pass. Also run `git diff --check`. Run the full project test gate only if production or shared project code was touched; such touching is outside this plan and must be treated as a defect.

## Stop conditions

Stop immediately when any of these occurs:

- A paid download or missing external dataset appears necessary.
- A required input is unavailable before the simulated signal time.
- Internal validation fails any mandatory gate.
- An audit finds unresolved leakage, clock, mapping, direction, or cost errors.
- The final evaluation fails or lacks the required sample.

In each case, save the evidence, write the verdict, update TODO #93, and end the run. Do not replace a failed rule, widen the time window, lower a threshold, add data, or promise to try again after more collection.

## Execution handoff

This is a research project with a fixed evaluator, so use `$autoresearch-goal` as the durable execution owner. If parallel work is available, use one builder lane and one independent audit lane, but never let the builder approve its own result. The final gate remains leader-owned and mechanical.

Recommended roles if the execution surface supports them:

- One `executor` for data panel, feature, and walk-forward scripts.
- One `test-engineer` for clock, split, cost, and leakage tests.
- One `verifier` for independent raw-record reproduction and final gate evidence.
- One `critic` only after the evidence packet exists, to challenge the conclusion rather than rewrite the frozen rules.

Do not use a broad discovery workflow. The question, data, rules, and stop conditions are now explicit.
