# Audit Solutions — 2026-06-06

## How to read this

Each entry is the concrete fix for one audit finding: what to change, which files, the on/off switch (flag), whether it goes live during the run or waits for your "go" (go_live), how to test it with real data, and the risk/effort. **go_live** = whether the change flips live on by itself during the run ("live-during-run"), waits for your explicit "go" before it affects anything users see ("hold-for-signoff"), or is invisible internal plumbing/docs that never changes user output ("internal").

## Execution order

Ordered by tier. Tier 1 = highest-leverage quick wins (the `!all` speed/cost cuts, the fake-ticker block, options-channel routing). Tier 2 = the three features you asked for (Wolf short ideas, Wolf-confluence in `!all`, B3 number tagging). Tier 3 = the flag-gated YouTube-score smarts. Tier 4 = the cost lane. Tier 5 = bugfixes, missing tests, and doc fixes.

| # | Solution | Lane | Effort | Risk | go_live | Flag |
|---|---|---|---|---|---|---|
| 1 | Block fake/penny tickers on `!all` | !all build-new + presentation | S | low | hold-for-signoff | `all_command.market_cap_gate_enabled` |
| 2 | Cut the `!all` cleanup (sanitize) phase | !all token/latency cost | S | med | hold-for-signoff | `all_command.sanitize_enabled` |
| 3 | Make the `!all` sanitize phase no-LLM by default | !all token/latency cost | S | med | hold-for-signoff | `all_command.sanitize_enabled` |
| 4 | Skip the wasted groq head-start on big tickers that 413 | !all token/latency cost | S | low | live-during-run | `llm.all_command_head_start_max_tokens` |
| 5 | Route options-flow alerts to their own channel | options-flow + infra | S | low | hold-for-signoff | `api_keys.options_flow_channel_id` |
| 6 | Build the SHORT side of Wolf beneficiary inference (v1.1) | Wolf brain | M | med | hold-for-signoff | `wolf.beneficiaries.shorts_enabled` |
| 7 | Surface "Wolf + N sources agree" inside `!all` | Wolf brain | M | low | hold-for-signoff | `all_command.wolf_confluence_field_enabled` |
| 8 | Flip B3 per-number ticker tagging ON + before/after | YouTube scoring + B3 | S | low | hold-for-signoff | `youtube.visual.per_number_ticker_tagging` |
| 9 | Direction-aware YouTube score | YouTube scoring + B3 | M | med | hold-for-signoff | `features.youtube_score.direction_aware` |
| 10 | Recency decay on stale YouTube mentions | YouTube scoring + B3 | M | low | hold-for-signoff | `features.youtube_score.recency_decay` |
| 11 | Channel-reliability weighting of the YouTube boost | YouTube scoring + B3 | M | low | hold-for-signoff | `features.youtube_score.channel_reliability` |
| 12 | YouTube-level / technical-level confluence bonus | YouTube scoring + B3 | L | med | hold-for-signoff | `features.youtube_score.level_confluence` |
| 13 | Extend B3 tag into the structured youtube_levels path | YouTube scoring + B3 | M | med | hold-for-signoff | `youtube.visual.per_number_ticker_tagging` |
| 14 | Re-process recent multi-stock videos for live data | YouTube scoring + B3 | S | med | internal | — |
| 15 | Cut the ~2,800-token static synthesis instruction block | !all token/latency cost | M | med | hold-for-signoff | — |
| 16 | Skip the per-ticker confidence scorer below threshold | !all token/latency cost | M | med | internal | `scoring.skip_llm_below_threshold` |
| 17 | Per-cycle cap (8) smarter than raw premium-sort | options-flow + infra | M | med | hold-for-signoff | `options_flow.selection_mode` |
| 18 | Per-ticker "unusual" baseline instead of flat $250k/5x | options-flow + infra | M | med | hold-for-signoff | `options_flow.relative_baseline_enabled` |
| 19 | Disable Gemini thinking + cap output on Wolf chart reads | Wolf brain | S | low | internal | — |
| 20 | Add a wolf_vision budget bucket | Wolf brain | M | low | internal | — |
| 21 | Surface chart-pattern strength in `!all` | !all build-new + presentation | S | low | hold-for-signoff | — |
| 22 | Data-sparseness banner on thin tickers | !all build-new + presentation | S | low | hold-for-signoff | `all_command.sparse_banner.enabled` |
| 24 | Widen the risk-section price gate beyond the stop-loss | !all build-new + presentation | M | med | hold-for-signoff | `all_command.risk_price_gate_strict` |
| 25 | Swing horizon uses realized volatility, not raw ATR | !all build-new + presentation | M | low | hold-for-signoff | `all_command.horizon_realized_vol` |
| 26 | Guard Wolf trade-idea entry/target ordering + reject non-positive prices | Wolf brain | S | low | hold-for-signoff | — |
| 27 | Drop the two always-empty sanitize batches (searxng + sec) | !all token/latency cost | S | low | internal | — |
| 28 | Measure the synthesis retry rate from obs logs | !all token/latency cost | M | low | internal | — |
| 29 | Add missing end-to-end test for YouTube level-alert path | options-flow + infra | S | low | internal | — |
| 30 | Wolf test-gaps: short bear thesis, confluence tier-up, beneficiary freshness | Wolf brain | S | low | internal | — |
| 31 | Tradier real-time-free options feed (research → WONTFIX) | options-flow + infra | S | low | internal | — |
| 32 | Close the Wolf-echo filter as WONTFIX (corrected rationale) | Wolf brain | S | low | internal | — |
| 33 | Keep Twitter one-net-vote in Wolf confluence (argue against per-author) | Wolf brain | S | low | internal | — |
| 34 | Update stale gemini-video-eval-assertions.md status (doc-only) | options-flow + infra | S | low | internal | — |
| 35 | Reconcile dod-checklist-scope-aware.md (marked DONE) with CLAUDE.md | options-flow + infra | S | low | internal | — |

## Solutions by lane

### Lane: !all build-new + presentation

#### Block fake/penny tickers on !all
**finding (the HOW):** In `handle_all` (aggregator.py), right after the existing `is_valid_ticker_format` check passes (around line 1229, before the "Analyzing $TICKER..." reply at 1231), add one `await validate_ticker_market_cap(ticker)`. That function already exists in `consensus_engine/utils/tickers.py:144` — it reads cached DB metadata, falls back to a Finnhub profile2 lookup, and returns True only when market cap >= the $100M floor (`ticker_validation.min_market_cap`, consensus.yaml:328). On a False result, reply with a plain message like "`$FAKEX` isn't a tracked stock (unknown ticker or under the $100M size floor)." and return — skipping the entire 30-80s pipeline. Import `validate_ticker_market_cap` alongside the existing `is_valid_ticker_format` import at aggregator.py:41. Gate the whole check behind the config flag so it can be turned off if Finnhub starts misbehaving.
- Plain words: today typing `!all FAKEX` or a tiny penny stock runs the full analysis and hands back a confident-looking but empty report; this adds a quick size check up front so junk tickers get a one-line rejection in ~1s instead.
- **files:** consensus_engine/alerts/all_command/aggregator.py; config/consensus.yaml
- **flag:** `all_command.market_cap_gate_enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** (1) `!all NVDA` and `!all AAPL` (large caps already in the ticker_metadata cache) — both must proceed to the full embed unchanged. (2) `!all FAKEX` (no Finnhub profile → name='' → cached as cap 0) — must return the one-line rejection in ~1s, NOT the full embed. (3) A known sub-$100M micro-cap symbol → rejection. Verify the rejection message appears in #chat via the Discord REST read-back (token in .env.service, send a User-Agent header).
- **risk/effort:** low / S
- **open_question:** Should index/ETF tickers like SPY/QQQ (Finnhub returns 0 market cap for many ETFs) be whitelisted so the gate doesn't accidentally reject them? Need to confirm what profile2 returns for the common ETFs users actually query.

#### Surface chart-pattern strength in !all
**finding (the HOW):** The pattern detector already returns a dict like `{pattern:'bull_flag', confidence:0.72, key_level:130.5}` and stashes it at `data['chart_pattern']` (aggregator.py:347), but it only feeds the AI prompt (narrator.py:911-914) and never reaches the embed. Thread it through: (a) add a `chart_pattern: Optional[dict] = None` parameter to `build_embed` (embed.py:626); (b) pass `chart_pattern=data.get('chart_pattern')` at the build_embed call site (aggregator.py:1148-1156); (c) in `build_embed`, after the existing inline fields block (after the R:R/Rel Vol fields ~embed.py:724), append a 'Pattern' field when chart_pattern is a dict with confidence >= a small floor (e.g. 0.5). Render it human-readably: map the snake_case name ('bull_flag'→'Bull flag', 'double_bottom'→'Double bottom', 'breakout_above_n_day_high'→'Breakout') and format like `Bull flag — key $130.50 (0.72)`.
- Plain words: the bot already detects chart shapes every run but throws the result into prose only; this gives users a clean labeled field showing the pattern, its key price, and how confident the detector is.
- **files:** consensus_engine/alerts/all_command/embed.py; consensus_engine/alerts/all_command/aggregator.py
- **flag:** none
- **go_live:** hold-for-signoff
- **test (real-data):** Run `!all` on a ticker whose recent daily candles form a detectable pattern. AMD/TSLA over a runup often trigger breakout/bull_flag; double_bottom appears on names that retested a low. Run `!all AMD` and `!all NVDA`, read the embeds back from #chat via Discord REST, and confirm a 'Pattern' field renders with name+key_level+confidence when patterns.detect_all returns a hit, and is ABSENT when it returns None (a flat ticker). Also extend tests/test_all_command_chart_pattern_wiring.py with an assertion that build_embed emits a Pattern field for a sentinel pattern dict and omits it for None.
- **risk/effort:** low / S
- **open_question:** What confidence floor hides noise without hiding real signals? The detectors' confidence formulas (patterns.py:174 etc.) cap at 1.0 but start ~0.4; 0.5 is a guess — may want to surface all hits since detect_all already returns only the single best one.

#### Data-sparseness banner on thin tickers
**finding (the HOW):** The surfaced-source count is already known where the embed is built — `len(sources_surfaced)` (aggregator.py:1153/1191). Add a one-line caveat when coverage is thin. Pass `sources_count=len(sources_surfaced)` (or reuse the existing sources_used list build_embed already receives — it computes sources_count at embed.py:752) into a new banner. When sources_count <= a config threshold (default 3), prepend a banner line to the embed description (above the TL;DR), e.g. `⚠️ Low coverage — only 2 sources; trade levels are ATR-derived, treat with caution.` Build it inside build_embed using the already-present `sources` list and `_cfg.get('all_command.sparse_banner.max_sources', 3)`. Keep it purely additive (prepend to the description chunks in _assemble at embed.py:669).
- Plain words: on obscure tickers the bot still prints a full confident trade plan even when almost nothing backed it; this adds a visible 'thin data, be careful' warning so users don't over-trust a report built on 2 sources.
- **files:** consensus_engine/alerts/all_command/embed.py; config/consensus.yaml
- **flag:** `all_command.sparse_banner.enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** Pick an obscure low-coverage ticker (few/no rows in signal_events and youtube_signals — most small-caps surface only 'score' + 'technical_long', ~2-3 sources) and run `!all`; confirm the banner appears. Then `!all NVDA` (20 sources in logged runs) and confirm NO banner. Verify both via Discord REST read-back of #chat. Unit-test: feed build_embed a 2-element sources_used list → banner present; a 12-element list → banner absent. The count must be the SURFACED sources count, matching the footer 'Sources: N'.
- **risk/effort:** low / S
- **open_question:** Is the right threshold based on surfaced-source COUNT, or on whether the trade plan actually fell back to ATR levels (trade_plan reason='atr_fallback')? The audit's separate ATR-root-cause item means almost every run is currently atr_fallback, so keying on that would fire the banner everywhere — count-based is safer until that item lands.

#### Widen the risk-section price gate beyond the stop-loss literal
**finding (the HOW):** `risk_section_violations` (quality_bar.py:142) backs the prompt's 'no price levels in Risk Considerations' rule but only catches the stop-loss literal (structured.sl). Live NVDA output restated other banned prices anyway, so the deterministic backstop misses leaked entry/target/buy-zone numbers. Widen it: after isolating the Risk section text (already done at quality_bar.py:167), scan for any bare share-price-magnitude number. Accept an optional `price_levels: Optional[list[float]]` (sl, tp1, tp2, tp3, buy_zone_low/high, current_price) AND/OR a generic regex pass that flags any standalone `$NN.NN` / `$N,NNN` token, OR a number whose magnitude is within ~30% of current_price (so '$130', '128.50', '130' all trip but '20%', '2026', '[evidence:3]' don't). Add a violation entry per match. Wire it at narrator.py:1084 and 1108: pass the structured price set so the re-prompt fires when ANY price leaks, not just the stop. Keep behind a flag because a stricter gate could trigger more re-prompts (cost) and could false-positive on legitimate percentages — default the flag the SAME as today's behavior until soaked.
- Plain words: the AI sometimes sneaks an entry or target price back into the Risk section despite being told not to; the current safety net only catches the stop price, so this widens the net to catch any leaked price.
- **files:** consensus_engine/alerts/all_command/quality_bar.py; consensus_engine/alerts/all_command/narrator.py; config/consensus.yaml
- **flag:** `all_command.risk_price_gate_strict`
- **go_live:** hold-for-signoff
- **test (real-data):** Unit-test a crafted narrative with a Risk bullet that names tp1 ('a close above $145 would force...') while sl is a different number — strict gate must flag it; current gate misses it. Replay the documented live NVDA narrative that restated banned prices through risk_section_violations with the full price set and assert violations is non-empty. Also assert NO false positive on a clean Risk section containing only '%' figures, dates ('2026'), and [evidence:N] tags. After enabling, run `!all NVDA`/`!all TSLA` and grep consensus_engine.log for 'risk-section violations ... re-prompting' to confirm the gate fires and the adopted narrative has no price in the Risk section (check the #chat embed).
- **risk/effort:** med / M
- **open_question:** The current re-prompt KEEPS the original (possibly-still-violating) draft if the retry also fails (narrator.py:1108-1113). With a wider gate that trips more often, do we want to also strip the offending price tokens deterministically as a last resort, or keep the 'keep original on retry-fail' behavior? Stripping risks mangling a sentence.

#### Swing horizon uses raw ATR → use realized volatility
**finding (the HOW):** `compute_swing_horizon` (structured_fields.py:299) estimates days-to-target as `|tp1-spot| / (0.7 × atr14)`. It uses the single 14-day ATR as the daily move, so after an earnings crush or a vol spike the horizon is stale. The daily candles (with 'close') are already fetched and in memory (`data['daily_candles']`, aggregator.py:346), so realized volatility is free. Add `compute_realized_daily_move(candles, lookback=10)` in structured_fields.py: compute log returns of closes, take their stdev × the latest close = a realized daily $ move (model it on the existing compute_relative_volume loop at line 139 which already iterates candles safely). Pass an optional `realized_daily_move` into compute_swing_horizon and, when present and positive, use it (or the max/blend of it and 0.7×atr14) as the denominator instead of the ATR-only term. Wire the candle source at the call site (aggregator.py:985). Keep the existing ATR path as fallback when candles are too few (<lookback+1) so behavior is unchanged on thin data.
- Plain words: the 'days to target' estimate divides the distance by how much the stock typically moves per day; today it uses one fixed measure that can be wrong right after earnings; this uses the stock's actual recent daily swings, which the bot already has, for a sharper estimate.
- **files:** consensus_engine/alerts/all_command/structured_fields.py; consensus_engine/alerts/all_command/aggregator.py; config/consensus.yaml
- **flag:** `all_command.horizon_realized_vol`
- **go_live:** hold-for-signoff
- **test (real-data):** Unit-test compute_realized_daily_move on a synthetic candle series with known stdev (assert it equals stdev(log-returns)×last_close). Then compute_swing_horizon: feed (a) a calm series → realized move < 0.7×ATR → horizon LONGER than the ATR-only baseline; (b) a post-spike series → realized move > 0.7×ATR → horizon SHORTER. Assert the <lookback+1-candle fallback returns the identical old ATR-based horizon (no regression). Real-data: run `!all` on a name fresh off earnings (check recent_earnings_recap / next_earnings to find one) with the flag ON vs OFF and confirm the Horizon field shifts in the expected direction; verify via the #chat embed and the vault markdown horizon line.
- **risk/effort:** low / M
- **open_question:** Should realized vol REPLACE 0.7×ATR, or be blended (average, or max for a conservative shorter horizon)? Replacing is cleaner but a 10-day window can itself be noisy; the 0.7 empirical slippage constant (structured_fields.py:288) was tuned against ATR, so reusing it with realized vol may need a different constant.

### Lane: !all token/latency cost

#### Cut the !all cleanup (sanitize) phase — drop to single fast attempt
**finding (the HOW):** The cleanup phase fires up to 9 concurrent LLM calls (one per source type) in `narrator.sanitize_hostile_text` (narrator.py:301-312), each on the flaky free pool that 429s ~half the time, then falls back to trimmed raw text. The team's own note (todo/all-command-quality.md:179) proves cleanup outcome has NO visible effect on the final writeup. Rather than rip out the code, gate the whole batch off by default: change the aggregator's `cfg.get("all_command.sanitize_enabled", True)` default-read to False, and add `all_command.sanitize_enabled: false` explicitly to config/consensus.yaml. When OFF, the existing else-branch (aggregator.py:1084-1094) already gives every source plain `_sanitize_text` truncation — no LLM calls at all.
- Plain words: today the bot makes up to 9 throwaway AI calls to 'clean up' source text before writing the summary; those calls mostly fail and don't change the result, so we turn them off and just trim the text instead. Same phase as the next item — sanitize_enabled is the single flag that controls it.
- **files:** consensus_engine/alerts/all_command/aggregator.py; config/consensus.yaml
- **flag:** `all_command.sanitize_enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** Run `python3 -m consensus_engine` and `!all NVDA` (20-source ticker) with the flag OFF, then ON. Diff the two Discord embeds — narrative must be substantively equivalent (audit's measured claim). Grep consensus_engine.log during the OFF run for `LLM fallback chain exhausted for role=text` — must be ZERO (cleanup made no calls). Confirm `all_command_strategy: head_start` synthesis still produces a valid (status=ok) narrative. Test tickers: NVDA + TSLA (heavy), SOFI + WEN (thin) so both source-count regimes are covered.
- **risk/effort:** med / S
- **open_question:** sanitize_enabled is live-visible (changes the exact evidence text fed to synthesis), so it needs sign-off even though the maintainer's note says no quality loss — confirm on 4 real tickers before flipping in prod.

#### Make the !all sanitize phase no-LLM by default
**finding (the HOW):** This is the SAME control surface as the cut-cleanup item above — the audit lists it twice (cut vs no-LLM-default) but both resolve to flipping `all_command.sanitize_enabled` to False, which routes every source through plain `narrator._sanitize_text` truncation (aggregator.py:1084-1094) instead of `narrator.sanitize_hostile_text`. There is no second code change; the no-LLM path already exists and is exercised by the else-branch. The only delta vs the item above is framing: ship it as a permanent config default (`all_command.sanitize_enabled: false` in consensus.yaml around line 278) rather than a per-run toggle, and update the inline comment at aggregator.py:1067-1070 to note the default is now OFF.
- Plain words: the 'clean the text with AI first' step is now off by default and the bot just trims the raw text — no AI calls for cleanup.
- **files:** config/consensus.yaml; consensus_engine/alerts/all_command/aggregator.py
- **flag:** `all_command.sanitize_enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** Same end-to-end test as the cut-cleanup item (it is the same flag). Additionally assert token saving: instrument or grep that with the flag OFF, zero `role=text` synthesize calls hit the OpenRouter free pool during one `!all NVDA` — saving up to 7 real free-tier calls per command (searxng+sec already empty, see the always-empty-batches item). Verify on real tickers NVDA, TSLA, SOFI.
- **risk/effort:** med / S
- **open_question:** Should this be the permanent default (config) or stay opt-in? Recommend permanent OFF given the maintainer's own 'no quality loss' note, but it is the same sign-off gate as the item above — do not ship both as separate changes; ship one flag flip.

#### Skip the wasted 15s groq head-start on big tickers that 413
**finding (the HOW):** Add a cheap prompt-size estimate to `narrator._invoke_synthesis` (narrator.py:944-968): before calling call_with_fallback, compute `est_tokens = sum(len(m.get('content','')) for m in messages) // 4`; if est_tokens exceeds groq's TPM cap (config `llm.all_command_head_start_max_tokens`, default 12000 — matches the logged 'Limit 12000'), pass `strategy='race_all'` (or set head_start=0) so the groq solo window is skipped and the free fallbacks fan out immediately. IMPORTANT CORRECTION from the logs: a groq 413 returns at **0.0s** (verified: `HTTP 413 ... 0.0s` then same-second fan-out in consensus_engine.log 2026-06-02), so the head-start does NOT actually burn 15s on a 413 — the audit's '15s saved' premise is wrong for the 413 case. The real win is eliminating one guaranteed-failing round-trip and the misleading 'stalled within 15s' log line; the genuine 15s wait only happens when groq STALLS (accepts but is slow), which is the small-ticker case where groq can still win, so we must NOT skip there.
- Plain words: for big tickers (NVDA/TSLA) groq always rejects the writeup instantly because it's too big, so we stop even trying groq first on those and go straight to the models that do the work.
- **files:** consensus_engine/alerts/all_command/narrator.py; config/consensus.yaml
- **flag:** `llm.all_command_head_start_max_tokens`
- **go_live:** live-during-run
- **test (real-data):** Run `!all NVDA` (logged at ~12.3k requested tokens, over the 12k cap) and `!all SOFI` (small). With the change: grep consensus_engine.log — NVDA must show NO `groq/llama-3.3-70b-versatile` synthesis attempt and go straight to fan-out; SOFI must STILL try groq first (its prompt is under 12k). Confirm both still produce status=ok narratives. Measure wall-clock: NVDA should drop by the wasted-round-trip overhead (small, ~0-1s — NOT 15s, since 413 was already instant). The flag value 12000 must match groq's live TPM limit.
- **risk/effort:** low / S
- **open_question:** The advertised '15s saved per big ticker' is not real — the 413 already returns in 0.0s, so the actual saving is near-zero wall-clock plus a cleaner log. Worth confirming with a real before/after timing on NVDA whether there is ANY measurable latency win, or whether this is purely log-hygiene. If groq's DAILY budget (100k TPD) is exhausted it 429s fast on ALL tickers — a separate, larger issue this fix does not address.

#### Drop the two always-empty sanitize batches (searxng + sec)
**finding (the HOW):** aggregator.py passes `searxng_snippets=[]` (line 1073) and `sec_snippets=[]` (line 1078) into narrator.sanitize_hostile_text on every !all (SEC is injected deterministically post-sanitize at line 1096; searxng was split into news+sec routing in PR4). Inside sanitize_hostile_text the searxng_batch and sec_batch coroutines early-return `[]` on empty input (narrator.py:197-198), so they never make a call — zero token win today, this is pure dead-surface cleanup. Remove the searxng and sec parameters from the call site and from the sanitize_hostile_text signature + gather list (narrator.py:301-312, 324-334), dropping the gather from 9 coroutines to 7. Keep `sanitized['searxng']` and `sanitized['sec']` keys present (set to [] in the return dict) because downstream synthesize_narrative reads `sanitized.get('searxng', [])` and the SEC injection at aggregator.py:1096 overwrites `sanitized['sec']`.
- Plain words: two of the nine cleanup workers are always handed an empty list and do nothing — remove them so there's less code that can break.
- **files:** consensus_engine/alerts/all_command/narrator.py; consensus_engine/alerts/all_command/aggregator.py
- **flag:** none
- **go_live:** internal
- **test (real-data):** Run the !all test suite `python3 -m pytest tests/ -k all_command -v` — must stay green. Run `!all NVDA` end-to-end and confirm the SEC evidence block still appears in the embed (proves the post-sanitize sec injection at aggregator.py:1096 is untouched) and searxng-derived web snippets still reach synthesis. No output change expected (the batches were already no-ops).
- **risk/effort:** low / S
- **open_question:** none

#### Cache or trim the ~2,800-token static synthesis instruction block
**finding (the HOW):** Measured exactly: `_SYS_INSTRUCTION` (narrator.py:350-372) = 348 tokens, `_build_constraints_block` (narrator.py:577-731) = 2,583 tokens (swing_v2), total ~2,931 static tokens re-sent on the initial synthesis call AND verbatim on each of up to 3 retries (lines 1073, 1101, 1116-1125). CORRECTION on the 'cache' half: the synthesis chain is `groq/llama-3.3-70b-versatile` + `openai/gpt-oss-120b:free` + `gpt-oss-20b:free` (consensus.yaml:262) — OpenRouter `:free` models do NOT bill input tokens and do NOT support Anthropic-style cache_control blocks via the OpenRouter chat-completions endpoint (llm_client.py:121-127 sends a plain OpenAI payload). So prompt-caching yields ~0 cost savings here. The actionable half is TRIM: the anti-fabrication / 'cite verbatim, don't invent' rule is repeated ~4 times (the ANTI-FABRICATION RULE block at narrator.py:356-371, plus the FORBIDDEN-patterns lists at 605-635, 627-632, and the Expected-Move clause 569-575). Collapse to one canonical anti-fabrication statement referenced once; target ~30-40% reduction (~900-1,100 tokens off every call). This also helps the groq-413 item by getting more tickers under the 12k TPM cap.
- Plain words: the giant fixed instruction the bot sends with every writeup repeats the same 'don't make things up' rule four times — say it once and cut the prompt by roughly a third.
- **files:** consensus_engine/alerts/all_command/narrator.py
- **flag:** none
- **go_live:** hold-for-signoff
- **test (real-data):** Before/after: assert the constraints block shrinks (`python3 -c "from consensus_engine.alerts.all_command import narrator as n; print(len(n._SYS_INSTRUCTION)+len(n._build_constraints_block(True)))"` drops from ~11,725 chars). Then run `!all NVDA`, `!all TSLA`, `!all AMD` and diff the embeds against the pre-trim version — every required section (TL;DR, Catalysts, Risk Considerations, Trade Plan) must still render, no fabricated partners/codenames, no price leak in Risk. This is the load-bearing prompt for output quality, so verify on 3+ real tickers before merge.
- **risk/effort:** med / M
- **open_question:** Trimming a quality-load-bearing prompt risks reintroducing fabrication on the free models (the prose was added precisely because free models invent codenames/partners). Confirm the `:free` chain truly bills $0 input (it does) so the ONLY benefit is fewer tokens helping the groq-413 fit, not dollar savings — which reframes whether this is worth the quality risk. Recommend gating the trim behind a quick A/B on NVDA/AMD fabrication checks before committing.

#### Skip the per-ticker confidence scorer when it can't reach the alert threshold
**finding (the HOW):** `cross_reference.score_ticker` fires the LLM confidence call `_run_llm_score` whenever `technical or catalyst` is truthy (cross_reference.py:310-319), even when the cheap deterministic subtotal can't possibly clear the alert line. Compute the cheap subtotal FIRST (everything except llm_pts: analyst_pts, news_pts, sec_pts, tech_pts, social_breakdown, options_pts, youtube_pts — all already computed by line 333), then guard the LLM call: `llm_max = m.get('llm_boost_max', 15)`; skip `_run_llm_score` when `base_score + cheap_subtotal + llm_max < medium_confidence` (consensus.yaml: precision_engine.thresholds.medium_confidence=65 — the lowest tier that escapes IGNORE per engine.py:270-276). If even the maximum possible +15 AI boost can't reach 65, the AI call cannot change the WATCHLIST/IGNORE decision. Gate behind `scoring.skip_llm_below_threshold` (default False) because score_ticker is shared by the LIVE alert engine (cross_reference.py:444) AND !all (aggregator.py:129) — a sign/value-affecting change must be flag-gated.
- Plain words: the bot makes an AI call to score every ticker that has any signal; if that ticker's guaranteed points plus the biggest possible AI bonus still can't reach the alert cutoff, the AI call can't change anything, so we skip it.
- **files:** consensus_engine/cross_reference.py; config/consensus.yaml
- **flag:** `scoring.skip_llm_below_threshold`
- **go_live:** internal
- **test (real-data):** Pick a low-signal ticker from signal_events (e.g. a Twitter-only mention with no catalyst, no SEC, base_score ~20) and a high-signal one (catalyst + technical). Run score_ticker on both with the flag ON: the low-signal one must log a 'skipped LLM scorer (cannot reach threshold)' line and return llm_boost=0; the high-signal one must STILL call the scorer. Assert the final classification (engine._classify) is IDENTICAL with flag ON vs OFF for the skipped ticker (it was always going to IGNORE/WATCHLIST). Run `python3 -m pytest tests/ -k cross_reference -v` green. With flag OFF, byte-identical to today.
- **risk/effort:** med / M
- **open_question:** llm_reasoning is also used for thesis text in the alert embed even when llm_pts can't move the tier — confirm a skipped ticker (which can't alert anyway) never needs that reasoning string downstream, or the skip could blank a field on a ticker that later gets surfaced via !all. Verify the !all path tolerates llm_reasoning='' before flipping in prod.

#### Measure the synthesis retry rate from obs logs
**finding (the HOW):** Today the obs log (.omc/logs/pipeline-obs.jsonl) records only narrator_cache_miss/hit — there is NO event for any of the 4 synthesis attempts, so the retry rate is unmeasured (verified: event counts are sltp_atr_fallback/narrator_cache_miss/safe_send/pre_ready_drop/narrator_cache_hit only). Add one obs_log line at each retry site in narrator.py: (1) `{event:'synth_retry', reason:'missing_sections', ticker, missing}` at line ~1059; (2) `{event:'synth_retry', reason:'risk_violation', ticker}` at ~1085; (3) `{event:'synth_retry', reason:'contradiction', ticker}` inside the _retry_fn at ~1116; plus a baseline `{event:'synth_initial', ticker}` right after the first _invoke_synthesis at line 1051. Then compute the rate offline: `synth_retry count / synth_initial count`, broken down by reason. The 4 synthesis paths are initial (1051) + missing-sections (1073) + risk-violation (1101) + contradiction (output_filter.sanitize_or_retry retry_fn, output_filter.py:157).
- Plain words: the writeup can be re-generated up to 3 extra times when it's missing a section or leaks a banned price, each time re-sending the full ~3.6k-token prompt — but nobody has counted how often that actually happens, so we add a one-line counter at each retry point and read it back from the log.
- **files:** consensus_engine/alerts/all_command/narrator.py
- **flag:** none
- **go_live:** internal
- **test (real-data):** After adding the events, run `!all` on 8-10 varied real tickers (NVDA, TSLA, AMD, MSFT, SOFI, WEN, plus 2-3 thin tickers). Then `python3 -c` over pipeline-obs.jsonl counting synth_initial vs synth_retry by reason. Deliverable = the measured retry rate. If retries fire on >~30% of runs, the prompt-trim item above becomes the cheapest cost win; if <10%, deprioritize the trim. Cross-check against consensus_engine.log WARNING lines ('missing required sections', 'risk-section violations') which currently exist but aren't in obs and weren't found in the rotated logs (so retries are either rare or the WARNING level isn't persisted).
- **risk/effort:** low / M
- **open_question:** The existing WARNING-level retry logs don't appear in the 5 rotated consensus_engine.log files — either retries are genuinely rare on real tickers (good — low cost win) or the file handler drops WARNINGs. Confirm the log level captures them before concluding the rate is low; the obs_log events sidestep this since obs_log always writes.

### Lane: YouTube scoring + B3 tagging

#### Direction-aware YouTube score (bearish consensus must not raise a long score)
**finding (the HOW):** Today the YouTube boost (5/10/15) is always added as a positive number to the score, no matter whether the YouTube videos are bullish or bearish. So a YouTuber screaming 'short NVDA' currently RAISES NVDA's long score by up to 15. The consensus direction is already computed (`consensus_dir` at cross_reference.py:230) but thrown away when the boost is set. Fix in ONE place — `_get_youtube_context` (cross_reference.py:247-249): behind a new default-OFF flag, sign the boost by the consensus direction. When `consensus_dir=='short'`, return `score_boost = -conv_map[top_conviction]` (negative); when `=='long'`, positive; when `=='neutral'`, 0. The signed value flows unchanged into `breakdown.youtube` (cross_reference.py:364), which is summed into both `total` (the alert-threshold score) and `compute_direction` (youtube is already in `_BULLISH_BIASED_FIELDS`, models.py:73), so a negative value correctly pulls a marginal long below the alert line AND can flip computed direction. Flag OFF = byte-identical current behavior. Both live alerts (cross_reference.py:333) and `!all` (cross_reference.py:454) read `youtube.score_boost`, so this single change covers both consumers.
- Plain words: a YouTuber telling people to short a stock should LOWER that stock's "go long" score, not raise it — today it raises it regardless of direction.
- **files:** consensus_engine/cross_reference.py; config/consensus.yaml; tests/test_yt_score_visibility.py
- **flag:** `features.youtube_score.direction_aware`
- **go_live:** hold-for-signoff
- **test (real-data):** 11 short rows exist (GME high ×3 on 2026-05-21, TSLA medium ×3, META/SPY/XLK high). Seed/force a ticker whose 7d consensus is short (current data has no ticker where short strictly beats long+neutral inside 7d, so the unit test must inject a short-majority set like GME high) and assert: flag OFF → breakdown.youtube == +15 (unchanged); flag ON → breakdown.youtube == -15 and compute_direction flips a marginal long to BEARISH. PIN test: tests/test_yt_score_visibility.py — add `test_bearish_consensus_unchanged_when_flag_off` asserting a short-consensus context still yields +score_boost with the flag default-OFF, locking current behavior before the fix can flip it.
- **risk/effort:** med / M
- **open_question:** Should a 'neutral' consensus zero the boost (proposed) or keep the small positive it gets today? Zeroing is the cleaner correctness story but changes neutral-ticker totals when the flag is on.

#### Recency decay on stale YouTube mentions
**finding (the HOW):** A mention extracted 6.9 days ago counts identically to one from an hour ago. The freshness timestamp `extracted_at` is already in the row (verified 100% populated, 876/876) but the signals query (db.py:1833) doesn't even SELECT it into the output dict — only uses it in WHERE. Two-part fix: (1) add `s.extracted_at` to the SELECT list in db.get_youtube_signals_for_ticker so each mention dict carries it. (2) In `_get_youtube_context` (cross_reference.py:247-249), behind default-OFF flag, multiply the final boost by a decay factor based on the freshest contributing mention's age: `decay = max(floor, 0.5 ** (age_days / half_life_days))` with `half_life_days=3` and `floor=0.3` (config keys under the same flag block). A 1-hour-old high-conviction mention keeps the full 15; a 6.9-day-old one drops to ~0.3×. Rounds to int. Flag OFF = no decay. Stacks multiplicatively with direction-aware sign if both are on.
- Plain words: an old YouTube call should count for less than a fresh one — today a 7-day-old mention counts the same as one from an hour ago.
- **files:** consensus_engine/db.py; consensus_engine/cross_reference.py; config/consensus.yaml; tests/test_yt_score_visibility.py
- **flag:** `features.youtube_score.recency_decay`
- **go_live:** hold-for-signoff
- **test (real-data):** youtube_signals span 2026-05-31..2026-06-05 in the 7d window; NVDA has medium ×5 fresh (extracted 2026-06-05 15:39), older rows exist near the 7d edge. Unit test: build two contexts from real-shaped rows, one extracted_at = now-1h, one = now-6.9d; assert flag ON → the 6.9d boost is ~0.3× the 1h boost, flag OFF → identical. Also assert db.get_youtube_signals_for_ticker now returns extracted_at in each dict (was absent). PIN test: tests/test_yt_score_visibility.py — assert with flag default-OFF a stale (now-6.9d) mention still yields the full undecayed score_boost.
- **risk/effort:** low / M
- **open_question:** Decay off the freshest mention's age (proposed) or off a mention-count-weighted average age? Freshest is simpler and matches 'is this still live'; average punishes a thesis that had one fresh re-mention.

#### Channel-reliability weighting of the YouTube boost
**finding (the HOW):** A `trust_score` per channel already exists (youtube_channels.trust_score, used to rank YouTube price levels at db.py:1871) but the score boost ignores it. CAVEAT FROM REAL DATA: all 14 registered channels currently have trust_score=1.0, so this weighting is a NO-OP multiplier today — it only bites once scores are differentiated, but wiring it now means it activates automatically when trust is curated. Fix: (1) extend db.get_youtube_signals_for_ticker (db.py:1833) to LEFT JOIN youtube_channels on display_name=channel_name and SELECT yc.trust_score (the levels query at db.py:1874 already does this exact join — copy it). (2) In `_get_youtube_context`, behind default-OFF flag, scale the boost by the trust of the backing channel(s): use the max trust among the primary mentions (or mean), clamped to [0.3, 1.0], multiplied into the boost and rounded. Flag OFF = no scaling. NULL trust (unregistered channel) → bootstrap default 0.5, matching the levels-path convention at db.py:1862.
- Plain words: a call from a trusted channel should count more than one from a random channel — today every channel counts the same.
- **files:** consensus_engine/db.py; consensus_engine/cross_reference.py; config/consensus.yaml; tests/test_yt_score_visibility.py
- **flag:** `features.youtube_score.channel_reliability`
- **go_live:** hold-for-signoff
- **test (real-data):** 14 channels all trust=1.0 (CheddarFlow, Market Rebellion, etc.) → with this flag ON and uniform trust, every real boost is unchanged (×1.0) — that itself is the safe-default proof. Unit test must seed a low-trust channel (e.g. trust=0.4) on a real-shaped mention and assert flag ON → boost scaled to 0.4×, flag OFF → full boost; an unregistered-channel mention → 0.5× bootstrap. Assert db.get_youtube_signals_for_ticker now returns trust_score per row. PIN test: tests/test_yt_score_visibility.py — assert flag default-OFF leaves the boost untouched regardless of trust_score.
- **risk/effort:** low / M
- **open_question:** Max-trust vs mean-trust across the contributing channels: max rewards 'one trusted channel said it', mean dilutes when a low-trust channel piles on. Which matches the alert philosophy better?

#### YouTube-level / technical-level confluence bonus
**finding (the HOW):** When a YouTube-stated buy zone or target lines up with a computed support/resistance, that is genuine 2-source agreement (the project's core alert philosophy), but the two are never cross-checked. The YouTube level_data is built in `_get_youtube_context` (cross_reference.py:234-245); the technical anchor available inside score_ticker is `technical.price` and `technical.atr14` (models.py:108-114) — there is no explicit S/R list on TechnicalResult, so use an ATR-band proxy as the technical reference. Fix: behind default-OFF flag, in score_ticker (after both `youtube` and `technical` are gathered, ~cross_reference.py:333), award a small capped bonus to `youtube_pts` when any YouTube level price falls within a tight band (e.g. 1.5%) of a computed technical reference level (price ± k×ATR bands). Bonus small and capped (config `bonus`=3, `cap`=6, `band_pct`=0.015 under the flag block). Sign the bonus to match the boost's direction so it never fights the direction-aware fix. Flag OFF = no bonus.
- Plain words: when a YouTuber's target price matches a price the bot's own chart math flags as important, that's two sources agreeing — reward it with a small bonus.
- **files:** consensus_engine/cross_reference.py; config/consensus.yaml; tests/test_yt_score_visibility.py
- **flag:** `features.youtube_score.level_confluence`
- **go_live:** hold-for-signoff
- **test (real-data):** NVDA has 5 long-medium YouTube mentions + real youtube_levels rows (321 level rows in DB); run score_ticker for a ticker whose YouTube level price is within 1.5% of price±ATR and assert flag ON adds the capped bonus, flag OFF adds 0. Use a real youtube_levels price for NVDA and a real technical.price/atr14 (from yfinance, mocked in unit test) one band apart vs far apart to prove the band gate. PIN test: tests/test_yt_score_visibility.py — assert flag default-OFF yields zero confluence bonus even when a YouTube level coincides with the ATR band.
- **risk/effort:** med / L
- **open_question:** Is the ATR-band proxy an acceptable stand-in for 'computed S/R', or should this bonus be computed in the !all aggregator where the real anchor-cluster levels exist (but where the LIVE alert path can't see it)? Computing it in score_ticker keeps both consumers consistent; computing it in aggregator is more accurate but only helps !all.

#### Flip B3 per-number ticker tagging ON + run a real multi-stock before/after
**finding (the HOW):** Turn on `youtube.visual.per_number_ticker_tagging` (consensus.yaml:459, currently false). The full plumbing already exists: the prompt addendum (gemini_video_parser.py:71-84 `_B3_TICKER_ADDENDUM`), the parser capture+validation (gemini_video_parser.py:461-465), and the two-tier DB read (db.py:2199-2223, tagged numbers surface only under their own ticker, untagged fall to top-ticker). Flipping the flag asks Gemini to add a `ticker` field per on-screen number on the NEXT videos it processes. Flag OFF is byte-identical to today (all 495 existing visual rows are untagged), so the flip is a safe one-session change. Restart consensus-engine after the flip so the running parser picks up the new prompt.
- Plain words: when a YouTube video shows numbers for several stocks on screen, the bot should label each number with its stock; the wiring is already built and just needs switching on.
- **files:** config/consensus.yaml
- **flag:** `youtube.visual.per_number_ticker_tagging`
- **go_live:** hold-for-signoff
- **test (real-data):** After the flip + restart, let the poller process the next multi-stock videos, then run `!all` on two tickers from the SAME video and compare. Use a known multi-ticker video shape like IpqwTKyG4hE (7 tickers / 16 visual rows, currently 0 tagged) once re-processed. Verify in DB: `SELECT value, ticker FROM youtube_visual_evidence WHERE video_id=? AND ticker IS NOT NULL` returns per-stock tags; then `!all` on the secondary ticker should show ITS chart numbers instead of nothing. PIN test: tests/test_youtube_b3_ticker_tagging.py::test_untagged_only_is_pre_b3_behavior (already asserts all-NULL == pre-B3 top-ticker-gets-all) — the regression lock proving the flag-OFF path is unchanged.
- **risk/effort:** low / S
- **open_question:** How many real multi-stock videos to wait for before judging tag quality — Gemini may mis-tag or null-tag aggressively; need a sample before declaring the routing useful (ties to the re-process item below).

#### Extend B3 tag into the structured youtube_levels path
**finding (the HOW):** Flipping B3 ON only fixes the AI NARRATIVE text path (db.py:2199 read). The structured levels path — which feeds scoring, cross-reference, and the `!all` support/resistance ANCHORS — still hard-codes the top ticker and never reads the per-number tag. Specifically `_build_visual_levels` (scanners/youtube.py:452) computes `top = max(live_sigs, mention_count)` and passes that single ticker to `classify_visual_levels` (video_classifier.py:800), which sets `ticker=top_ticker` on EVERY filed level (video_classifier.py:859). The B3 tag (`row['ticker']`, populated at gemini_video_parser.py:465) is already on the visual_evidence rows but ignored here. Fix (behind the same flag, or a paired `youtube.visual.tag_structured_levels`): in `classify_visual_levels`, when a row carries its own `ticker` tag, file that level under the tagged ticker with that ticker's OWN live-price anchor (not top_ticker's), so its proximity-band gate uses the right price. Requires `_build_visual_levels` to fetch live prices for each distinct tagged ticker (small per-ticker fetch loop) and group rows by tag; untagged rows keep top-ticker attribution exactly as today. Flag OFF = top-ticker for all (unchanged).
- Plain words: tagging the numbers in the AI text isn't enough — the bot's structured price levels (what `!all` uses for support/resistance) also need to file each tagged number under the right stock at the right price.
- **files:** consensus_engine/scanners/youtube.py; consensus_engine/analysis/video_classifier.py; config/consensus.yaml; tests/test_visual_levels.py
- **flag:** `youtube.visual.per_number_ticker_tagging`
- **go_live:** hold-for-signoff
- **test (real-data):** Video 2UUTK-lntus has 47 visual rows (test_visual_levels.py already uses its real values REAL_2UUTK). Unit test: feed mixed tagged/untagged rows (tagged 510.43→SMCI within SMCI's price band, untagged 420.50→top DELL) and assert the SMCI-tagged level is filed under SMCI using the SMCI anchor and the DELL-band reject doesn't drop it; untagged stays on DELL. Live check: after B3 on + re-process, `SELECT ticker, price FROM youtube_levels WHERE video_id=?` should show levels under multiple tickers, not just the top one. PIN test: tests/test_visual_levels.py — the existing tests call classify_visual_levels WITHOUT tags, so they already lock the untagged/top-ticker behavior; add an explicit assert that with no tags AND flag-OFF the output is byte-identical to current.
- **risk/effort:** med / M
- **open_question:** Per-tagged-ticker live-price fetches add latency/API calls inside the poller's per-video processing — acceptable, or batch/cache them? A 7-ticker video would do up to 7 quote fetches; need a small concurrency cap.

#### Re-process recent multi-stock videos for live data
**finding (the HOW):** All 495 existing visual rows are untagged (verified: 495 total, 0 tagged) and the skip-check `has_video_been_processed` (db.py:1665, called at scanners/youtube.py:713) blocks retroactive tagging — it returns True for any video whose `transcript_status != 'pending'`. So after flipping B3 ON, without forcing a re-watch the only evidence is unit tests. Fix (operational, one-session): after the flag flip + restart, set `transcript_status='pending'` for 2-3 chosen recent multi-stock video_ids so the next poll re-watches them with tagging on, giving an instant before/after. Do this via a one-shot UPDATE, not a code change. Costs a few free-tier Gemini calls (well within the ~3-4 video/key/day budget if limited to 2-3 videos).
- Plain words: to actually see tagging work, push a couple of recent multi-stock videos back through the pipeline so they get re-watched with the new labeling on.
- **files:** consensus.db
- **flag:** none
- **go_live:** internal
- **test (real-data):** Pick high-visual-row multi-stock videos — 2UUTK-lntus (47 rows), mU0rdKxDF5A (31), WbgCM1Y0tiA (30), or IpqwTKyG4hE (7 tickers/16 rows). `UPDATE youtube_videos SET transcript_status='pending' WHERE video_id IN (...)`, restart, watch the poll log re-process them, then verify `SELECT count(*) FROM youtube_visual_evidence WHERE video_id IN (...) AND ticker IS NOT NULL` flips from 0 to >0, and `!all` on two tickers from the same re-processed video shows distinct per-stock numbers. Limit to ≤3 videos to stay inside the Gemini free quota.
- **risk/effort:** med / S
- **open_question:** Re-processing overwrites the existing untagged visual rows for those videos — confirm insert is idempotent/upsert vs duplicating rows; if it appends, need to delete the old visual+level rows for those video_ids first to avoid double-counting in scoring.

### Lane: Wolf brain

#### Build the SHORT side of Wolf beneficiary inference (v1.1) + wire the dead shorts_enabled flag
**finding (the HOW):** Mirror the existing longs-only ranking in consensus_engine/analysis/wolf_beneficiaries.py to produce SHORT picks (the weakest laggards), gated behind the already-present-but-unused `wolf.beneficiaries.shorts_enabled` flag (currently read NOWHERE — grep returns 0 hits). Concretely:
(1) macro_universe.yaml: add a `beneficiary_shorts: [...]` list inside each (scope_key, direction) bucket where the natural play is a short (e.g. OIL bull → short airlines DAL/UAL; SPX/NDX bear already has long defensives, so its SHORT bucket is the high-beta names that get hit, e.g. ARKK/high-multiple growth). Keep it surgical: only add shorts where there is a clean single-name loser, omit otherwise (same 'no manufactured pick' rule the longs follow).
(2) New function `resolve_short_universe(scope_type, scope_key, direction)`: macro/index/asset → the new `beneficiary_shorts` list; sector BEAR → the SAME ETF members as the long path (`_peer_etf_members()[scope_key]`), but ranked as the WEAKEST laggards instead of leaders. Today resolve_candidate_universe explicitly returns [] for sector+bear (lines 104-110) — that omission is what leaves a bear thesis with an empty 'bot's read'.
(3) New `rank_shorts(thesis)` mirroring rank_beneficiaries: keep names where `rs.delta < -floor` (UNDERperformers), rank by MOST-NEGATIVE delta (invert the percentile so the weakest gets rank_score~1.0), confirm with a BEARISH catalyst (`_aligned_catalyst` already returns bearish for Analyst Downgrade/Earnings Miss/FDA Rejection/Insider Selling) and a new `_bearish_flow(ticker)` mirroring `_bullish_flow` but checking PUT premium > CALL premium. Set side='short'. The DB (db.py replace_beneficiaries) and the renderer (_beneficiary_block already prints `str(p['side']).upper()`) already support side='short' with zero change.
(4) FLIP the anti-chase guard: for a short, 'extended' means already DOWN a lot (rs.stock_pct <= -extended_pct) — a name that has already crashed is mean-reversion-prone to BOUNCE, so dampen its short confidence and cap it at yellow. (The long guard dampens names already UP a lot.)
(5) In run_cycle, when shorts_enabled is true, additionally compute and persist short rows for each thesis; the digest already renders them.
- Plain words: when Wolf turns bearish on chips, the bot should name the WEAKEST chip stocks as short ideas, the same way it names the strongest as longs when he's bullish — and that whole half is currently dead.
- **files:** consensus_engine/analysis/wolf_beneficiaries.py; consensus_engine/data/macro_universe.yaml; config/consensus.yaml; consensus_engine/alerts/wolf_digest.py
- **flag:** `wolf.beneficiaries.shorts_enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** Flip the flag on. Run rank_shorts against the LIVE SMH bear thesis (macro_theses id=35, sector/SMH/bear) — its candidate universe is the 18 Semiconductor members in peer_groups.yaml (NVDA,AMD,AVGO,INTC,TSM,MU,QCOM,TXN,AMAT,LRCX,KLAC,ADI,MRVL,ON,MCHP,NXPI,ARM,SMCI). Assert the top short is a genuine LAGGARD (rs.delta most-negative, NOT a leader) and side='short'. Also run the BTC bear (id=64) and GOLD bear (id=63) asset theses. Then call gather_digest('midday') and confirm the #news embed's 'Bot's read' field shows '🔴 <TICKER> SHORT'. Negative check: with the flag OFF the output stays byte-identical (longs-only).
- **risk/effort:** med / M
- **open_question:** Which short buckets to curate in macro_universe.yaml for index BEAR theses — is the short the highest-beta growth names (ARKK-style), or do we leave index-bear shorts to the sector-member path only and not curate a macro short list? Needs one review pass on the bucket choices before sign-off.

#### Surface "Wolf + N sources agree" inside !all responses
**finding (the HOW):** Add ONE read-only DB lookup to the !all gather so a user running `!all NVDA` sees Wolf's macro context. In consensus_engine/alerts/all_command/aggregator.py `_gather_all_sources` (the parallel gather at lines 179-296), add a new task that: (a) maps the ticker to its Wolf scope via `wolf_scope.resolve_scope(ticker)` and also its sector ETF via `wolf_scope.stock_sector_etf(ticker)` (e.g. NVDA → sector SMH); (b) calls `db.get_active_thesis(scope_type, scope_key, <both directions>)` to find an active Wolf thesis on that name OR its sector; (c) if found, calls the EXISTING `db.get_confluence_check(thesis_id)`. Pass the resulting confl row into the structured result. Then in embed.py (near the other appended fields ~708-746) render one line reusing the EXISTING `wolf_news._confluence_field(confl_row)` renderer, e.g. '🤝 Wolf + 2 sources agree — bearish on semis (SMH)'. No AI call, one indexed read, near-zero latency.
- Plain words: today the bot quietly tracks when Wolf and other sources agree on a sector, but `!all` never shows it; this surfaces that unique macro context (e.g. running `!all NVDA` would note 'Wolf + 2 sources are bearish on semis').
- **files:** consensus_engine/alerts/all_command/aggregator.py; consensus_engine/alerts/all_command/embed.py; config/consensus.yaml
- **flag:** `all_command.wolf_confluence_field_enabled`
- **go_live:** hold-for-signoff
- **test (real-data):** Run `!all NVDA` (NVDA → sector SMH, active bear thesis id=35) and `!all URA` (URA stock thesis id=10, confluence tier=high, agree=1) and confirm the embed shows a Wolf/confluence line. Run `!all AAPL` (no active Wolf thesis on it or its sector) and confirm NO Wolf line appears (no false positive). Verify the !all latency is unchanged within noise (single indexed read).
- **risk/effort:** low / M
- **open_question:** Resolution precedence when BOTH a stock-level thesis and a sector-level thesis exist for the ticker (e.g. a NVDA stock thesis AND the SMH sector thesis) — show the stock one, the sector one, or both? Default proposal: prefer stock-level, fall back to sector.

#### Guard Wolf trade-idea entry/target ordering + reject non-positive prices
**finding (the HOW):** Two surgical guards.
(1) Ordering guard in consensus_engine/alerts/wolf_news.py `_trade_idea_value` (line 176): the current check only rejects `entry == target`. Add: for a SHORT, require entry > target (sell high, cover low); for a LONG, require entry < target (buy low, sell high). If the order is wrong, return None so the field falls back to plain relabeled 'Key levels' instead of posting a backwards idea like 'short $70,000 → $74.2k'. The parser is explicitly non-deterministic (free LLM) and nothing downstream catches this today.
(2) Non-positive guard in consensus_engine/analysis/wolf_email_parser.py `_coerce_thesis` setup block (lines 218-226): the parser keeps a setup if entry OR target is present and accepts 0/negatives. Require BOTH entry and target to be present and > 0 before keeping the setup (note levels already do `if price <= 0` at line 179 — apply the same boundary to setup prices). This stops a model emitting entry:0 from rendering '$0' in #news.
- Plain words: a backwards trade idea (short that 'profits' going up) or a $0 price is worse than no idea — these two checks reject both and fall back to plain 'Key levels'.
- **files:** consensus_engine/alerts/wolf_news.py; consensus_engine/analysis/wolf_email_parser.py
- **flag:** none
- **go_live:** hold-for-signoff
- **test (real-data):** Unit: feed _trade_idea_value a backwards short {'action':'short','entry':70000,'target':74192} and assert None; a correct short {'entry':74192,'target':70000} still renders 'short a re-test of $74,192 → $70k'; a backwards long {'action':'long','entry':230,'target':200} → None. Feed _coerce_thesis a setup with entry:0 and target:0 → setup is None; entry:-5 → None. Real-data: re-parse the live BTC bear email/thesis (id=64, which carries a real short setup) and confirm the rendered 'Trade idea' field is unchanged (entry above target, valid). Add the wrong-side regression test the audit calls for in tests/test_wolf_trade_idea.py.
- **risk/effort:** low / S
- **open_question:** none

#### Disable Gemini thinking + cap output on Wolf chart reads
**finding (the HOW):** In consensus_engine/analysis/wolf_vision.py `_call_gemini_image` (lines 158-165), the call passes NO generation config, so Gemini's default 'thinking' (hidden reasoning tokens) is ON and output is uncapped — wasteful for a fixed-schema JSON extraction. Build a `types.GenerateContentConfig` with `thinking_config=types.ThinkingConfig(thinking_budget=0)` (disable thinking) and `max_output_tokens` capped (~512, configurable via wolf.vision.max_output_tokens) and `response_mime_type='application/json'`, and pass it as `config=...` in the generate_content call. The video parser already builds an equivalent config (_build_generation_config in gemini_video_parser.py) — mirror that pattern. Wolf reads up to 5 charts per email against a tiny ~3-4-call/key/day free quota, so every saved token stretches scarce quota and cuts 429 key rotation. Pure cost/quota change; the extracted JSON (instrument/levels/direction) is identical.
- Plain words: the chart-reading AI call currently lets Gemini 'think' with extra hidden tokens and write unlimited output for a simple fixed-format answer; turning thinking off and capping the answer length stretches the tiny free quota.
- **files:** consensus_engine/analysis/wolf_vision.py; config/consensus.yaml
- **flag:** none
- **go_live:** internal
- **test (real-data):** Run read_chart against 3-5 of the 112 real chart JPGs in /tmp/wolf_charts (generated 2026-05-31) and confirm the returned validated dict (instrument, levels with price/role/confidence) is equivalent to before. Capture the response's usage_metadata and confirm thoughts_token_count is 0 (thinking off) and output tokens are bounded. Confirm no regression in the levels-merge step of parse_email on a real Wolf email.
- **risk/effort:** low / S
- **open_question:** Whether gemini-flash-latest honors thinking_budget=0 (some 2.5-flash variants ignore a 0 budget and only accept a low positive value); if the SDK rejects 0 for a model in _VISION_MODELS, fall back to the lowest accepted budget. Verify against the live SDK during the read.

#### Add a wolf_vision budget bucket so chart reads stop starving the video Gemini keys
**finding (the HOW):** The chart-vision path (wolf_vision._call_gemini_image) makes Gemini calls with ZERO budget accounting, yet shares the exact free-tier key pool + exhaustion tracker (_get_available_gemini_client / _mark_key_exhausted) the YouTube video pipeline depends on — and the video pipeline DOES gate on a daily budget (BudgetManager.can_consume_gemini). So uncapped vision calls can silently exhaust the shared keys and starve the budgeted video pipeline. Add a dedicated bucket:
(1) engine.py: add 'wolf_vision_calls' to BudgetManager._COLUMNS.
(2) db.py: add `('api_usage_daily', 'wolf_vision_calls', 'INTEGER NOT NULL DEFAULT 0')` to the column-migration list at line 792-794 (same pattern as gemini_video_calls) and add the column to the api_usage_daily CREATE TABLE. _ensure_row needs no change (relies on the column DEFAULT 0).
(3) consensus.yaml: add `precision_engine.budget.wolf_vision_calls: <limit>` (e.g. 30/day) near gemini_video_calls (line 578).
(4) wolf_vision.read_chart: before each chart read, `budget = BudgetManager(); if not await budget.can_consume('wolf_vision_calls', 1): skip` and on a successful read `await budget.consume('wolf_vision_calls', 1)`. Caps vision usage, makes it VISIBLE in the daily usage table, and protects the video pipeline from a cross-feature outage.
- Plain words: chart-reading and video-watching share the same small free Gemini quota, but only video-watching counts its usage; this gives chart-reading its own daily limit so a backfill burst can't starve the video pipeline.
- **files:** consensus_engine/engine.py; consensus_engine/db.py; consensus_engine/analysis/wolf_vision.py; config/consensus.yaml
- **flag:** none
- **go_live:** internal
- **test (real-data):** After migration, query api_usage_daily and confirm a wolf_vision_calls column exists defaulting to 0. Run read_chart on N+1 of the /tmp/wolf_charts images with the daily limit set to N and confirm the (N+1)th read is skipped (budget exceeded) and api_usage_daily.wolf_vision_calls == N. Then run the video pipeline and confirm its gemini_video_calls budget is unaffected (separate column).
- **risk/effort:** low / M
- **open_question:** Right daily cap value — ~15 fresh Wolf emails × up to 5 charts = ~75 reads on a backfill burst, but steady-state is 1-2 emails/day. Set the cap (e.g. 30) so a normal day never hits it but a runaway backfill is bounded; confirm against the email cadence.

#### Close the Wolf-echo filter as WONTFIX (corrected rationale)
**finding (the HOW):** The deferred 'Wolf-echo filter' in todo/wolf-macro-brain.md aims to drop signal_events rows that merely re-quote Wolf, justified by 'Twitter rows carry no text' — that justification is FACTUALLY WRONG: signal_events Twitter rows DO store text (db.py stores the tweet body; a live probe shows 1514 Twitter rows all carry text). The real reason to NOT build it still holds: Wolf's newsletter is private/paid, so genuine cross-source echoes of Wolf are ~0, and the 135 'wolf' text hits are noise from Wolfspeed / the $WOLF ticker, not echoes. Action: edit todo/wolf-macro-brain.md to mark the echo filter WONTFIX, replacing the wrong 'no text' premise with the correct 'echoes are ~0 because the newsletter is paid/private; the 135 hits are Wolfspeed/$WOLF noise' rationale. Doc-only; prevents a future session wasting effort on a non-problem.
- Plain words: a planned filter was based on a wrong fact (it claimed tweets have no text — they do); the filter still isn't worth building, but for a different reason, so write down the correct reason so nobody re-chases it.
- **files:** todo/wolf-macro-brain.md
- **flag:** none
- **go_live:** internal
- **test (real-data):** Re-run the probe: `SELECT count(*) FROM signal_events WHERE source_type='twitter' AND (raw_text IS NOT NULL AND raw_text != '')` confirms rows DO carry text (the premise is wrong), and `SELECT count(*) FROM signal_events WHERE lower(raw_text) LIKE '%wolf%'` ~= 135 and a spot-check shows they are Wolfspeed/$WOLF, not Wolf-newsletter echoes. Then confirm the todo line now reads WONTFIX with the corrected rationale.
- **risk/effort:** low / S
- **open_question:** none

#### Keep Twitter one-net-vote in Wolf confluence (argue against per-author)
**finding (the HOW):** Document feasibility but recommend NOT changing the vote unit. The data supports splitting Twitter into per-author votes (handles ARE stored — db.py signal_events has the author; ~30 distinct handles in 21 days), BUT the current one-net-vote-per-source-type in wolf_confluence.py (the anti-crowding design at lines 14-16,146-163,236-238) is deliberate: per-author voting would let ONE chatty account post N tweets and tip a thesis to 'critical' (the @-ping tier), reintroducing exactly the crowding the design prevents. The confluence tiers gate on agree_count >= 1 (high) / >= 2 (critical, which @-pings) — per-author would inflate agree_count from a single loud account. Recommendation: keep one-net-vote; at MOST use distinct-author COUNT as a display-only color/strength hint in the embed (never as a vote multiplier). Edit todo/wolf-macro-brain.md to record this decision with the crowding-risk rationale so it isn't re-litigated.
- Plain words: counting each Twitter author as a separate 'vote' sounds fairer, but it would let one loud account spam a thesis to the alert-everyone tier — so keep one combined Twitter vote and only maybe show author count as a strength hint.
- **files:** todo/wolf-macro-brain.md
- **flag:** none
- **go_live:** internal
- **test (real-data):** Probe `SELECT author, count(*) FROM signal_events WHERE source_type='twitter' AND recorded_at > strftime('%s','now')-21*86400 GROUP BY author ORDER BY 2 DESC` and confirm at least one account has enough rows that, under per-author voting, it alone could reach agree_count>=2 (the critical @-ping threshold) — demonstrating the crowding risk concretely. No code change; the verification IS the argument.
- **risk/effort:** low / S
- **open_question:** none

#### Wolf test-gaps: short-side bear thesis, confluence tier-up firing, beneficiary freshness gate
**finding (the HOW):** Three real-data regression tests.
(1) SHORT-side end-to-end (pairs with the v1.1 build): run rank_shorts against a REAL active bear thesis — SMH bear (macro_theses id=35, 18 Semiconductor members) — and assert the ranked top short is a LAGGARD (rs.delta most-negative, sign-flip is correct, side='short'), then render gather_digest and confirm the '🔴 ... SHORT' embed line. The long side shipped with a real-data test that caught a direction bug; the short side inverts the riskiest sign logic and needs the same check.
(2) Confluence tier-up regression-LOCK: the audit asked whether the live tier-up→alert path has EVER fired — VERIFIED IT HAS (wolf_news_alerts holds 5 posted confluence alerts: thesis 63 GOLD high 2026-06-04, 64 BTC high, 59 critical, 10 URA high, 52 YIELDS high). So this is NOT a dead path — write a regression test that replays an active high-tier thesis (e.g. id=10 URA) through wolf_confluence.score_confluence + the main.py tier-up branch and asserts a confluence event is produced when combined_tier rises past alerted_tier, and is suppressed (hysteresis) when it does not.
(3) Beneficiary freshness gate: wolf_digest.gather_digest filters beneficiary rows older than wolf.beneficiaries.digest_max_age_sec (7200s) — that branch was only tested with a hand-built payload, never against the DB. Add a test seeding one FRESH and one STALE wolf_beneficiaries row (via db.replace_beneficiaries with computed_at now vs now-9000) for an acting/imminent thesis and assert only the fresh row reaches the digest payload.
- Plain words: three missing safety tests for the Wolf feature — that short ideas pick the right (weakest) stocks, that the 'sources agree, send an alert' path actually fires, and that stale beneficiary picks get filtered out of digests.
- **files:** tests/test_wolf_beneficiaries.py; tests/test_wolf_trade_idea.py
- **flag:** none
- **go_live:** internal
- **test (real-data):** Run pytest on the three new tests against a temp DB seeded from the real shapes above (SMH bear id=35 members from peer_groups.yaml; URA confluence row; fresh+stale beneficiary rows). All three pass; the short-side test fails BEFORE the v1.1 build lands (proving it guards the new sign logic) and passes after.
- **risk/effort:** low / S
- **open_question:** none

### Lane: options-flow + infra + test-gaps + docs

#### Route options-flow alerts to their own channel (stop flooding main, ~175/day)
**finding (the HOW):** Today every unusual-flow alert posts to the SAME Discord channel as regular signals via `_post_to_alerts_channel` (main.py:372). The DB confirms the flood: 116 alerting cycles, ~175-200 distinct (ticker,hour) posts/day (e.g. 202 on 06-01, 174 on 06-04). Fix: add a dedicated channel. (1) Add config `api_keys.options_flow_channel_id` (new key, default "") in consensus.yaml next to `discord_channel_id`. (2) Add a sibling helper `_post_to_options_channel(text)` in main.py that mirrors `_post_to_alerts_channel` (main.py:874-893) but reads the new channel id, and falls back to the main alerts channel when the new id is blank (so behavior is unchanged until the user fills it in). (3) In `_run_options_flow_scan` change `await _post_to_alerts_channel(format_flow_alert(h))` (main.py:372) to call the new helper. No scoring/data change; every hit is still saved via `insert_options_flow` for `!all`.
- Plain words: move the firehose of ~175 options messages a day off the main signals channel into a room of its own; if the user hasn't set that room yet, nothing changes.
- **files:** consensus_engine/main.py; config/consensus.yaml
- **flag:** `api_keys.options_flow_channel_id`
- **go_live:** hold-for-signoff
- **test (real-data):** Set `options_flow_channel_id` to a test channel; run `python3 -m consensus_engine --once` (or call `_run_options_flow_scan`) with `features.options_flow.enabled:true` during market hours and confirm the `⚡ UNUSUAL OPTIONS FLOW` posts land in the new channel, not #chat. Unit test: monkeypatch both post helpers, assert flow alerts call `_post_to_options_channel` and that with a blank id it falls through to the main channel. Regression vs DB: the 7,278 alerted options_flow rows show this path is hot, so verify a real cycle still posts.
- **risk/effort:** low / S
- **open_question:** Which Discord channel id should options flow go to — a brand-new #options-flow channel, or the existing #news? User must supply the id; until then it falls back to main (no visible change).

#### Per-cycle cap (8) silently drops qualifying flow — make selection smarter than raw premium-sort
**finding (the HOW):** The scanner sorts hits by raw premium descending (options.py:278) and main.py picks the top 8 distinct tickers per cycle (main.py:363-374). The DB proves the bias: SPY/QQQ/TSLA take 1205/954/813 of the alerts because their avg premium is ~$9-11M vs MSTR ~$1.2M, so mega-cap ETFs win the top-8 race every cycle (104 of 116 cycles hit the cap=8). Fix: replace the raw-premium sort key with an 'unusualness' score that normalizes premium against the ticker's own trailing average, behind a default-OFF flag. Add `options_flow.selection_mode` (values: `premium` [current/default] | `relative`). When `relative`, compute each ticker's trailing-30-day mean premium from the options_flow table (new `db.get_flow_premium_baseline(ticker, days=30)` helper: `SELECT AVG(premium_usd) FROM options_flow WHERE ticker=? AND detected_at>=?`) and sort hits by `premium_usd / max(baseline, premium_usd*0.1)` (a ratio = how big this bet is vs normal for THAT name), keeping vol_oi_ratio as the tiebreak. Keep the cap at 8 but now the 8 chosen are the most-unusual-for-their-name, not the 8 fattest ETFs.
- Plain words: instead of always alerting on the biggest dollar bets (always the same giant ETFs), alert on the bets that are biggest *relative to what's normal for that stock* — so a surprising $3M bet on a mid-cap beats the routine $200M SPY bet.
- **files:** consensus_engine/scanners/options.py; consensus_engine/main.py; consensus_engine/db.py; config/consensus.yaml
- **flag:** `options_flow.selection_mode` (default "premium")
- **go_live:** hold-for-signoff
- **test (real-data):** Backtest on the 32,794 real options_flow rows: replay the 116 alerting cycles under `relative` mode and diff the chosen top-8 vs current. Assert mega-cap ETFs (SPY/QQQ/IWM) lose slots to single names with high premium/baseline ratios (e.g. a day MU's $57M max vs $8.76M avg = 6.5× should rank above a routine QQQ bet near its $9.5M avg). Unit test: feed FlowHits for SPY (premium 200M, baseline 11.5M → ratio 17) and MSTR (premium 8M, baseline 1.16M → ratio 7) plus a one-off small-cap (premium 3M, baseline 0.3M → ratio 10) and assert the small-cap and SPY both outrank MSTR under relative mode but SPY dominates under premium mode.
- **risk/effort:** med / M
- **open_question:** Should `relative` mode keep an absolute premium FLOOR (e.g. still require >=$250k) so a tiny illiquid name with a $30k-but-10×-its-average bet doesn't crowd out real money? Recommend yes — keep min_premium_usd as a pre-filter, apply relative only to ranking.

#### Per-ticker "unusual" baseline instead of a flat $250k/5x floor
**finding (the HOW):** The gate is a single flat `min_premium_usd: 250000` + `min_vol_oi: 5.0` for every ticker (consensus.yaml:700-702), applied in `_scan_chain_for_flow` (options.py). A $250k bet is noise on SPY (avg $11.5M) but genuinely unusual on a $5 small-cap — so mega-caps trivially clear it every cycle while real small-name surprises just under $250k are missed. Fix (flag-gated): add `options_flow.relative_baseline_enabled` (default false) and `options_flow.relative_multiplier` (e.g. 3.0). When ON, after the flat floor passes, ALSO require `premium_usd >= relative_multiplier * baseline` where baseline = the ticker's trailing-30d mean premium from the same `db.get_flow_premium_baseline` helper used by the selection-mode item (share one DB call per ticker per cycle). This is an ADDITIONAL filter, not a replacement, so the existing absolute floor still protects against penny-stock noise. The options table already holds the history (32,794 rows, every top-50 ticker has >50 rows).
- Plain words: 'unusual' should mean 'unusual for this stock', so a $250k bet only counts if it's at least 3× bigger than that stock's normal daily options money.
- **files:** consensus_engine/scanners/options.py; consensus_engine/db.py; config/consensus.yaml; consensus_engine/main.py
- **flag:** `options_flow.relative_baseline_enabled` (default false)
- **go_live:** hold-for-signoff
- **test (real-data):** Against the 32,794 options_flow rows: compute each top-20 ticker's 30d mean premium and confirm with `relative_multiplier=3` that SPY's routine $11.5M-avg bets mostly FAIL the relative gate (they sit near their own average) while MU's $57M max (6.5× its $8.76M avg) PASSES. Quantify cap relief: count how many of the 104 capped cycles would drop below 8 qualifying tickers under the relative gate (should free the cap on most cycles). Unit test: FlowHit premium $300k on a ticker whose baseline is $50k passes (6×); same $300k on a ticker whose baseline is $5M fails.
- **risk/effort:** med / M
- **open_question:** Cold-start: a ticker with <N rows of history has no reliable baseline. Recommend skipping the relative gate (fall back to flat floor only) when row count < e.g. 10 — needs the helper to return None and the caller to treat None as 'pass'.

#### Tradier real-time-free options feed (research, needs signup)
**finding (the HOW):** RESEARCH RESULT: recommend WONTFIX / close the candidate. Verified from Tradier's own docs: real-time options data (chains, quotes, time&sales) is available ONLY to Tradier *Brokerage* (funded) account holders; the free account + sandbox return the industry-standard 15-minute delayed data — identical freshness to the yfinance source already in production. Real-time *streaming* additionally requires a paid market-data subscription. The realtime-options todo's HARD CONSTRAINT (todo/options-flow-realtime.md:8) is 'must be FREE, paid feeds OFF the table.' Tradier therefore buys zero freshness improvement under the free constraint. The only narrow, optional use: Tradier sandbox is a more stable, documented 15-min-delayed source (rate limit ~60 req/min, ORATS greeks/IV included) than rate-limit-fragile yfinance — so it could serve as a drop-in *reliability* fallback for the SAME 15-min data, NOT a real-time upgrade. No code change; update the todo to record the verified delay and close the Tradier line.
- Plain words: Tradier's free tier is also 15 minutes behind, just like what we use now — going truly live needs a funded account and a paid data plan, which the user ruled out. Nothing to build; just write down the finding so no future session re-chases it.
- **files:** todo/options-flow-realtime.md; todo/wolf-macro-brain.md
- **flag:** none
- **go_live:** internal
- **test (real-data):** Documentation-verified (Tradier docs market-data + sandbox pages, June 2026): sandbox = 15-min delayed; real-time = funded brokerage account; real-time streaming = paid subscription. No runtime test. If the optional sandbox-fallback is ever pursued, smoke-test the sandbox options-chain endpoint with a free sandbox token on AAPL and confirm timestamps are ~15 min old (matching yfinance).
- **risk/effort:** low / S
- **open_question:** Does the user want a sandbox-based 15-min Tradier fallback purely for yfinance rate-limit resilience (same freshness, more stable), or close the Tradier line entirely? Default recommendation: close it.

#### No end-to-end test for the concurrent YouTube level-alert path
**finding (the HOW):** `_check_youtube_level_alerts` (main.py:896-949) fetches every watched ticker's price concurrently via `asyncio.gather(..., return_exceptions=True)` then zips ticker→price and fires `🎯 approaching` alerts within the proximity band — and it has ZERO test (grep of tests/ finds none). Add `tests/test_youtube_level_alerts.py` mirroring the tmp_db fixture style of tests/test_options_flow.py. Seed real-shaped rows into youtube_levels (e.g. NVDA support @ $100, TSLA resistance @ $250), monkeypatch `consensus_engine.main._fetch_yfinance_price` to return a price INSIDE the 0.5% band for NVDA (e.g. $100.2) and OUTSIDE for TSLA (e.g. $300), and monkeypatch `_post_to_alerts_channel` to capture sent text. Assert: (a) exactly one alert fires (NVDA, in-band) and the message contains '🎯' + 'NVDA' + '$100'; (b) `db.record_level_alert` was called for NVDA so a re-run is deduped by `was_level_recently_alerted`; (c) THE ERROR-SKIP BRANCH: make the price fetch RAISE for TSLA (return an Exception) and a normal value for NVDA, assert NVDA still alerts and the TSLA exception is swallowed (not fatal) — the zip(ticker,price)+`isinstance(current_price, Exception)` branch at main.py:918-921.
- Plain words: write the missing test that proves the price-vs-level matcher pairs the right price to the right stock, fires only when truly near a level, and that one stock's price-fetch failure doesn't kill the whole alert sweep.
- **files:** tests/test_youtube_level_alerts.py; consensus_engine/main.py
- **flag:** none
- **go_live:** internal
- **test (real-data):** `python3 -m pytest tests/test_youtube_level_alerts.py -v` — uses the real DB schema via the tmp_db fixture (init_db), real `get_youtube_levels_for_ticker` / `was_level_recently_alerted` / `record_level_alert` code paths, only the network (yfinance) and Discord post mocked. Seed mirrors real youtube_levels rows (321 live level rows exist for shape reference). Add the test ID to .test-baseline only if it surfaces a pre-existing bug; otherwise it should pass green.
- **risk/effort:** low / S
- **open_question:** `_fetch_yfinance_price` is module-level in main.py and imports yfinance lazily — confirm the monkeypatch target is `consensus_engine.main._fetch_yfinance_price` (it is, per the call at main.py:914). No open blocker.

#### Update stale gemini-video-eval-assertions.md status (doc-only)
**finding (the HOW):** todo/gemini-video-eval-assertions.md:3 still reads 'Status: OPEN — chronic failure since 2026-04-23' and the title says '2/7 chronic failure', but the harness was rewritten and today's cron (.omc/logs/v2_assertions_20260606.log) reports 'SUMMARY: gemini-reading+guardrails 6/6 gating checks passed'. A1 (Gemini read video, 47 spans), A3-A7 all ✅; the OLD A1-A3 'chronic failure' framing is obsolete. The ONE real remaining open item is now an INFO check, not a failure: A2 'visual→levels filing path' shows `visual_price_rows=17 chart_levels_filed=0` — i.e. the classifier sees 17 chart price rows but files 0 into youtube_levels. Fix the doc: change Status to 'MOSTLY RESOLVED — gating 6/6; one open question (A2)'; retitle away from '2/7'; rewrite the 'REMAINING' section to the single concrete question 'why does A2 file 0 levels from 17 visual price rows for 4mSyMr8PGLI' and point at the visual→levels filing path (scanners/youtube.py:459-462; video_classifier.py:800-815).
- Plain words: the daily self-test now passes 6 of 6 — the todo is years-out-of-date saying it's broken; rewrite it to reflect the pass and name the one leftover puzzle (chart numbers not reaching the level table).
- **files:** todo/gemini-video-eval-assertions.md
- **flag:** none
- **go_live:** internal
- **test (real-data):** Cross-check the rewritten status against .omc/logs/v2_assertions_20260606.log line 42 ('6/6 gating checks passed') and line 28 ('A2 visual_price_rows=17 chart_levels_filed=0'). Doc-only — verify by reading the log, no code run. The A2 zero-filing is corroborated by the live DB note in the audit (0 tagged of 495 visual rows).
- **risk/effort:** low / S
- **open_question:** Close the todo entirely or keep it open scoped to just the A2 zero-level-filing question? Recommend keep-open-but-rescoped to A2, since that is a genuine unsolved pipeline gap (chart numbers not reaching youtube_levels) tracked elsewhere in the audit as the B3 structured-levels item.

#### Reconcile dod-checklist-scope-aware.md (marked DONE) with CLAUDE.md
**finding (the HOW):** todo/dod-checklist-scope-aware.md:3 says 'Status: DONE 2026-05-22' and its acceptance #1 (line 61) required CLAUDE.md's critical-path checklist to be restructured into tag-keyed buckets ([always]/[gateway]/[discord-commands]/[agent-mention]/[infra]/[ingest], lines 28-51). But the live CLAUDE.md 'What to verify' section (lines 93-105) is still the OLD flat list: 'Always-on checks — every time' + 'Shared-file tripwire'. The restructure was never applied, so a DONE item is hiding undone work. Recommend: flip the status, don't silently re-do scope of someone else's accepted design. Change line 3 to 'Status: REOPENED 2026-06-06 — marked DONE but acceptance #1 (CLAUDE.md tag-keyed restructure) was never applied; CLAUDE.md still has the flat list at lines 93-105.' Add a one-line note explaining the gap. (Doing the actual CLAUDE.md restructure is a separate larger change — the user edits CLAUDE.md directly per their workflow — so this solution only corrects the false DONE; the restructure itself stays a tracked open task.)
- Plain words: a todo claims it finished rewriting the testing checklist into per-area buckets, but the checklist in CLAUDE.md was never actually rewritten — it's still the old everything-every-time list. Flip the todo back to open with a note so the leftover work isn't hidden.
- **files:** todo/dod-checklist-scope-aware.md; CLAUDE.md
- **flag:** none
- **go_live:** internal
- **test (real-data):** Doc-only. Verify by diffing the proposed tag-keyed structure in the todo (lines 28-51) against CLAUDE.md lines 93-105 — they don't match (CLAUDE.md has 'Always-on checks'/'Shared-file tripwire', not '[always]'/'[gateway]'/'[ingest]'). No code run.
- **risk/effort:** low / S
- **open_question:** Should this session perform the CLAUDE.md tag-keyed restructure now (acceptance #1-#4), or only flip the status and leave the restructure as tracked work? Recommend flip-status-only here, since restructuring the DoD changes how every future session self-verifies and warrants explicit user buy-in on the bucket design.

## Open questions for the user

**ASK THE USER ONLY THESE — everything else is resolved; use the recommended default noted inline and do NOT ask.**

The run should ask only the genuine judgment calls below, up front, before Pass 1:

- **A. Options-flow channel (REQUIRED — the run needs a channel ID from the user).** Routing the ~175 alerts/day off the main signals channel needs a destination. Brand-new #options-flow channel or the existing #news — and what is its channel ID? Until provided, the code falls back to the main channel (no change) and the flood continues, so this one genuinely needs the user's answer to deliver the benefit.
- **B. Wolf index-bear shorts — what to short on a broad-market top.** For a whole-market bear thesis (SPX/NDX/RUT bear), should the bot's short ideas be the highest-beta / most-extended growth names (e.g. ARKK-style), or should index-bear theses NOT get a curated macro short list and only ever surface shorts via the sector-member path (weakest members of a bearish sector)? A curation judgment that changes which short ideas post.
- **C. (optional) AI evidence-cleanup OFF by default?** The run will turn off the `!all` AI "cleanup" step (maintainer's own note: no quality loss; saves up to ~9 calls/command). Default = permanently off. Speak up only to keep it a toggle instead. (You'll see this again at the go-live sign-off regardless.)

**Everything in the numbered list below now has a recommended default written into its own solution above** (fake-ticker ETF whitelist → yes; neutral-YouTube boost → zero it; recency decay → freshest mention; channel-trust → max; sparseness banner → count-based; risk-gate retry-fail → keep original draft; swing horizon → blend; B3 sample → 2-3 videos; wolf_vision cap → 30; options relative gate → keep $250k floor + skip on <10 rows of history; Tradier → close; gemini thinking_budget → fall back to lowest accepted; doc-todos → keep-rescoped / flip-status-only; CLAUDE.md restructure → flip the stale DONE only, leave the restructure as tracked work for the user). **Apply those defaults silently. The list below is kept only as the record/rationale — do NOT ask the user about any of it; ask only A/B/C above.**

The original decision list (now defaulted — reference only):

1. **Fake-ticker block:** Should index/ETF tickers like SPY/QQQ (Finnhub returns 0 market cap for many ETFs) be whitelisted so the size gate doesn't accidentally reject them?
2. **Chart-pattern field:** What confidence floor hides noise without hiding real signals (0.5 is a guess; may want to surface all hits since the detector returns only the single best one)?
3. **Sparseness banner:** Threshold on surfaced-source COUNT, or on whether the trade plan fell back to ATR levels? (Count-based is safer until the ATR-root-cause item lands — see Cross-reference.)
4. **Risk price gate:** When the re-prompt also fails, strip the offending price tokens deterministically as a last resort, or keep today's 'keep the original draft' behavior?
5. **Swing horizon:** Should realized volatility REPLACE 0.7×ATR or be blended (and does the 0.7 slippage constant need re-tuning for realized vol)?
6. **Sanitize cut (×2 framing):** Permanent OFF default or opt-in? (Recommend permanent OFF; ship as ONE flag flip, not two separate changes.)
7. **Groq head-start skip:** Confirm with a real before/after NVDA timing whether there's ANY measurable latency win or whether it's purely log-hygiene (the 413 already returns in 0.0s).
8. **Prompt trim:** Confirm the `:free` chain truly bills $0 input (it does) so the only benefit is fewer tokens helping the groq-413 fit — is the trim worth the fabrication risk on free models? (Recommend an A/B on NVDA/AMD fabrication checks first.)
9. **Skip-LLM-scorer:** Confirm the `!all` path tolerates an empty llm_reasoning string before flipping in prod (a skipped ticker could later be surfaced via `!all`).
10. **Synthesis retry-rate measurement:** Confirm the log level captures the WARNING retry lines before concluding the rate is low.
11. **Direction-aware YouTube:** Should a 'neutral' consensus zero the boost (cleaner) or keep today's small positive?
12. **Recency decay:** Decay off the freshest mention's age (proposed) or a count-weighted average age?
13. **Channel reliability:** Max-trust vs mean-trust across contributing channels?
14. **Level confluence:** Is the ATR-band proxy an acceptable stand-in for real S/R, or compute the bonus in the `!all` aggregator (more accurate, but only helps `!all`)?
15. **B3 flip:** How many real multi-stock videos to wait for before judging tag quality?
16. **B3 structured levels:** Per-tagged-ticker live-price fetches add latency — acceptable, or batch/cache them (and what concurrency cap for a 7-ticker video)?
17. **B3 re-process:** Confirm the visual-row insert is idempotent/upsert vs appending — if it appends, delete old visual+level rows first to avoid double-counting.
18. **Wolf shorts (v1.1):** Which short buckets to curate for index BEAR theses — highest-beta growth names (ARKK-style), or leave index-bear shorts to the sector-member path only?
19. **Wolf-confluence in !all:** Precedence when BOTH a stock-level and a sector-level thesis exist — show stock, sector, or both? (Default: prefer stock, fall back to sector.)
20. **Gemini thinking-off:** Whether gemini-flash-latest honors thinking_budget=0 (some variants only accept a low positive value) — fall back to the lowest accepted budget if rejected.
21. **wolf_vision budget cap:** Right daily cap value (e.g. 30) so a normal day never hits it but a runaway backfill is bounded?
22. **Options selection-mode:** Should `relative` mode keep an absolute premium FLOOR (e.g. >=$250k) so a tiny illiquid name doesn't crowd out real money? (Recommend yes.)
23. **Options relative baseline:** Cold-start — skip the relative gate (fall back to flat floor) when a ticker has <~10 rows of history?
24. **Tradier:** Want a sandbox-based 15-min Tradier fallback purely for yfinance rate-limit resilience (same freshness, more stable), or close the Tradier line entirely? (Recommend close.)
25. **Options channel id:** Which Discord channel should options flow go to — a brand-new #options-flow channel or the existing #news? (User must supply the id; falls back to main until then.)
26. **gemini-video-eval todo:** Close it entirely or keep it open rescoped to just the A2 zero-level-filing question? (Recommend keep-open-but-rescoped.)
27. **DoD checklist todo:** Perform the CLAUDE.md tag-keyed restructure now, or only flip the false DONE and leave the restructure as tracked work needing user buy-in? (Recommend flip-status-only.)

## Cross-reference

The `!all` ATR-fallback root cause (almost every run currently falls back to ATR-derived trade levels) is solved separately in `_smart-levels-design-2026-06-06.md`. Two items here depend on that fix: the **data-sparseness banner** (open question 3 — whether to key the banner on ATR-fallback would fire it everywhere until the root cause lands, so it stays count-based for now) and the **swing-horizon realized-vol** item (sharper days-to-target only matters once the levels themselves are sound).
