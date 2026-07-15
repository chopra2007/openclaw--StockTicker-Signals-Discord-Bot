# Build plans for the #76 feature menu — the 7 ideas still to build

**Created:** 2026-07-14 (run `menu-top10`, TODO #76)
**Why this file exists:** these plans were produced by a discover run into
`.claude/discover/menu-top10/`, which is **git-ignored and lives in a throwaway worktree**. Copied here
so they survive. The ledger (`todo/feature-menu-ledger.md`) is the MENU (what's open, what's dead and
why); this file is the HOW-TO for the ones still open.

## Status of the 10 features planned below

| Plan | Feature | Status |
|---|---|---|
| **F1** | "Sources: N of M attempted" footer | ✅ **BUILT 2026-07-14** — `features.sources_denominator.enabled` |
| **F2** | VVIX fear-of-fear gauge | ✅ **BUILT 2026-07-14** — `features.vvix_residual.enabled` |
| **F3** | `!sweep` watchlist command | ✅ **BUILT 2026-07-14** — `features.sweep.enabled` |
| **F4** | Hedge-vs-directional options-flow classifier | ⬜ TO BUILD (ships as a shadow log — it touches a live alert) |
| **F5** | Crowding-guard generalization | ❌ **DROPPED 2026-07-14 (user)** — do NOT build. Its whole job was to treat several YouTube channels saying the same thing as "crowding" and discount them. The user's call: independent channels agreeing is **confluence, not crowding** — the exact signal we want, not noise to suppress. |
| **F6** | Brier/calibration report — timer + Discord sink | ⬜ TO BUILD (small; the maths already exists, nobody ever sees it) |
| **F7** | Short-alert squeeze-risk guard (c102) | ⬜ TO BUILD (its short-interest blocker HAS shipped) |
| **F8** | Analyst target-spread logger | ❌ **DROPPED 2026-07-14 (user)** — do NOT build. It logs the high-vs-low analyst target gap **daily**, but analysts rarely change targets, so it mostly writes the same three numbers over and over. Shows the user nothing for months (no history to compare against). Not worth it as planned. |
| **F9** | SEC XBRL fundamentals feed | ⬜ TO BUILD (heavy: new client + table + display) |
| **F10** | Backtest-to-live decay tracker | ⬜ TO BUILD (medium-heavy; grows in value as #73's outcome data fills in) |

**Two things this plan got WRONG, found during the F1–F3 build — do not trust it blindly:**
1. It said to rank `!sweep` on `breakdown.total`. That is the RAW ADDITIVE sum, but `!scan` reports the
   PRECISION-GATED score — following the plan would have made `!sweep NVDA` and `!scan NVDA` print
   different numbers for the same ticker, re-creating the exact bug TODO #50 fixed. **Verify a plan's
   claims against live code before implementing them.**
2. It gave the VVIX fetch as a straight yfinance pull. True, but yfinance returns **^VVIX in New York
   time and ^VIX in Chicago time**, so a naive join matches ZERO bars and silently writes nothing. The
   shipped code aligns on the calendar date.

Everything below is the plan **as generated** (F1–F3 included, for the record).

---

# Build Plan: 10-Feature Selection (Menu-Top10 Pass 4)

**Status:** FINAL SELECTION AND PLAN  
**Selection date:** 2026-07-14  
**Candidates evaluated:** 12 (10 selected, 2 killed)  
**Build order:** Integration-dependency ordering (fewest dependencies first)

---

## System Overview

Ten features selected from the 12-candidate pool. Two dropped by kill-test verdict. Nothing here is already built — every candidate was grepped and cross-referenced against the live codebase at `/home/openclaw/.openclaw/workspace` on 2026-07-14.

**SELECTED (10):**

- **F1** T1-a — 'Sources: N of M' footer denominator (SMALL, ~20 lines, finished feature)
- **F2** T1-b — VVIX residual, fear-of-fear gauge, DESCRIPTIVE ONLY (MEDIUM; daily writer + !market line)
- **F3** T1-c — !sweep watchlist-wide on-demand command (MEDIUM, finished feature)
- **F4** T2-a — hedge-vs-directional options-flow classifier (MEDIUM; ships as SHADOW LOG ONLY this run — live alert untouched per hard rule 6)
- **F5** T2-b — generalize the crowding guard (SMALL — reuses existing generic mechanism; no flag flip, #67 owns the blast-radius measurement per hard rule 5)
- **F6** T2-c — Brier/calibration report: systemd timer + Discord sink (SMALL; metrics already exist)
- **F7** c102 — short-alert squeeze-risk guard (SMALL; the short-interest data leg has shipped, the guard is unbuilt)
- **F8** T2-d — analyst price-target spread logger (SCAFFOLDING/LOGGER, not a signal — zero stored history exists today)
- **F9** T3-a — SEC XBRL company-facts fundamentals feed (HEAVY: new client + table + display consumer)
- **F10** T3-c — backtest-to-live decay tracker (MEDIUM-HEAVY: baseline table + nightly compare + #errors alert)

**DROPPED (kill-test verdicts):**

- **T3-b FOMC hawk/dove statement reader** — Dropped on cost/benefit, not on duplication: 8 statements per year, zero per-ticker attribution, requires a new fetcher + LLM stance parser + stance persistence table, and FOMC already drives an alert blackout (`data/macro_events.yaml` → `analysis/contradiction.py`). Lowest output-per-line on the menu.

- **T3-d learned (continuous) signal weights** — The old gate (needs the 0–100 score) is gone; the score is live. But the real gate — outcome-data volume — is owned by #67/#73 (the Friday outcome-data backfill work). `eval/report.py:286-366` already fits logistic-regression coefficients with a ticker embargo, but that function only runs offline; persisting and serving those weights in live inference is a blast-radius change that belongs with the auto-flip engine overhaul (#67), not here. Explicitly NOT dropped as "already built" — it is unbuilt, just mis-sized for this run.

**HONEST SIZING (per hard rule 8):**
- F8 is a logger (start collecting spreads now, signal deferred — no history exists)
- F4 ships as a shadow log, not a live discount
- F5 is a config-map extension, not a build (the dedup mechanism at `cross_reference.py:237-256` is already generic; only the default map is social-only)
- F9 and F10 are the two heavy builds
- **Split: 6 finished features (F1, F2, F3, F6, F7, F9), 1 config extension (F5), 2 loggers/shadow scaffolding (F4, F8), 1 tracker that grows in value with forward data (F10)**

**Evidence that nothing is a rebuild:**
- Zero `vvix` hits in `consensus_engine/` or `config/consensus.yaml`
- Zero `sweep`/`universe` hits in `alerts/commands.py`
- Zero `xbrl`/`hawkish`/`dovish` hits repo-wide
- `grep 'target_mean' consensus_engine/db.py` = zero (no persistence today)
- No calibration `.timer`/`.service` in `scripts/` or `/etc/systemd/system/`
- `consensus_engine/cross_reference.py:1799-1812` uses `days_to_cover` ONLY as a bullish +3 term (returns 0 unless direction=='long'), so no short-side guard exists
- `models.py:254 ScoreBreakdown` has no `squeeze_risk` field

**PATH NOTE (verified):** the scorer is `consensus_engine/cross_reference.py`, NOT `consensus_engine/analysis/cross_reference.py`. All line numbers below refer to the top-level module.

---

## Component Architecture

### F1 — footer denominator

**Files touched:** `consensus_engine/alerts/all_command/aggregator.py`, `consensus_engine/alerts/all_command/embed.py`

**The job:**
- `aggregator.py:501-529` builds `_classify_items` (27 (label, value) pairs) → `_classify_sources()` → `sources_surfaced`. Add `sources_total = len(_classify_items)` and pass it to the embed builder.
- `embed.py:862` `build_embed(..., sources_used: list[str], ...)` → add keyword `sources_total: Optional[int] = None`. Patch BOTH footer branches at `:1129-1134`.
- Flag: `features.sources_denominator.enabled` (default false). OFF → `f"Sources: {n}"` byte-identical.
- **Honest-denominator safeguard:** the numerator counts sources that RETURNED data; the denominator counts sources ATTEMPTED. Label reads `Sources: N of M attempted` so it never claims 27 sources 'looked and disagreed'. M is derived at runtime from `len(_classify_items)` — never a literal.

### F2 — VVIX residual (descriptive)

**Files touched:** `consensus_engine/db.py` (SCHEMA), `scripts/market_daily.py`, `consensus_engine/analysis/market_panel.py`, `alerts/commands.py`

**The job:**
- **Producer:** `scripts/market_daily.py` (already the daily writer, `/etc/systemd/system/market_daily.timer`). New `build_vvix_rows()` alongside `build_macro_rows()` (:458) + a seed() insert.
- **Fetch:** yfinance DIRECTLY for `^VVIX` and `^VIX`, `period='3y'` — NOT `consensus_engine/utils/prices.fetch_history`, because `schwab_client.py:283` rewrites `^VIX` → `$VIX` and Schwab index symbology for VVIX is unverified.
- **Math:** PORTED, not re-derived, from the sibling `/home/openclaw/wt-reliability-hardening/volatility_regime_reversal_indicator/src/signals/conditions_phase2.py:65-73 + src/features/utils.py` rolling_ols_residual/trailing_percentile: residual = rolling-252 OLS residual of log(VVIX) on log(VIX); score = trailing_percentile(residual, 252). Needs ~504 trading days to warm up — that is why it lives in the DAILY writer with a 3y history pull, not a request-time fetch.
- **Store:** new table `vol_of_vol_daily`. **Consumer:** `consensus_engine/analysis/market_panel.py:29` allowlist += `'vol_of_vol_daily'`; `alerts/commands.py` `_build_market_embed` (:1973) adds ONE descriptive field when `features.vvix_residual.enabled`.
- **HARD CONSTRAINT:** no term in `score_ticker`, no alert gate. Unit test asserts the score breakdown is identical with the flag ON.

### F3 — !sweep

**Files touched:** `alerts/commands.py`

**The job:**
- Dispatch table (:397-578; `!scan` lives at :406-411 — untouched). Add `elif command in ("sweep", "universe")` → `_handle_sweep()`; add a help line in `_build_help_embed()` (:277).
- **Universe** = `db.get_active_tickers(min_signals=1)` (db.py:1586) + `cfg.get("options_flow.fixed_core", [])` (the same union `main.py:_run_options_flow_scan` uses), deduped, capped by `features.sweep.max_tickers` (default 25).
- **Per ticker:** `cross_reference.score_ticker(ticker, executor=None)` (:1414 — the tweetless scorer), bounded concurrency (asyncio.Semaphore, default 4), per-ticker failures skipped. Post ONE ranked embed (top 10 by breakdown.total) via `send_command_embed_reply`.
- **Flag:** `features.sweep.enabled` (default false) → command replies 'disabled' when OFF.

### F4 — options-flow hedge/directional classifier (shadow only)

**Files touched:** `consensus_engine/models.py`, `consensus_engine/scanners/options.py`, new `consensus_engine/scanners/flow_hedge.py`, new `scripts/flow_hedge_shadow_review.py`

**The job:**
- `scanners/options.py:312` `_scan_chain_for_flow` already reads the chain rows; `_side_rows` (:687-746) proves per-leg Schwab delta is fetched. Add `delta: Optional[float] = None` to `models.FlowHit` (:347), populated when the column exists (yfinance path → None).
- **New module** `consensus_engine/scanners/flow_hedge.py`: `classify(hits) -> list[dict]` computing (a) delta-weighted notional = premium_usd * |delta|, and (b) leg pairing within one scan cycle (same ticker + same expiry + opposite side + notional within a config ratio → 'paired/likely hedge or spread'); emits a `flow_shadow` log line per hit.
- **Sink:** log lines only + `scripts/flow_hedge_shadow_review.py`, copying the parse-and-compare shape of `scripts/score_shadow_review.py`.
- **format_flow_alert** (options.py:506-521) is NOT modified this run. **Flag:** `features.flow_hedge_discount.collect` (default false) turns the shadow log on; `features.flow_hedge_discount.enabled` exists but is unused until the shadow review passes.

### F5 — crowding guard generalization

**Files touched:** `consensus_engine/cross_reference.py`, `config/consensus.yaml`

**The job:**
- `consensus_engine/cross_reference.py:237-256`. The guard already reads its family map from config (`features.social_family_dedup.families`) and is generic over breakdown keys. **Generalization** = (a) a new flag `features.crowding_guard.enabled` that ORs with the existing social flag, (b) a DEFAULT family map extended past the retail crowd (e.g. youtube_* → 'video_crowd'), (c) keep demotion-only. ~15-25 lines + tests.
- **NO flag flip and NO decision_snapshots blast-radius measurement** — that is #67's job (`config/consensus.yaml:870` comment).

### F6 — calibration report timer + Discord sink

**Files touched:** `consensus_engine/eval/report.py`, new `scripts/calibration_report.py`, new `scripts/calibration-report.service` and `.timer`

**The job:**
- `consensus_engine/eval/report.py:687` `run(db_path, out_path)` already returns the sections dict (verified by running the CLI). Add `format_discord(sections) -> str` in report.py (no changes to `eval/metrics.py`).
- **New script** `scripts/calibration_report.py`: calls `report.run()` read-only, formats, posts via `consensus_engine.alerts.discord.send_message` to `ops_alert.errors_channel_id()` (`alerts/ops_alert.py:59`) — the same asyncio.run() sink shape `scripts/schwab_reauth_check.py:71-114` uses. `--dry-run` prints instead of posting.
- **New systemd units:** `scripts/calibration-report.service` + `.timer`, User=openclaw, Type=oneshot, WorkingDirectory=/home/openclaw/.openclaw/workspace, OnCalendar weekly — copied from `scripts/iv-snapshot-daily.{service,timer}`.
- Suppress the numeric Brier and print the raw ratio when resolved n<10. **Flag:** `features.calibration_report.enabled` (default false) → the script exits 0 without posting.

### F7 — short-alert squeeze-risk guard (c102)

**Files touched:** `consensus_engine/models.py`, `consensus_engine/cross_reference.py`

**The job:**

**RISK CALLOUT (single DB read):** `consensus_engine/cross_reference.py:1799-1812` already does `latest_si = await db.get_latest_finra_short_interest(ticker)` inside the r12 days-to-cover block — but ONLY when `features.short_interest.enabled` is true, and that flag is currently FALSE (`consensus.yaml:879`; `collect:true` is what fills the table). So: widen the ONE existing read's condition to `short_interest.enabled OR short_squeeze_guard.enabled` and compute BOTH legs from that SAME `latest_si` row. **Do NOT add a second get_latest_finra_short_interest call** — a second read doubles hot-path DB traffic on every scored short and can disagree with the row the bullish leg just used.

- New `_compute_squeeze_risk_pts(si_row, *, direction)` next to `_compute_days_to_cover_pts` (:328-362): returns a NEGATIVE capped term only when direction == 'short' AND days_to_cover >= min AND short interest is rising.
- `models.py:254 ScoreBreakdown += squeeze_risk: int = 0`, added into `total` (:274-279).
- **Flag:** `features.short_squeeze_guard.enabled` (default false); when OFF nothing is called and the breakdown is byte-identical. Data comes from `features.short_interest.collect` (already true).

### F8 — analyst target-spread logger (scaffolding)

**Files touched:** `consensus_engine/db.py` (SCHEMA), new `scripts/target_spread_daily.py`, new `.service`/`.timer`

**The job:**
- `scanners/snapshot.py:177-210` `fetch_ticker_snapshot` already returns target_mean/high/low/n_analysts from yfinance .info. Nothing persists them (grep 'target_mean' `consensus_engine/db.py` = 0 hits).
- **New script** `scripts/target_spread_daily.py` (+ `.service`/`.timer`): for each active ticker, call `fetch_ticker_snapshot`, compute spread = (high-low)/mean, INSERT OR REPLACE into `analyst_target_spreads`. Deliberately a daily script, NOT a hot-path hook — zero risk to !all.
- **Flag:** `features.target_spread.collect` (default false). No signal, no display, no score this run.

### F9 — SEC XBRL fundamentals (heavy)

**Files touched:** new `consensus_engine/scanners/sec_xbrl.py`, `consensus_engine/db.py` (SCHEMA), new `scripts/sec_xbrl_daily.py`, `consensus_engine/alerts/all_command/embed.py`

**The job:**

**RISK CALLOUT (reuse the existing CIK map):** `scanners/sec_edgar.py:30-37` already loads and in-memory-caches SEC's full company_tickers.json ticker→CIK map, and already carries a compliant User-Agent (`_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"`, sec_edgar.py:22). **New module** `consensus_engine/scanners/sec_xbrl.py` IMPORTS that resolver and that UA — do NOT build a second CIK map (two maps can resolve the same ticker differently).

- **Fetch:** GET `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (free, UA required).
- **RISK CALLOUT (revenue tag):** parse `RevenueFromContractWithCustomerExcludingAssessedTax` and `RevenueFromContractWithCustomerIncludingAssessedTax` as well as `us-gaap/Revenues` — many filers (plausibly including NVDA) report revenue ONLY under the RevenueFromContractWithCustomer* variants, so anything hard-coded to Revenues can come back empty/404 on a perfectly healthy filer. Also parse NetIncomeLoss, EarningsPerShareDiluted, Assets, Liabilities → last 8 quarterly points; compute YoY revenue growth + net margin.
- **Store:** new table `company_fundamentals`. **Consumer:** ONE display line on the !all card next to the existing analyst/snapshot block (`embed.py:551-555` region), gated by `features.sec_xbrl.enabled` (default false).
- **Rate limit:** SEC allows 10 req/s; the fetcher caches per ticker for 24h and runs from a daily script (`scripts/sec_xbrl_daily.py`), never on the !all hot path.

### F10 — backtest-to-live decay tracker (medium-heavy)

**Files touched:** `consensus_engine/db.py` (SCHEMA), new `scripts/signal_decay_check.py`, new `.service`/`.timer`

**The job:**
- **New table** `signal_baselines` (one row per signal_key: reference hit-rate, n, source, frozen_at).
- **New script** `scripts/signal_decay_check.py` (+ `.service`/`.timer`, daily): for each signal_key, compute the trailing-60d LIVE hit rate from `decision_snapshots` (3,791 rows, 3,706 with `outcome_price_24h` — verified) and `options_flow_outcomes`; compare to the stored baseline with a Wilson lower bound; when the live LB falls below baseline by more than `features.decay_tracker.tolerance`, post ONE #errors note via `alerts/ops_alert` (transition-only + flap guard, so it can't spam).
- Report the raw ratio, never a %, when live n < 10. **Flag:** `features.decay_tracker.enabled` (default false); the tracker NEVER un-flips a flag — it only reports.

---

## Data Flow Pipeline

**F1:** `!all NVDA` → `aggregator.gather` (aggregator.py:501-529 classify) → sources_surfaced + sources_total(=len(_classify_items)) → `embed.build_embed(:862)` → footer at :1129-1134 → Discord.

**F2:** `market_daily.timer` (daily) → yfinance ^VVIX/^VIX 3y → rolling-252 OLS residual + 252d trailing percentile → `vol_of_vol_daily` row → `!market` → `market_panel.get_latest_row('vol_of_vol_daily')` → one descriptive field. No path into score_ticker.

**F3:** user types `!sweep` → `commands._route_command_inner` → `_handle_sweep` → `db.get_active_tickers` + `options_flow.fixed_core` → semaphore-bounded `score_ticker` per ticker → ranked embed → Discord reply.

**F4:** existing flow loop (`main.py:_run_options_flow_scan`) → `scan_options_flow` → FlowHit(+delta) → `flow_hedge.classify()` → shadow LOG line → `scripts/flow_hedge_shadow_review.py` compares 'would-discount' vs actual `options_flow_outcomes`. The live alert (`format_flow_alert`) is emitted unchanged, in parallel.

**F5:** `score_ticker` → breakdown dict → family-collapse pass (`cross_reference.py:237-256`) with the extended map → breakdown. Flag OFF → untouched dict.

**F6:** `calibration-report.timer` → `scripts/calibration_report.py` → `eval.report.run(db, out)` (read-only) → `format_discord` → `send_message(#errors)`.

**F7:** `score_ticker(direction='short')` → the ONE widened short-interest block (`cross_reference.py:1799-1812`) → that SAME latest_si row → `_compute_squeeze_risk_pts` → `breakdown.squeeze_risk` (negative) → total → precision engine → alert band.

**F8:** `target-spread.timer` → `scripts/target_spread_daily.py` → `snapshot.fetch_ticker_snapshot` per active ticker → `analyst_target_spreads` rows. Dead end by design (no consumer yet).

**F9:** `sec-xbrl.timer` → `scanners/sec_xbrl.py` (sec_edgar's cached CIK map + UA) → `data.sec.gov companyfacts` → `company_fundamentals` rows → `!all embed` reads the latest row → one line.

**F10:** `signal-decay.timer` → `scripts/signal_decay_check.py` → `decision_snapshots` + `options_flow_outcomes` trailing-60d rates vs `signal_baselines` → `ops_alert.report_ops_state` → #errors (transition-only).

---

## Data Structures

### New Tables (all via db.SCHEMA, CREATE TABLE IF NOT EXISTS; producers idempotent with INSERT OR REPLACE, mirroring scripts/market_daily.py:646-690)

**vol_of_vol_daily** (F2)
```
date_utc TEXT PRIMARY KEY, vvix_close REAL, vix_close REAL,
vvix_vix_ratio REAL, residual REAL, residual_pct_252 REAL,  -- NULL until 504 bars warm up
computed_at REAL NOT NULL
```

**analyst_target_spreads** (F8)
```
ticker TEXT NOT NULL, date_utc TEXT NOT NULL, target_mean REAL, target_high REAL,
target_low REAL, n_analysts INTEGER, spread_pct REAL, computed_at REAL NOT NULL,
PRIMARY KEY (ticker, date_utc)
```

**company_fundamentals** (F9)
```
ticker TEXT NOT NULL, cik TEXT, period_end TEXT NOT NULL, fiscal_period TEXT,
revenue REAL, revenue_tag TEXT,  -- which us-gaap tag the revenue came from (Revenues vs RevenueFromContractWithCustomer*)
net_income REAL, eps_diluted REAL, assets REAL, liabilities REAL,
revenue_yoy REAL, net_margin REAL, source TEXT DEFAULT 'sec_xbrl', fetched_at REAL NOT NULL,
PRIMARY KEY (ticker, period_end)
```

**signal_baselines** (F10)
```
signal_key TEXT PRIMARY KEY, baseline_rate REAL NOT NULL, baseline_n INTEGER NOT NULL,
horizon TEXT NOT NULL, source TEXT NOT NULL,  -- 'backtest' | 'first-90d-live'
frozen_at REAL NOT NULL
```

### Changed In-Memory Structures

- **models.FlowHit** (models.py:347): + `delta: Optional[float] = None` (F4)
- **models.ScoreBreakdown** (models.py:254-279): + `squeeze_risk: int = 0`, included in `total` (F7)
- **embed.build_embed** (embed.py:862): + `sources_total: Optional[int] = None` (F1)

### No Existing Columns Dropped or Renamed

`market_panel` allowlist (market_panel.py:29) gains one entry: `'vol_of_vol_daily'`.

---

## Integration Plan

**Order:** cheapest first, each step independently verifiable and committable.

1. **F1** (2 files: aggregator.py, embed.py + flag + test). Smallest diff on the menu.
2. **F7** (models.py + cross_reference.py + flag + test) — widens the ONE existing short-interest DB read; no second read.
3. **F5** (cross_reference.py family map + flag + test). Coordinate with #67: NO flag flip, NO decision_snapshots blast-radius measurement here.
4. **F6** (eval/report.py format_discord + scripts/calibration_report.py + units). Zero changes to eval/metrics.py.
5. **F3** (commands.py: dispatch entry + _handle_sweep + help line; flag). No change to !scan.
6. **F2** (db.py SCHEMA + scripts/market_daily.py builder/seed + market_panel allowlist + commands._build_market_embed line + flag). Read VVIX-RESEARCH-FINDINGS.md (main workspace copy: `/root/.openclaw/workspace/.claude/discover/next-features-jul2026/VVIX-RESEARCH-FINDINGS.md` — it is NOT in this worktree) AND the sibling `src/signals/conditions_phase2.py` + `src/features/utils.py` before writing a line; port the formula, do not re-derive.
7. **F8** (db.py SCHEMA + scripts/target_spread_daily.py + units + collect flag). Logger only.
8. **F4** (models.py delta field + options.py delta capture + new scanners/flow_hedge.py + scripts/flow_hedge_shadow_review.py + collect flag). format_flow_alert untouched — a test asserts its output is byte-identical for a fixed FlowHit.
9. **F10** (db.py SCHEMA + scripts/signal_decay_check.py + units + flag; baselines seeded from stored outcomes).
10. **F9** (scanners/sec_xbrl.py reusing sec_edgar's CIK map + UA, db.py SCHEMA + scripts/sec_xbrl_daily.py + units + one embed.py line + flag). Heaviest; last.

### Config: Features Block

One new block per feature in `config/consensus.yaml` under `features:`, every boolean default false. Adding an OFF flag does not trip `scripts/flag_flip_gate.py` (it blocks only OFF→ON diffs); flipping any of them ON later requires `.claude/go-live-evidence/<flag_with_underscores>.md`.

### Systemd Units

New units live in `scripts/` (repo) then install to `/etc/systemd/system` as User=openclaw, matching `iv-snapshot-daily`. Verify file ownership after the first run ([infra] bucket).

---

## Failure Handling

**Universal:** every new flag defaults false and the OFF path must be byte-identical (unit test per feature; conftest already force-offs flipped audit flags).

**F1:** sources_total None (old callers) → render the old bare-count string. Never render 'N of 0'.

**F2:** yfinance failure, empty frame, or <504 aligned bars → residual_pct_252 stays NULL and the !market field is OMITTED — never 0.0/1.0 masquerading as data. Stale row (>3 trading days old) → omitted. Explicitly avoids prices.fetch_history so the Schwab index-symbol rewrite (schwab_client.py:283) cannot silently reshape ^VVIX.

**F3:** per-ticker score_ticker exception → that ticker is skipped and named in the embed footer ('3 of 25 failed'); a hard cap (max_tickers, default 25) and a semaphore (4) bound Discord/yfinance load; empty watchlist → 'nothing active right now'.

**F4:** missing delta (yfinance path) → hit is logged as 'delta_unknown', never guessed. Classifier exceptions are caught and logged; the live alert path cannot be affected because it does not call the classifier.

**F5:** unknown breakdown key in the family map → ignored. Demotion-only: the guard can zero a term, never add one.

**F6:** if eval.report.run() itself raises (not just a missing channel) → log the full traceback, post NOTHING, and exit NON-ZERO so systemd marks the unit failed and the OnFailure=alert@%n.service path fires. A swallowed exception would make the weekly report silently vanish with no journal signal. Missing channel id → ops_alert.errors_channel_id() fallback chain; if still empty, log and exit non-zero rather than swallow. Resolved n<10 → print the raw ratio, no Brier number.

**F7:** flag on but no FINRA row, a stale row (recency_window 'short_interest' = 43200 min), or a missing days_to_cover → 0 points (no penalty invented from nothing). If BOTH short_interest.enabled and short_squeeze_guard.enabled are false → zero DB reads, exactly as today.

**F8:** yfinance .info missing targets → no row written for that ticker that day (gaps are honest).

**F9:** SEC 403 (bad/missing User-Agent) / 404 (no CIK) / all revenue tags absent → skip the ticker, log once with the tag names tried; 24h cache prevents hammering; hard 10 req/s ceiling.

**F10:** baseline missing for a signal_key → no comparison (never alerts on an empty baseline); live n<30 → report 'insufficient', no alert; ops_alert's transition-only + flap guard prevents daily repeats. The tracker never writes a flag.

---

## Feature Activation Plan

All ten ship **FLAG-OFF** (project rule + hard rule 2). Three activation classes:

### Class A: Safe to flip after probe passes (display-only / no alert change)

**F1** (sources_denominator.enabled), **F2** (vvix_residual.enabled, descriptive only, byte-identical score proven), **F3** (sweep.enabled, a new command that changes no existing output), **F6** (calibration_report.enabled, posts to #errors), and **F9** (sec_xbrl.enabled, display-only; folding fundamentals into the score is explicitly out of scope).

For every class-A flip: the pasted REAL probe output IS the go-live evidence — write it into `.claude/go-live-evidence/<flag_with_underscores>.md` AT FLIP TIME (e.g. `.claude/go-live-evidence/features_sources_denominator_enabled.md`), so `scripts/flag_flip_gate.py` passes at push with no second evidence-writing pass.

### Class B: Collect-first, flip later (forward data owed)

**F4** (features.flow_hedge_discount.collect ON in a later session after review; .enabled stays OFF until `scripts/flow_hedge_shadow_review.py` shows the discount would have improved options_flow_outcomes), **F8** (features.target_spread.collect; the signal cannot be built until months of analyst_target_spreads rows exist — no history exists today, grep-verified), **F10** (features.decay_tracker.enabled after baselines are frozen and a week of dry-runs is sane).

**NOTE (per project rules):** collect flags default OFF, but the short_interest precedent (yaml:879 collect:true) shows the pattern: collect flags go ON at merge + mandatory engine restart + forward data accrues. For F4, F8, F10: the collect step is the proof that the infrastructure works; the signal/report comes later when history is rich enough.

### Class C: Score-touching, needs blast-radius evidence

**F5** (crowding guard: the flip is #67's decision_snapshots measurement — DO NOT flip here), **F7** (short-squeeze guard: demotes SHORT alerts, so it needs a shadow comparison of scored short signals before ON).

**Nothing in this plan flips an existing flag.** `features.short_interest.collect` is already true (consensus.yaml:879), which is why F7's data exists even though `features.short_interest.enabled` is false.

---

## Verification Checklist

1. **Baseline first:** `python3 -m pytest tests/ -q` and diff against `.test-baseline` (known failure: `tests/test_i13_apewisdom_zscore.py::test_baseline_two_days_std`). No new failure may appear.

2. **Per-feature OFF-path test:** with the flag false, the changed surface is byte-identical (footer string, score breakdown, flow alert text, !market embed, !all embed).

3. **Dependent grep before EACH commit:** `grep -rn` the changed symbol/output string across `tests/` and run every match. **Specifically required this run:** `grep -rn 'FlowHit(' tests/` and `grep -rn 'ScoreBreakdown(' tests/` — BOTH dataclasses gain a field, and the hidden breakage lives in fixtures / monkeypatch stubs that construct them POSITIONALLY. Also grep `build_embed(`, `'Sources: '`, and `_classify_items`.

4. **Assert the F1 denominator is derived at runtime** as `len(_classify_items)` and that the literal `27` appears NOWHERE in the diff.

5. **Run each feature's probe** (below) and paste the REAL output; no 'code looks right' claims.

6. **flag_flip_gate:** `python3 scripts/flag_flip_gate.py` must pass — all new flags are additions in the OFF state, no OFF→ON diff. For any same-session class-A flip, the matching `.claude/go-live-evidence/<flag>.md` must already contain the pasted probe output.

7. **Scoped critical-path buckets** from the changed paths: [always] (consensus-engine + openclaw-gateway active, no GATEWAY drift, /root/.openclaw resolves), [discord-commands] (!all NVDA and !sweep return coherent replies — F1/F2/F3/F9 touch alerts/**), [ingest] (one real poll of the options-flow loop after the F4 delta change lands sane rows/log lines), [infra] (new timers run clean under systemd as openclaw; `ls -l` shows openclaw ownership after the first run).

8. **Separate verifier agent** re-runs the full suite at the end and diffs the baseline (Regression Gate).

---

## Feature Probes

### F1: Sources: N of M footer denominator

**Probe:**
```bash
python3 - <<'PY'
import asyncio
import consensus_engine.config as cfg
from consensus_engine.alerts.all_command import aggregator, embed

_real_get = cfg.get

# Mock the flag to ON
def mock_get(k, d=None):
    return True if k == 'features.sources_denominator.enabled' else _real_get(k, d)

cfg.get = mock_get
ctx = asyncio.run(aggregator.gather('NVDA'))  # real DB + real live sources
e = embed.build_embed(**ctx)                   # exact kwargs per the real call site
print('ON  footer:', e['embeds'][0]['footer']['text'] if 'embeds' in e else e['footer']['text'])

cfg.get = _real_get
e2 = embed.build_embed(**ctx)
print('OFF footer:', e2['embeds'][0]['footer']['text'] if 'embeds' in e2 else e2['footer']['text'])
PY
```

Then independently verify:
- The ON footer reads `Sources: N of 27 attempted` (27 is from len(_classify_items))
- The OFF footer is the exact old string `Sources: N` (byte-identical)
- The rendered Discord footer matches the ON string
- `git diff | grep -n '27'` returns no literal 27

**Expected evidence:** ON and OFF strings as shown above; rendered Discord embed pasted; git diff grep confirming no hard-coded 27.

---

### F2: VVIX residual fear-of-fear gauge, descriptive only

**Probe:**
```bash
# 1) Run the daily writer
python3 scripts/market_daily.py --db /tmp/vvix_probe.db --dry-run
python3 scripts/market_daily.py --db /tmp/vvix_probe.db  # real run
sqlite3 /tmp/vvix_probe.db 'select * from vol_of_vol_daily order by date_utc desc limit 1'

# 2) Independently recompute spot checks
python3 -c "
import yfinance as yf
v = yf.Ticker('^VVIX').history(period='3y')['Close']
x = yf.Ticker('^VIX').history(period='3y')['Close']
print('VVIX', v.iloc[-1], 'VIX', x.iloc[-1], 'ratio', v.iloc[-1]/x.iloc[-1], 'bars', len(v))
"

# 3) Render the panel
python3 - <<'PY'
import asyncio
import consensus_engine.config as cfg
from consensus_engine.alerts import commands

cfg.get = lambda k, d=None: True if k == 'features.vvix_residual.enabled' else cfg.get(k, d)
embed = asyncio.run(commands._build_market_embed())  # real snapshot
print('VVIX line:', [f for f in embed.get('fields', []) if 'vvix' in f.get('name', '').lower()])
PY

# 4) Score identity check
python3 - <<'PY'
import asyncio
from consensus_engine import cross_reference
import consensus_engine.config as cfg

async def test():
    for enabled in [False, True]:
        cfg.get = lambda k, d=None: enabled if k == 'features.vvix_residual.enabled' else cfg.get(k, d)
        r = await cross_reference.score_ticker('NVDA')
        print(f'Flag {enabled}: breakdown={repr(r.breakdown)}')

asyncio.run(test())
PY
```

**Expected evidence:** Real vol_of_vol_daily row with vvix_close/vix_close matching raw ^VVIX/^VIX spots; residual_pct_252 in (0,1] or NULL (if <504 bars, stated honestly); rendered !market field; two ScoreBreakdown reprs identical character-for-character (VVIX never touches score).

---

### F3: !sweep watchlist-wide on-demand command

**Probe:**
```bash
# Enable flag and drive the handler
python3 - <<'PY'
import asyncio
import os
import consensus_engine.config as cfg
from consensus_engine.alerts import commands

# Mock the flag to ON
_real = cfg.get
cfg.get = lambda k, d=None: True if k == 'features.sweep.enabled' else _real(k, d)

CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
MESSAGE_ID = int(os.getenv('DISCORD_MESSAGE_ID', '0'))

asyncio.run(commands._handle_sweep(CHANNEL_ID, MESSAGE_ID))
PY

# Independently verify !scan still works
python3 - <<'PY'
import asyncio
from consensus_engine.alerts import commands

CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
asyncio.run(commands._handle_scan(['NVDA'], CHANNEL_ID))
PY
```

**Expected evidence:** One real Discord embed listing ranked watchlist tickers (top 10) with 0-100 scores and failure names in footer; !scan still returning single-ticker verdict unchanged.

---

### F4: hedge-vs-directional options-flow classifier (shadow log only; live alert untouched)

**Probe:**
```bash
python3 - <<'PY'
import asyncio
from consensus_engine.scanners.options import scan_options_flow, format_flow_alert
from consensus_engine.scanners import flow_hedge

hits = asyncio.run(scan_options_flow(['NVDA','AMD','SPY','TSLA'], executor=None, use_schwab=True))
rows = flow_hedge.classify(hits)
for r in rows:
    print(f"{r['ticker']} {r['side']} prem={r['premium_usd']:.0f} delta={r['delta']} dw_notional={r.get('delta_weighted_notional', 0):.0f} verdict={r['verdict']}")

if hits:
    print('format_flow_alert output:', format_flow_alert(hits[0]))
else:
    print('no hits')
PY
```

Compare that alert text to the text produced by the same FlowHit on origin/master.

**Expected evidence:** Real shadow rows showing populated Schwab delta, delta-weighted notional, verdict (directional vs paired/hedge); format_flow_alert output byte-identical to master for the same hit.

---

### F5: generalized crowding guard

**Probe:**
```bash
python3 - <<'PY'
import asyncio
import consensus_engine.config as cfg
from consensus_engine import cross_reference
import sqlite3

db_path = '/root/.openclaw/workspace/consensus.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
select ticker, count(*) from ticker_signals
where expires_at > strftime('%s', 'now')
group by ticker order by 2 desc limit 5
""")
high_signal_ticker = cursor.fetchone()[0] if cursor.fetchone() else 'NVDA'

async def test(flag1, flag2):
    _real = cfg.get
    def mock_get(k, d=None):
        if k == 'features.social_family_dedup.enabled': return flag1
        if k == 'features.crowding_guard.enabled': return flag2
        return _real(k, d)
    cfg.get = mock_get
    r = await cross_reference.score_ticker(high_signal_ticker)
    return repr(r.breakdown)

print('OFF/OFF:', asyncio.run(test(False, False)))
print('ON/OFF:', asyncio.run(test(True, False)))
print('OFF/ON:', asyncio.run(test(False, True)))
PY
```

**Expected evidence:** Run OFF/OFF equals the pre-change master output exactly; run OFF/ON shows duplicate family members zeroed and total LOWER than OFF/OFF (demotion-only, never higher); no key outside the family map is touched.

---

### F6: Brier/calibration report: weekly timer + Discord sink

**Probe:**
```bash
# 1) Dry run
python3 scripts/calibration_report.py --dry-run

# 2) Cross-check against manual run
python3 -m consensus_engine.eval --db /root/.openclaw/workspace/consensus.db --out /tmp/eval_probe.md
# Compare the Brier numbers to the dry-run output

# 3) Post for real and fetch the message
python3 scripts/calibration_report.py
# Then fetch the message from Discord using the API and show the body

# 4) Test systemd
sudo systemctl start calibration-report.service
systemctl status calibration-report.service
ls -l /root/.openclaw/workspace/calibration-report.log  # if it writes output

# 5) Test error path: corrupt DB
sqlite3 /tmp/corrupt.db '.mode line'
python3 scripts/calibration_report.py --db /tmp/corrupt.db 2>&1 | head -20
```

**Expected evidence:** Dry-run Brier values match manual eval numbers exactly; real posted message fetched from Discord and shown; systemd run exits 0 as User=openclaw; corrupt-DB run exits non-zero with logged traceback and no Discord post.

---

### F7: short-alert squeeze-risk guard

**Probe:**
```bash
python3 - <<'PY'
import asyncio
import sqlite3
import consensus_engine.config as cfg
from consensus_engine import cross_reference, db as db_module

# Find a real high-squeeze ticker
db_path = '/root/.openclaw/workspace/consensus.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
select ticker, days_to_cover, pct_change from finra_short_interest
where days_to_cover >= 3 and pct_change > 0
order by published_at desc limit 1
""")
ticker, days, pct = cursor.fetchone() or ('NVDA', 5, 0.1)

async def test_squeeze():
    _real = cfg.get
    
    # Test with flag OFF
    cfg.get = lambda k, d=None: False if 'squeeze_guard' in k else _real(k, d)
    r_off = await cross_reference.score_ticker(ticker, direction='short')
    
    # Test with flag ON
    cfg.get = lambda k, d=None: True if k == 'features.short_squeeze_guard.enabled' else _real(k, d)
    r_on = await cross_reference.score_ticker(ticker, direction='short')
    
    # Also test long direction with flag ON
    r_long = await cross_reference.score_ticker(ticker, direction='long')
    
    print('OFF breakdown:', r_off.breakdown)
    print('ON breakdown:', r_on.breakdown)
    print('LONG breakdown:', r_long.breakdown)
    print('Short ON total - Short OFF total:', r_on.breakdown.total - r_off.breakdown.total)

asyncio.run(test_squeeze())
PY
```

**Expected evidence:** Flag OFF equals master output exactly; flag ON with real high-days-to-cover rising-short row shows squeeze_risk is negative and SHORT total drops; direction=long shows squeeze_risk stays 0; no duplicate DB reads.

---

### F8: analyst price-target spread logger

**Probe:**
```bash
python3 scripts/target_spread_daily.py --db /tmp/spread_probe.db --tickers NVDA,AMD,MU
sqlite3 /tmp/spread_probe.db 'select ticker, date_utc, target_mean, target_low, target_high, n_analysts, spread_pct from analyst_target_spreads'

# Cross-check against !all card
python3 - <<'PY'
import asyncio
from consensus_engine.alerts.all_command import embed
from consensus_engine import cross_reference

async def check():
    for ticker in ['NVDA', 'AMD']:
        r = await cross_reference.score_ticker(ticker)
        print(f'{ticker} snapshot targets:', r.catalyst_summary[:100])  # rough check

asyncio.run(check())
PY

# Verify we have only today's data
sqlite3 /tmp/spread_probe.db 'select count(*), min(date_utc), max(date_utc) from analyst_target_spreads'
```

**Expected evidence:** Real rows with spread_pct = (high-low)/mean; same mean/low/high as !all card shows; count/min/max returns only TODAY's date (no history exists).

---

### F9: SEC XBRL company-facts fundamentals feed

**Probe:**
```bash
# 1) Prove free endpoint works with shared resolver
python3 - <<'PY'
import asyncio
from consensus_engine.scanners import sec_xbrl, sec_edgar

# Verify we reuse sec_edgar's map
import inspect
source = inspect.getsource(sec_xbrl)
assert 'from consensus_engine.scanners import sec_edgar' in source or '_load_ticker_map' in source
print('sec_xbrl correctly imports/reuses sec_edgar resolver')

d = asyncio.run(sec_xbrl.fetch_company_facts('NVDA'))
print('CIK:', d['cik'])
ug = d['facts']['us-gaap']
print('Revenue tags present:', [t for t in ug if 'Revenue' in t])
PY

# 2) Run the daily script
python3 scripts/sec_xbrl_daily.py --db /tmp/xbrl_probe.db --tickers NVDA,AAPL
sqlite3 /tmp/xbrl_probe.db 'select ticker, period_end, revenue, revenue_tag, net_income, eps_diluted, revenue_yoy, net_margin from company_fundamentals order by period_end desc limit 6'

# 3) Render !all with flag ON
python3 - <<'PY'
import asyncio
import consensus_engine.config as cfg
from consensus_engine.alerts.all_command import embed

cfg.get = lambda k, d=None: True if k == 'features.sec_xbrl.enabled' else cfg.get(k, d)
e = asyncio.run(embed.build_embed(...))  # real NVDA ctx
print('Fundamentals line:', [f for f in e.get('fields', []) if 'fundamental' in f.get('name', '').lower()])
PY

# 4) Verify flag OFF is byte-identical
# ... (do the same with flag OFF and diff the embeds)
```

**Expected evidence:** Revenue-tag print shows which tag NVDA actually uses (expected RevenueFromContractWithCustomerExcludingAssessedTax); stored revenue_tag matches; revenue/EPS match published 10-Q figures; rendered !all line; byte-identical embed with flag OFF; grep proof that only ONE CIK map exists repo-wide.

---

### F10: backtest-to-live decay tracker

**Probe:**
```bash
# 1) Freeze baselines from stored history
python3 scripts/signal_decay_check.py --freeze-baselines --db /root/.openclaw/workspace/consensus.db --out /tmp/decay_probe.db

# 2) Dry-run the comparison
python3 scripts/signal_decay_check.py --dry-run --db /root/.openclaw/workspace/consensus.db --baselines /tmp/decay_probe.db
# Print per-signal baseline rate, trailing-60d live rate, Wilson lower bound, verdict

# 3) Force an alert (test the Discord sink and flap guard)
python3 scripts/signal_decay_check.py --force-alert some_signal_key --db /root/.openclaw/workspace/consensus.db --baselines /tmp/decay_probe.db
# Run it again immediately — should post nothing (flap guard)

# 4) Verify no flag was written
git diff config/consensus.yaml | grep -c squeeze_risk
```

**Expected evidence:** Printed table of signal_keys with baseline vs live rates and explicit DECAY/OK/INSUFFICIENT verdict; forced run posts exactly ONE #errors message; immediate re-run posts nothing (flap guard); consensus.yaml unchanged (tracker only reports).

---

## Tournament Notes

### Judge Scores and Grounded Findings

Two plans submitted:
- **Minimal-diff planner** (score 8.4): near-perfect grounding on integration points, but one defect in F1 probe (embed.build_embed can't take aggregator.gather's raw payload) and problematic activation plan (collect flags default OFF, stalling forward data).
- **Robustness-first** (score 9.2, winner): equal anchor grounding, every load-bearing number verified exact against live DB (decision_snapshots 3,791/3,706 resolved; finra_short_interest 3,835; options_flow 128,646), real-Discord end-to-end probes, activation plan follows short_interest precedent (collect ON at merge + engine restart).

**Both plans verified same candidates are unbuilt.** All integration points grepped and read in the live codebase.

### Graft Decisions (Robustness-first Winner Adopted)

1. **Risk callouts section (F9 XBRL):** Do not re-implement ticker→CIK resolution — sec_edgar.py already loads and caches company_tickers.json; a second map risks divergent resolution. Also parse RevenueFromContractWithCustomer* variants, not just us-gaap/Revenues.

2. **Risk callouts section (F7 squeeze guard):** Compute penalty from SAME latest_si row the r12 block already fetches — do not issue a second get_latest_finra_short_interest read (doubles DB traffic, can disagree).

3. **Verification checklist:** Before committing, grep -rn 'FlowHit(' and 'ScoreBreakdown(' across tests/ and run every match — dataclasses gain fields and hidden breakage lives in fixtures.

4. **Feature activation plan:** For class-A flips (F1/F2/F3/F6/F9), pasted real probe output IS the go-live evidence at flip time, so flag_flip_gate.py passes without second evidence-writing pass.

5. **Failure handling (F6 calibration report):** If eval.report.run() raises (not just missing channel), log traceback, post nothing, exit non-zero so OnFailure=alert@%n.service fires — a swallowed exception makes the report silently vanish.

6. **Collect flags (F4/F8/F10):** Default OFF, but follow short_interest precedent: turn collect ON at merge + mandatory engine restart + forward data accrues. Collect step proves infrastructure; signal/report comes later when history is rich.

---

**End of plan. Ready for Pass 5 (build execution).**
