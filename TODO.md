# To Do List

This is the **index**. Each entry points to a detail file in `todo/<name>.md` that holds the full context (what worked, what didn't, next steps, files involved, etc.). When an entry is completed, mark its header `— DONE YYYY-MM-DD` rather than deleting it. Leave completed entries (and their detail files) in place for a soak window so live tests can confirm there are no issues; remove only once the work is proven stable and user approves. **Never re-use deleted item numbers** — e.g. if #4 is removed, the next new item is #18, not #4.

---

<!-- Add items below -->

## 1. Delete old YouTube backup code (after 2026-05-28) — DONE 2026-05-28

**File:** `yt-grounding-path-b-hard-delete.md`

Rip out the dormant old YouTube-parsing fallback code now that the 30-day soak window has passed.

## 2. Finish making alerts arrive faster — DONE 2026-05-29

**File:** `speed-accuracy-optimization.md`

Finish the 8 partially-done speed-accuracy items (parallel news cascade, technical filter short-circuit, batch price followups, shared watchlist) so alerts arrive in 3–8 seconds instead of 10–30.

## 3. Fix the daily Gemini video-test failures — DONE 2026-05-29

**File:** `gemini-video-eval-assertions.md`

Make the daily Gemini regression cron stop failing every day. Root cause (fixed earlier) was the chain testing a dead captions path, not Files-API re-upload. This session finished it: **A1** verified the eval video's levels are chart-sourced not spoken (classifier extracts 0 levels from 26 spoken spans); **A2** built the chart-numbers→`youtube_levels` pipe (commit on master); **A3/A4** re-pointed the cron's stale-value checks to honest capability checks and split "Gemini reading works" (gating) from "levels-filing" (informational) so it stops blanket-red.

## 4. Stop the model-sync script from breaking ownership — DONE 2026-05-22

**File:** `sync-gateway-models-ownership.md`

Stop the gateway-model sync script from breaking the gateway when run as root by flipping the config file's ownership from openclaw to root.

## 5. Make the done-checklist scope-aware — DONE 2026-05-22

**File:** `dod-checklist-scope-aware.md`

Rewrite the done-checklist so each item is tagged by code surface and only the relevant tags run for a given change, instead of forcing every session to verify every check every time.

## 6. Improve what the !all command shows

**File:** `all-command-quality.md`

Continue improving what `!all <TICKER>` shows by picking one quality lever per session (max-pain, peer comp, options flow, etc.) from the documented menu. **2026-05-29:** options-flow lever shipped via #18 — recent autonomous-detected unusual flow now feeds the `!all` narrator (`get_options_flow_for_ticker` → structured-data summary). **2026-05-30 (run `all-levers-2026-05-29`):** shipped **max-pain** (weekly+monthly embed field) + **peer relative-strength** (5-day vs sub-industry peers, embed + narrator) + a new sub-industry **peer layer** (`data/peer_groups.yaml`, separate from the A4 gate map). Commits `53e3e35`+`7d77245`, live-verified. **2026-06-01 (run `latency-speedup`):** shipped the **slow-response fix** — `!all` synthesis now gives groq a head-start and races the 2 fallback models only on a stall (`llm.all_command_strategy: head_start`), with a structural-validity guard so a fast incomplete answer can't win, plus a groq circuit breaker. Scoped to `!all` only (6 other LLM callers untouched). Live-verified `!all TSLA`: tail **234s + failed narrative → 82.7s + valid** (commits `85ac88f`/`94d8276`/`9f1f537`). **Root-cause diagnosed 2026-06-01 (after the fix):** the groq "stall" is groq 429'ing on its free-tier **daily** token limit (100k/day, observed Used 98,960). Each `!all` burns ~18-25k groq tokens because the 9-call **sanitize** phase ALSO routes through the groq `all_command_chain` (`narrator.py:183`) on top of the 8k-token synthesis — so ~4-5 `!all` exhausts groq for the day, then everything 429s to the slow free models (the real tail). head_start handles this gracefully but is a symptom-fix. **Recommended root fix: route the 9 sanitize calls OFF groq onto the `openrouter/free` text chain** (trivial cleanup, no premium model needed) — roughly halves groq tokens/`!all`. **2026-06-02 — ROOT FIX SHIPPED + LIVE:** added a groq-free `all_command_sanitize_chain` (`[gpt-oss-120b:free, gpt-oss-20b:free]`); `_batch_summarize` (covers searxng/news/sec/chat/brief batches) + `vault_excerpt` now route through `_sanitize_chain()`; synthesis stays on the groq head-start chain. Commit `5e64656`, fast-forward-merged to master, engine restarted + live-verified `!all NVDA`: production logs show sanitize (role=text) tried ONLY the 2 free models (zero groq), synthesis attempted groq then fanned out, valid embed posted ("$NVDA — Full Analysis", 2061-char narrative). 1670 tests pass. **Observed caveat:** when both free models are transiently flaky (429/timeout, as during the verify run), sanitize degrades to its truncated-text fallback — output stays valid, but the cleanup quality drops that run. Optional follow-up: widen the free sanitize chain with more providers so one provider's rate-limit can't exhaust it. (Also: groq 413s on the source-heavy synthesis request — 12k TPM free-tier cap — so head_start fans out for big tickers; expected.) (2-stage-embed perceived-latency idea: REJECTED by user.) **2026-06-15 (run todo-sweep-2026-06-13):** shipped 2 more levers, both LIVE + verified in a real `!all` — **EPS-revision trend** (📊 Snapshot gains "EPS rev 34↑ 3↓ (30d)"; own-timeout lazy yfinance fetch, pinned column-casing fixture) + **Stocktwits retail sentiment** (new 💬 Retail field "74% bullish · +1 pts/5d · 650k watching"; fetched via requests since Cloudflare blocks aiohttp's TLS; in-flight coalescing + negative cache). The named 2026-06-10 "stale close price" bug was found already-fixed in committed code. Commits e5ad961/ffb4d0c, 20 tests. **2026-07-03 (active-items-audit):** shipped **analyst-consensus momentum** — the 📊 Snapshot field gains a `Rating trend ▲ 3.82→3.92 (2mo)` line: the weighted Wall-St rating (StrongBuy=5…StrongSell=1) now vs. the oldest available prior period from yfinance `.recommendations`, with a rolling-window fallback (a `-3m` baseline isn't guaranteed — AMD shows 2mo, TSLA 3mo) + honest window labels. Flag `features.snapshot.analyst_momentum: true`; live-verified AMD ▲3.82→3.92 / AAPL ▼3.75→3.62 / TSLA ▲3.38→3.43; 10 tests; evidence `features_snapshot_analyst_momentum.md`. Stays OPEN — more levers remain in the menu (`all-command-quality.md`).

## 7. Three upgrades to the discover skill — DONE

**File:** `discover-skill-mods.md`

Three quality-of-life upgrades to the discover skill: stronger verification gate in Pass 5, a no-tmux native parallel-agent option, and a one-sentence kickoff prompt for Pass 5.

## 8. Don't lose Discord messages during reconnects — DONE 2026-05-22

**File:** `gateway-reconnect-replay.md`

Stop losing user `!commands` and `@-mentions` that arrive during the Discord gateway's reconnect window by replaying recent messages on every gateway READY.

## 9. Get the 5-model failover working — DONE 2026-05-20

**File:** `agent-model-roulette.md`

Get `!ask` and `@-mention` failover working reliably across multiple LLM models so a single flaky provider can't kill the bot's replies.

## 10. Fix the broken web-search providers — DONE 2026-05-28

**File:** `web-search-providers.md`

Restore a working web_search tool for the `@-mention` agent path now that Exa is out of credits and the Brave plugin times out due to a secret-resolution bug.

## 11. Brave Search hit its monthly limit — DONE 2026-05-22

**File:** `brave-search-monthly-cap.md`

Handle Brave Search's monthly $5 cap being maxed out by either topping up, adding a 402-circuit-breaker, or demoting Brave in the news cascade.

## 12. Replace the flaky free OpenRouter models — DONE 2026-05-22

**File:** `openrouter-chain-reliability.md`

Make the bot's primary text-generation chain reliable by wiring Groq into the chain ahead of the flaky OpenRouter free-tier models that were causing most `!all` replies to render as `fallback_data_only`.

## 13. Fix the narrative-cleanup step that keeps failing — DONE 2026-05-22

**File:** `narrator-batch-sanitize.md`

Stop the evidence-sanitization LLM step from silently truncating evidence to 50 characters when the free-tier chain fails — either drop the sanitize step or move it to a reliable provider.

## 14. Fix missing direction on manual !all alerts — DONE 2026-05-28

**File:** `crossref-direction-none.md`

Stop manual `!all <TICKER>` from being treated as direction=`"neutral"` (which silently disables catalyst mining and other direction-gated features) by using the StructuredFields direction instead.

## 15. Stop fallback messages reaching Discord users — DONE 2026-05-22

**File:** `narrative-fallback-data-only.md`

Stop shipping ambiguous "narrative auto-redacted" embeds to users when the LLM chain exhausts — either say plainly what happened, retry in background, or fix the chain so it doesn't exhaust.

## 16. Update 13 broken unit tests — DONE 2026-05-22

**File:** `stale-unit-tests-all-refactor.md`

Update 13 stale unit-test assertions that the `!all` refactor and critical-sources change left behind.

## 17. Transcribe every YouTube video in full, start to finish (CRITICAL) — DONE 2026-06-15 (verified working)

**File:** `youtube_vision_upgrade.md`

LARGELY FIXED 2026-06-10: chunked reading shipped and live — long videos are now read in 15-minute windows (proven live: coverage jumped from an 18.7-minute ceiling to full window coverage on the 105-min evidence video), short videos unchanged. What remains open: videos LONGER than 90 minutes still lose their tail (the 6-window cap), and the partial-read alarm flags them — decide whether to raise the cap (more Gemini quota per video), buy Supadata caption credits, or accept the 90-min ceiling. Also watch the next few nightly runs to confirm real long videos now log full coverage.

## 18. Read live options flow and alert on unusual activity — DONE 2026-05-29

**File:** `options-flow-realtime.md`

Teach the bot to read near-real-time options data and alert on unusual flow. **Shipped:** FREE source = yfinance ~15-min chains (verified live); `scan_options_flow` (Balanced thresholds vol/OI≥5, vol≥500, premium≥$250k) + `options_flow` table + 15-min `options_flow_loop` (active watchlist ∪ fixed liquid core) firing instant alerts (per-ticker cooldown, staleness filter) + `!all` feed. Verified end-to-end on real data (MSFT $80M call sweep, NVDA $77M put detected; loop dedup/cap/cooldown/persist proven). Live alerts fire during market hours. Optional future upgrade: Tradier brokerage account for real-time-free (needs signup).

## 19. Research YouTube DB weighting in the score — DONE 2026-06-01 (verified already weighted)

**File:** `youtube_db_score_weighting.md`

Figure out whether YouTube database signals (video mentions, extracted levels) are currently weighted in the `!all` score, and whether they should be — then implement if the answer is yes. **DONE 2026-06-01 (run `latency-speedup` Pass-0, code-verified):** YouTube DB signals ALREADY feed the numeric score — `cross_reference.py` adds 15/10/5 pts by conviction → `breakdown.youtube` → `models.total`; rendered as `yt=N` in the footer (`embed.py:502`); direction parity via `_BULLISH_BIASED_FIELDS`. May-31 commit `2196ba5` made it visible (NVDA `yt=15`, AMD `yt=5`). No build needed (a well-evidenced "already weighted — here's where" is a valid done). Weight values 5/10/15 left unchanged (conviction-tiered, shared with the main scorer — changing them would alter live alerts).

## 20. Turn the Wolf market newsletter into a trade-finding brain — phase-1/2/3/4 LIVE

**File:** `wolf-macro-brain.md`

Read the Wolf on Wall Street emails (text + charts) so the bot tracks market tops/bottoms, sector rotations, and catalysts, and proactively flags actionable trades — louder when other sources agree. **Phase-1 (conviction tracker), phase-2 (cross-source confluence), and phase-3 (Gmail history backfill — 79 emails→72 theses — + midday/nightly/Sunday digest scheduler) are ALL LIVE in #news as of 2026-06-01 (user sign-off; commits 29ca428, d0cec7d, 99f2023, 9b6d3d4, 1977cd9, 14ae843), end-to-end verified. **Phase-4 BUILT 2026-06-02** (discover run `wolf-phase4`): #2 beneficiary inference (new `wolf_beneficiaries` v18; Codex-gated; ranked LONGs per macro/sector thesis, labeled "bot's read") + fixes #3 (thesis-alert retry) / #4 (scope canonicalization + live remap) / #5 (allowlist split). Commits 94ec4f7, 9fb9672, 35487fc, 4217c73. Regression gate clean (1686 pass). **#2 WENT LIVE 2026-06-02 (commit e6487db, user "go fully live"):** both flags on, engine restarted + verified (loop started, 9 picks/5 theses precomputed, live render confirms the #news section); first real post on the next scheduled digest window. **Confluence-into-!all DONE+LIVE (verified 2026-06-16, run todo-active-sweep — real !all NVDA shows the 🤝 Confluence line).** **Inverse "goes dark" watch BUILT+LIVE 2026-06-17** (run todo-followup-build): `/root/task_system/scripts/wolf_confluence_dark_watch.sh` + systemd timer `wolf-confluence-dark-watch.timer` (every 6h, Persistent). Read-only renderable-count query; pings `notifications.log` (+ best-effort #news) ONLY if the count drops to 0 (section silently blank). Retry-guarded so a transient DB lock can't fake a "dark" alarm. Verified: healthy run (count=10) stays silent; dark branch writes the alert; runs clean under systemd. **2026-07-03 (active-items-audit):** the two "remaining phase-3/4 RS follow-ups" were confirmed **already SHIPPED 2026-06-02** — 1-month RS horizon = `wolf.beneficiaries.rs_window_days:21` (a closed user decision; research rec was 63d), large-RS anti-chase guard = `extended_pct:45`/`extended_penalty:0.7` (commit `98e0de9`, `wolf_beneficiaries.py:312-317,401-405`, 2 tests). NOT outstanding. All named phase-1/2/3/4 work is live. **Kept OPEN (user, 2026-07-03)** only for one unscoped idea: **widen the confluence/flow inputs** — today just 2 signals feed confluence (news catalyst + options-flow direction); needs a definition of "wider" before it's buildable.

## 21. Auto-switch web-search keys when one runs out — DONE 2026-06-01

**File:** `serpapi-key-failover.md`

Make the bot rotate to the next SerpAPI key (or provider) with credit when the current one hits its monthly limit, instead of silently going dark — the bot was stuck on one exhausted key while two others had quota.

## 22. Sharpen the !all risk section (round 2) — DONE 2026-06-01

**File:** `all-risk-section-v2.md`

Fix the quality defects a Gemini head-to-head exposed in the merged Risk Considerations: drop the weak "1.3% short interest → squeeze" noise bullet, use real positioning/overextension data instead, make the no-price rule mechanical, close a gate bug, and stop internal tags ([macro_risk], COMPUTED SIGNAL) leaking into the Discord text.

## 23. Show Wolf trade ideas instead of raw levels — DONE 2026-06-03

**File:** `wolf-trade-idea-display.md`

When Wolf frames an actual trade, show a concise trade idea (entry → target + stop) on the #news alert instead of a confusing list of same-role price levels; otherwise relabel the levels (broken support → resistance, downside → target).

## 24. Pick the best/cheapest AI models for the bot — DONE 2026-06-04

**File:** `model-bakeoff-2026-06-04.md`

Re-tested two dozen OpenRouter models for speed, smarts, and reliability and rebuilt the primary, text, and ask/mention model chains with the best cheap picks (full rankings + raw data saved for future reference).

## 25. Stop cutting off long Wolf newsletters — DONE 2026-06-05

**File:** `wolf-extraction-input-cap.md`

Raise the limit on how much of each Wolf email the bot reads (12,000 → 40,000 characters) so trade calls in the back half of the long "Daily Wrap" editions aren't silently dropped.

## 26. Catch Wolf's hedged direction changes + retire stale calls — DONE 2026-06-15

**File:** `wolf-hedged-stance-and-stale-theses.md`

When Wolf softly changes his mind on a stock (e.g. IGV: bullish-to-target, then "now I'm looking to short") or an old call goes stale after the move already happened, the bot should update instead of keeping his old view — this session had to hand-fix a stale IGV "bull". **DONE 2026-06-15 (run todo-sweep-2026-06-13):** root-cause prompt fix in `_DIRECTION_GUARD_RULE` — narrowed the "back-test a level" carve-out to uptrends, added a topping-context override (bounce/back-test UP to a level FROM BELOW + toppy/neckline/H&S/lower-high → resistance/bear) + stopped the "200-day"→phantom-$200 misread. A/B vs the live extractor (gpt-oss-120b, N=10/arm, 5 real emails): IGV bull 5/10→0/10 (now bear w/ $100 resistance), SPX/NDX 9/9 bull→8/7 bear, controls unregressed. Corrected the live IGV id-140 bull→bear. Built a codex-hardened nightly **staleness sweep** (`wolf_staleness.py`): stage-split caps (imminent 18d / forming-diverging 30d / acting 90d), real-reaffirmation clock (a misread can't keep a dead thesis fresh), polarity-normalized same-complex contradiction, demote-not-delete to a `stale_review` state, ingest-revival on explicit reaffirmation + manual override. LIVE — first run demoted 8 genuinely-stale theses (VIX bear 46d, DJIA/RUT ~37d, SILVER/COPPER/KWEB ~31d, DBA/VEGI 18d), left fresh ones. Beneficiary orphan prune wired (cleared 16 stale rows). Commits 241b873/bcb9d1c. 11 tests.

## 27. A/B the !all "tidy text" step, then turn it off — DONE 2026-06-09

**File:** `sanitize-ab-then-flip-off.md`

You approved turning off the AI "tidy text" pass on `!all` (saves ~9 AI calls per command) once an A/B check confirms the free models don't start inventing numbers without it — held this session because the providers were flaky; sanitize is still ON.

## 28. Evaluate the SMART LEVELS shadow soak, then decide go-live — DONE 2026-06-09 (LIVE)

**File:** `smart-levels-shadow-evaluate.md`

The new chart-based buy/stop/target engine for `!all` is running in shadow (logs only, no visible change) — after a day, compare its numbers to the current ones and decide whether to switch it on for real.

## 29. Fix the issues found in the 2026-06-08 deep-dive — DONE 2026-06-09

**File:** `session-findings-2026-06-08-part2.md`

Bundle of investigated fixes — get the bot reading Wolf charts again (vision-model benchmark done), purge fake test data from the live database, add one shared "is this price level sane?" check before anything is shown, make the Discord outage self-heal or alert, add clickable TweetShift links to #news, stop YouTube video bursts from blowing the free Gemini quota (whole batches failing) with a durable day-to-day transcription queue, and make a feature un-markable as "done" until a live test proves it works. (The unusual-options-flow threshold 5×→10× from this batch was already applied + committed 2026-06-08.)

## 30. Turn on Wolf chart-reading — DONE 2026-06-09

**File:** `wolf-vision-go-live.md`

DONE — Wolf chart-reading is LIVE. The free AI vision models proved unreliable (they all share OpenRouter's throttled free pool — not separate provider outages), so it now reads ALL charts in every Wolf email with the cheap paid model gemini-2.5-flash-lite (about 2 cents a day). Proven 10/10 charts read with zero failures.

## 31. Clean up scrambled YouTube chart numbers + guard the !all trade plan — DONE 2026-06-10

**File:** `mis-attributed-yt-levels-sweep.md`

A multi-stock YouTube video dumped QQQ/SPY numbers (700–760) onto NVDA, which made !all show a $700 target on a $208 stock — found and fixed for NVDA at session close, but other tickers/videos may be scrambled too; sweep the stored data and add a safety filter so a wild number can never reach the !all trade plan again.

## 32. Switch on the Phase-2 signal upgrades after their watch windows  — DONE 2026-06-29

**File:** `signal-features-phase2.md`
**Switches:** features.single_score.enabled=on; features.contradiction_index_live.enabled=on; features.strong_requires_hard_evidence.enabled=on; features.apewisdom_zscore.enabled=on; features.cross_asset.enabled=on; features.finra_short_volume.enabled=on; features.consensus_logodds.enabled=noop; features.regime_widening_graduated.enabled=noop

**CURRENT STATUS (2026-06-27):** essentially DONE — every signal switch that actually does something is now ON (E2, the last one, went live 2026-06-26). The only two still off — I7 and I14-widening — are dead switches: a flip changes nothing until new code is written, so they're correctly left off. One live-check is owed: E2 hasn't touched a real alert yet because the weekend pause began right after it went live; an automatic check runs **Mon 2026-06-29 4pm PDT** and pings `notifications.log`. If that's ✅, this item is fully done. Dated history of each flip is below.

2026-06-10: conviction scoring FIXED and live, all 10 Phase-2 upgrades BUILT (off, gathering measurement data in the logs), and the 9 Phase-1 fixes TURNED ON and live-tested — what remains is reading the measurement lines after ~2 weeks (contradiction warning, hard-evidence gate, market-stress veto), tuning the freshness caps from that data, and flipping the Phase-2 switches on one at a time (the Reddit-mentions gate becomes eligible ~June 24 once 14 days of baseline accumulate). **2026-06-15 (Step 1 done, run todo-sweep-2026-06-13):** built the Codex-required offline **alert-replay harness** (`scripts/alert_replay_e1.py`, bounds the user-visible alert delta, not just term fire-rate); found+fixed E1's real blocker (no daily FINRA fetch loop existed — the table was a one-time backfill frozen at 06-12; added `finra_short_volume_loop`); flipped **E1** (replay: ≤177 candidates, +5 cap, 0 current changes, fails safe on stale data) + **I15** weighted Wolf votes (dry-run on 17 theses: 0 tier changes, 0 new criticals). **Still deferred BY DESIGN** (research+Codex: flip ONE AT A TIME after I4-full soaks — live-alert blast radius): I4-full, I3, I10, E2-VIX, plus the regime_daily seed (I14) + consolidation un-shadow (I7) enablers. I13 ApeWisdom eligible ~June 24. Commit 86ad572. **2026-06-15 (later, same session):** user provided a FRED API key (`.env.service`) → **E2-FRED leg BUILT** in `cross_asset.py` mirroring the VIX leg (HY credit spread BAMLH0A0HYM2, current/60d-baseline ratio → averaged with VIX, clamped); 24 new tests pass, proven live end-to-end (VIX 1.15 + credit 1.023 → combined 1.086); stays dark behind the E2 master gate (`features.cross_asset.enabled: false`) — both legs now flip together when E2 is eventually turned on. Also: **E1 confirmed firing** on fresh Monday data (CRWV, SMH qualify today), and the openclaw transcript-hygiene + memory-path config went **LIVE** via a clean gateway restart (bot @-mention healthcheck replied).

## 34. Research and wire in Apify as a new signal source — DONE 2026-06-26 (skipped)

**File:** `apify_research_and_integration.md`

**SKIPPED 2026-06-15 (user directive):** the only budget-viable actor (Seeking Alpha via `doesaiknow`) returns 200-empty/500 unreliably (upstream throttle, not fixable by us), and the unique value (per-ticker news) is already covered free by the `google_rss` cascade tier + Finnhub. Verified nothing in code/config/scripts reads Apify, so the keys were orphaned env vars — removed `APIFY_TOKEN`/`APIFY_PROXY_PASSWORD`/`xxxxxAPIFY2_TOKEN` from all 3 env files (backed up to `/root/apify-keys-removed-2026-06-15.txt`, ownership preserved). No build.


Research DONE 2026-06-10 (live probes, $0.19 spent): the winner is the Seeking Alpha news feed (~$1–1.50/month per ticker, real engagement counts, fits the free $5 plan at full polling speed); Reddit costs ~60x the old estimate (only 1–2 snapshots/day fit) and returns no upvote counts; Finviz needs no Apify at all (this server can fetch it directly, free). Awaiting your pick before building — suggested split: Seeking Alpha via Apify + a free direct Finviz feed + optional once-daily Reddit snapshot.

## 33. Fix the !all Groq 400 "allowed_mentions unsupported" error — DONE 2026-06-10

**File:** `all-command-groq-400-allowed-mentions.md`

The `!all` summary call to Groq's primary model is getting rejected with HTTP 400 because a stray `allowed_mentions` property (a Discord field that has no business in an AI request) is somehow in the request body — find how it gets there and strip it, so Groq actually serves `!all` instead of instantly bouncing to the slower fallback models. (Separate from the 413 size error fixed this same session.)

## 35. Make the bot read bare tickers as stocks (WEN ≠ haircare) — DONE 2026-06-15

**File:** `mention-ticker-disambiguation.md`

When you ask the bot about a ticker in chat (e.g. "tell me about WEN"), its web-search answer can latch onto the wrong meaning of the word — it described WEN haircare products instead of Wendy's stock (user caught this 2026-06-10); teach the conversational answer path to resolve ticker-shaped words to their company first, so questions about any ticker always come back about the stock. **DONE 2026-06-15:** `_handle_mention` now resolves ticker-shaped tokens via a chat-specific policy (NOT the scanner blacklist, which wrongly blocks SPY/QQQ/GAP) — hard-anchors real listed companies (APP=Applovin, GAP=Gap, SPY, QQQ...), soft-anchors slang homographs (WEN, FED, AI advisory: "if a stock it's <Co>, else answer normally"), skips grammar/tech-acronym words unless $-prefixed; Finnhub/cache real-company gate; capped at 5. **Live-verified**: "tell me about WEN" → bot replied "Wendy's Co (WEN), NASDAQ, fast-food chain". Commits 03eee26/190330e. 10 tests.

## 36. Fix 6 issues diagnosed 2026-06-11 (gateway, bot warnings, P/E, TweetShift field, smart levels, !help) — DONE 2026-06-11

**File:** `tweetshift-bullbear-field.md`

Six issues diagnosed 2026-06-11: gateway crashes on reboot, bot @-mentions return health warnings instead of answers, Fwd P/E uses wrong EPS window, !all has no TweetShift bull/bear count, smart levels reports closing price as "current", and !help is stale and unverified.

## 37. Fix the stale YouTube video-parser test (chunking) — DONE 2026-06-13

**File:** `gemini-chunking-test-stale.md`

Update the video-parser unit test that broke when the #17 chunked-reads feature landed (it's parked in the test baseline; the live feature works fine) so the regression gate isn't blind there.

## 38. Finish clearing openclaw doctor warnings — DONE 2026-06-29 (orphan transcripts cleared; only intentional warnings remain)

**File:** `openclaw-doctor-warnings.md`

One command (run as root) to fix the brave plugin ownership warning, plus optional cleanup of 142 archived transcript files still showing in doctor output. **2026-06-15:** brave duplicate deleted (npm copy serves search). The 6 Discord-channel chat transcripts are now preserved as #39 rollups and will be auto-deleted by #39's 30-day gated cleanup; the 142 raw archives were copied to a restricted-perms corpus (`archive/deleted-transcripts-2026-06-15`). Remaining: the ~132 non-channel `.deleted.` session files (cron/dreaming) + the 3 intentional warnings (symlink dual-path, task-registry sidecar, missing OAuth dir — leave as-is). Mostly resolved; stays open for the non-channel orphans.

## 39. Redesign the bot's chat memory so it stays small but can recall month-old summaries — DONE 2026-06-15

**File:** `bot_chat_memory_redesign.md`

Keep each channel's live chat context from growing big enough to slow the bot or starve its reply, while preserving past conversation as summaries the bot can look up later — even from a month ago. **DONE 2026-06-15 (architecture b):** new `chat_memory_rollups` table (codex schema: source_sha256 identity + status) + `memory/chat_rollup.py` summarizer (parse transcript → extractive date-bucketed rollup → REDACT secrets → idempotent sha-keyed write). Eval on the real 510KB #chat archive: 47x compression, 0 secret leaks, correctly recalled the month-old NVDA root cause + refused a hallucination trap. Recall is on-demand via the agent's existing DB access (steering prompt names the table + channel_id). Nightly `chat_memory_loop`: budgeted backlog drain + identity-gated cleanup (delete a raw archive only on exact sha256 + status=complete + byte match, 30d retention). openclaw.json hygiene: truncateAfterCompaction + maxActiveTranscriptBytes 5mb + repointed memorySearch.extraPaths to the live dir. LIVE — first run summarized 6 channel transcripts. Commit ba91341. 10 tests.

## 40. Assessment of Claude's repeated reasoning failures (2026-06-13 session) — DONE 2026-06-26

**File:** `reasoning-failures-assessment-2026-06-13.md`

A diagnosis-only record of how Claude's own reasoning failed six times in one session — the core application-gap problem, the specific failures, the bottlenecks behind them, and why they matter (no fixes or suggestions, by request).

## 41. Make "build → test on the DB → switch on this session" the standing rule — DONE 2026-06-16

**File:** `build-test-flip-on-same-session.md`

Decide where to write down (and how to word, without bloat) the directive that every future feature must be built, proven accurate against the historical database, and switched ON before the session ends — never left off "for testing later," only if genuinely broken or data-blocked.

## 42. Turn on the remaining signal switches (flip ledger)  — DONE 2026-06-29

**File:** `signal-flip-status-2026-06-15.md`
**Switches:** features.single_score.enabled=on; features.contradiction_index_live.enabled=on; features.strong_requires_hard_evidence.enabled=on; features.apewisdom_zscore.enabled=on; features.cross_asset.enabled=on; features.finra_short_volume.enabled=on; features.consensus_logodds.enabled=noop; features.regime_widening_graduated.enabled=noop

**CURRENT STATUS (2026-06-27):** essentially DONE — every switch in this ledger that has a real effect is now ON, E2 included (live 2026-06-26). Only I7 and I14-widening remain off, and both are proven no-ops (a flip changes nothing without new code first). The same E2 live-check as #32 is owed (auto-check **Mon 2026-06-29 4pm PDT**). Full per-switch state is in the detail file; dated history is below.

The one place that lists every bot switch touched in the 2026-06-15 build: what's ON now (Wolf direction guard, staleness sweep, EPS-revision + Stocktwits `!all` fields, chat memory, weighted Wolf votes, FINRA short-volume), and what's still OFF with the reason and exactly what's needed to flip each one — the four scoring switches that must go on one-at-a-time after I4-full soaks (I4-full, I3, I10, E2-VIX), the two that need an enabler built first (I7 needs consolidation un-shadowed, I14 needs the regime table seeded), and ApeWisdom (data-blocked until ~June 24). **Updated 2026-06-15 (later):** FRED leg is now **BUILT** (key provided) and rides inside the E2 master gate — both VIX and credit legs flip together; E1 is **live+firing** (CRWV, SMH today); and the openclaw transcript-hygiene + memory-path config is **LIVE** (gateway restarted, bot verified responsive). Only the one-at-a-time scoring flips (I4-full → I3 → I10 → E2 master) + the two enablers (I7, I14) + ApeWisdom remain. **Updated 2026-06-17 (run todo-followup-build):** **I3 flipped ON** — `contradiction_index_live.enabled: true` with a new ≥2-distinct-opposing-sources gate so one lone opposing source can't downgrade a thin STRONG; backtest impossible (all 1949 snapshots have ci=0.0), validated by 17 unit tests + forward `[A1]` shadow watch; `n_opposing` now persisted on new snapshots. Evidence: `.claude/go-live-evidence/features_contradiction_index_live_enabled.md`. **I4-display Breakdown fix shipped** (Breakdown line now resolves to the gated headline number — first slice of #46). **NOTE on the two "I7"s:** the user's "I7" ask = the loud **analyst-herding SWARM alert**, now **LIVE 2026-06-17 (user GO)**. Final spec (user redesign, supersedes the first 4-analyst one-shot): opens at **2 distinct analysts** within 60 min, stays live **24h fixed from open**, **@-pings the user (615525529537216513) on every new analyst that joins** (same analyst repeating = no-op; title shows elapsed span e.g. "5 analysts tweeting in 5 hours"). New `detect_swarm` + `swarm_state` table (survives restarts); ping delivery **verified live** (Discord returned the user in the response `mentions`, our anti-ping guard didn't strip it). Volume backtest (50d real history): ~7-9 pings/day. User's dial if noisy: change the opener from 2→3 analysts. The `consensus_logodds` *scoring* flag (also historically labeled I7, consensus.yaml:808) stays **OFF** — still needs consolidation un-shadowed; untouched.

## 43. Replace the retired backup AI model in the text chain — DONE 2026-06-15

**File:** `dead-text-model-swap-2026-06-15.md`

Swap out the dead NVIDIA backup model the health check flagged with a live one, so the text model chain has a working second fallback.

## 44. Bake off the best AI models for the three chains (text / primary / agent) — DONE 2026-06-15

**File:** `model-bakeoff-2026-06-15.md`

Live-test current cheap OpenRouter models against the three jobs (tweet-scoring/cleanup, big-writing, question-answering) to confirm we're using the best fit; swapped the text backup to a 4×-cheaper equal (qwen3-235b), and found the question-answering model times out on heavy questions — full results logged for future model decisions.

## 45. Fix the agent tool-loop context blow-up (heavy questions can time out) — DONE 2026-06-16

**File:** `agent-tool-loop-context-blowup.md`

When the bot answers a heavy question that needs lots of tool calls, some AI models keep piling up search results until they run out of time and the user gets "Agent unavailable" — fix the underlying loop (likely un-trimmed tool results / no round cap) so a future model swap can't silently bring the timeouts back.

## 46. Show every score on one consistent scale (0 = low, 100 = high) — DONE 2026-06-21

**File:** `unified-display-scale.md`

Every number the bot shows (alert score, !all breakdown, contradiction, market mood, LLM confidence) is on a different scale, so the user can't tell what's high or low — normalize all user-facing readings to one consistent 0–100 low→high display, without changing the underlying math.

## 47. Build an accurate market top/bottom detector (research how others did it) — !market dashboard LIVE 2026-06-29; predictor PARKED (paid data deferred, no free path)

**File:** `vol-indicator-accuracy-research.md`

**CURRENT STATUS (2026-07-03):** Two halves. The **descriptive** half (the `!market` dashboard — Wolf's market theses + a volatility-regime label) is **LIVE**. The **predictor** half (actually calling tops/bottoms) is **PARKED**: proven NO-GO on free daily data across 5+ rigorous phases, and the only build path needs paid data the user has deferred (no spend now) — so there is no open decision here, nothing to do. Free path still accruing in the background: `vol-collect-daily.timer` keeps logging CBOE put/call + NYSE breadth, and #55's 5d/20d outcome grading builds the matching horizon, so a $0 re-test becomes possible in a few months. (Supersedes the old "~$50 AlphaVantage = the only open decision" line — that framing is retired.)

Catch SPY/QQQ tops and bottoms early with few false alarms — the daily-data approach is exhausted (proven NO-GO with real rigor), so the next move is a research mission to find how others actually accomplish this (likely with richer data inputs we don't yet have), then a plan and an adversarial review.

## 49. Clean up the Claude memory index file — DONE 2026-06-20

**File:** `fix_claude_memory_md.md`

Restructure MEMORY.md so each entry is a short one-line pointer (as designed), not a content summary — backup at `memory/MEMORY.md.backup-2026-06-20`.

## 48. Stop the same stock double-alerting from different YouTube videos — DONE 2026-06-18

**File:** `youtube_standalone_alert_cooldown.md`

Optional: add a per-ticker cooldown so the "a YouTuber likes $STOCK" alert can't post twice for the same ticker when two different videos mention it in one poll cycle — build only if live use shows it's spammy.

## 50. Make !scan and !market-view scores agree (and fix a wrong help message) — DONE 2026-06-21

**File:** `scan-marketview-score-coherence.md`

The same stock can show two different "Score" numbers at the same moment — `!scan` runs a fresh check and saves nothing, while `!market-view` shows the last real-signal verdict (often stale or absent) on a different scale; also the bot wrongly tells users to "run !scan first" to create a verdict, which scan never does. Make the two commands coherent and fix the misleading text.

## 51. Add a !em command that shows a stock's expected daily move — DONE 2026-06-25

**File:** `em_command.md`

Let users type `!em SPY` to get the options market's expected up/down range for the day (or the next session if the market has closed), shown as a clean embed with a candlestick chart.

## 52. Make explanations clear and consistent (one yardstick, no flip-flopping) — DONE 2026-06-27

**File:** `clear-simple-explanations.md`

Stop giving convoluted explanations that switch reference frames mid-answer (e.g. "puts are half of calls" then "twice as many calls as puts"); hold one consistent, simple framing — and verify clarity by comparing against real Gemini and ChatGPT answers to the same prompts.

## 53. Show every bot reading on an intuitive, shared scale — DONE 2026-06-27

**File:** `intuitive-display-scales.md`

Roll out the !options percentage idea everywhere: convert readings computed in unintuitive internal scales (ratios, z-scores, raw counts) to an intuitive display scale in Discord, and give same-type readings one shared scale so learning to read one teaches you all of them. (!options is the shipped reference — see detail file.)

## 54. Make the bot more reliable, then turn on the cautious switches — DONE 2026-07-04

**File:** `reliability-hardening-soak.md`

**CURRENT STATUS (2026-07-04) — DONE:** All 15 reliability fixes live; **all 7 switches now ON**. The 5 cautious ones were flipped 2026-07-04 after the soak was **evaluated early** — markets are closed Fri–Sun so no source-health data accrues then (last Saturday logged 6 events vs ~400/weekday), making the "7 calendar days" really 4 trading days (Jun 29–Jul 2), already observed. Data cleared all 5: `social.market_cap_failclosed` (0 validation errors → drops nothing), `retry.use_classifier` + `adapters.report_failure` (internal-only, can't drop/block an alert), `circuit_breaker.enabled` + `dead_source.ops_alert_enabled` (only `exa` is dead = 1296 backoffs; the 3 healthy news sources = 0; none are instant-alert triggers so no real alert can be silenced). Flipped in 3 risk-tiered cycles; engine restarted + verified clean between each (NRestarts=0, healthy sources still polling — 18 activity lines post-breaker, Discord READY). Go-live evidence in `.claude/go-live-evidence/` (5 files). Redundant Sunday soak timer stopped + disabled. **One live watch owed:** confirm the breaker opens `exa` (not a healthy source) on the next real web-search hit — its shadow mode already showed this, but eyeball it next trading day.

Ship 15 reliability/efficiency fixes to the live bot (stop hangs, dead-source retries, and event-loop stalls), turn on the proven-safe ones now, and after a 7-day soak decide whether to turn on the 5 cautious switches (dead-source cutoff, junk-ticker skip, smarter retries).

## 55. Start saving the data future features need to test on — Tier-1 Items 1+2 + Tier-2 #3/#5 LIVE 2026-06-29 (analyst scorecard shadow-only; promotion soak-gated)

**File:** `forward-data-collection.md`

**CURRENT STATUS (2026-07-03):** Scorecard shadow-delta analysis DONE (the promotion decision-support the audit asked for). **Verdict: HOLD — do not promote the analyst scorecard to live yet.** Framing correction: the 3 consuming flags (`per_analyst_cooldown`, I2 `analyst_accuracy_weight`, I10) are ALREADY `enabled:true`; they only no-op because the live `source_performance` table is empty, so "promotion" = filling that table, not flipping a switch. But at the **1-hour** horizon those flags read, NO analyst beats a coin flip at 95% confidence (best Wilson lower-bound **0.484 < 0.50**, n=48). So promoting today only lets I2 **demote** ~1.5 STRONG alerts/month (QCOM + META) — never upgrade — downside with no measured upside; per_analyst_cooldown and I10 change 0 and 0. **Two cheap prep steps before any future promotion:** (a) repoint the readers from the near-random `1h` horizon to the honest `24h` (the producer's own docstring calls 1h "near-random") — no effect today (table empty) but the correct base; (b) gate promotion on a real stat threshold (≥1 analyst Wilson-LB > 0.50 at the used horizon — needs ~2.5× more samples for the leader unusual_whales). The 3 live loggers keep accruing meanwhile. Full analysis notes in the detail file.

**STATUS (2026-06-29):** The #1 unlock is LIVE — alerts are now graded at **5 and 20 days** later, not just 1h/24h. `decision_snapshots` got `outcome_price_5d`/`outcome_price_20d`; the live engine fills them forward and history was backfilled (2,154 5-day labels, 890 20-day). This starts the data clock to re-test the failed trade-edge features (sector-rotation/factor/trend) on a matching horizon in ~2-3 months. Still open: the `source_performance` producer (Tier-1 Item 2) and the point-in-time logging (Tier 2/3).

Begin a cheap forward-log of the inputs and outcomes future features will need — most importantly grading every alert at 5 and 20 days later (not just 1 hour and 24 hours) — so the next time we build a slow-signal feature it already has history to prove itself on instead of failing for lack of recorded data.

## 56. Buy 2 years of options history and backtest the options signals — PARKED (paid data deferred; free forward-log path accruing via #55)

**File:** `options-history-backtest.md`

**CURRENT STATUS (2026-07-03):** Nothing built. The buy-2yr-history route is **PARKED** — it needs paid data the user has deferred (no spend now). A **free alternative is already accruing**: #55's forward-loggers (`options_flow` 110k+ rows and growing, plus 5d/20d outcome grading) capture the same fields going forward, so the same backtest (did the vol/OI≥5, vol≥500, premium≥$250k unusual-flow rule actually predict the move?) can run on collected data for $0 in ~a few months. No action now — let #55 accrue, then build the replay harness. Independent of #57 (Schwab's snapshot logger only holds ~days of derived summaries, not raw chains).

Pay ~$29 once for 2 years of historical options data (massive.com) and use it to backtest the unusual-options-flow alerts and feed the market top/bottom detector — testing whether our options signals actually caught the big drops and rallies of the last 2 years.

## 57. Move live options data onto the Schwab real-time feed — BUILT + LIVE 2026-06-30 (on-demand ON); autonomous flow-loop alert switch FLIPPED ON 2026-07-02 (watched flip; alert footer fixed; soak → verify live alerts Mon 07-06, then DONE)

**File:** `schwab-options-realtime.md`

**Switches:** features.schwab_options.enabled=on; features.schwab_quotes.enabled=on; features.schwab_ohlcv.enabled=on; features.schwab_snapshot_logger.enabled=on; features.schwab_options.flow_loop_enabled=on

**CURRENT STATUS (2026-07-03):** Closed the last stale-footer mislabel — the `!em` (expected-move) command also runs on Schwab real-time now (`expected_move.py`), but its footer still hard-coded "yfinance · delayed". Threaded a `source` field through `ExpectedMoveResult` so `_fmt_quote_time` labels the real feed: Schwab → `Schwab · real-time · quote 7:30 AM PDT`, yfinance fallback keeps the honest `· delayed`. 14 expected-move tests pass (2 new). Still soaking on the main item: verify Monday 07-06's live flow alerts, then mark DONE.

**CURRENT STATUS (2026-07-02 eve):** `flow_loop_enabled` FLIPPED ON (watched flip). Engine restarted + healthy; the misleading "~15-min-delayed" alert footer removed. Real alerts start Mon 2026-07-06 open (market was closed at flip); the Mon 10:00 PDT numbers run + a live-alert review will tune thresholds from real data. Verify Monday, then mark DONE. Evidence: `.claude/go-live-evidence/features_schwab_options_flow_loop_enabled.md`.

**CURRENT STATUS (2026-06-30 eve):** BUILT + LIVE. `!options`, `!em`, `!all` max-pain, live quotes, and OHLCV (peer-RS/VIX) now run on Schwab's real-time feed with yfinance/Finnhub auto-fallback; daily options-history logger + weekly re-auth reminder timers enabled; 2522 tests pass, 0 regressions; engine restarted + healthy. ONLY the autonomous unusual-flow ALERT loop (`flow_loop_enabled`) stays OFF — its thresholds were tuned on the delayed feed and the market was closed tonight, so a Schwab-vs-yfinance shadow-compare is scheduled for 2026-07-01 10:00 PDT (posts a verdict to #chat); flip it after reading that. Re-auth (weekly Schwab re-login) due ~2026-07-07 6:56pm PT.

Swap the bot's live options source from the free, ~15-min-delayed, throttle-prone yfinance feed to the user's real-time Schwab Trader API — upgrading the `!options` command, the unusual-flow alerts in the options-flow channel, and the `!em` expected-move command with official real-time chains and native greeks. Also research everything the Schwab key can do (all endpoints + streaming) and what new bot commands / future features it unlocks.

## 58. Show insider trades with dates and dollar values — DONE 2026-07-01

**File:** `insider-display-refactor.md`

Refactor `!sec`, `!all`, the alert Score card, and the AI write-up so insider (Form 4) trades show as one clean block per person — with the date and total dollar value — instead of dozens of dateless, valueless repeat rows.

## 59. Fix the regression gate so a failed push doesn't just sit there

**File:** `regression-gate-auto-recovery.md`

**CURRENT STATUS (2026-07-03):** Both parts done. **Part 1 SHIPPED** (detection + safety net): (1) `ci-monitor.sh` extracts the REAL failing test ids from the FULL CI log — proven on the 07-02 pyarrow run it names `tests/test_market_command.py::…`, where the old `--log-failed` returned nothing; (2) `session_close.sh` captures the push exit code and writes a loud `notifications.log` line when a push is rejected (the silent hole that stranded 6 commits); (3) a SessionStart banner (`openclaw-digest.sh`) surfaces any GATE/CI/PUSH alert loudly; (4) 07-02 root cause fixed — `scripts/pre-push` per-user `/tmp` log (a stale root-owned one permission-denied `tee` → aborted the hook → silent reject), synced to `.git/hooks/pre-push`; `notifications.log` openclaw-writable. **Part 2 LIVE — deterministic, NO AI, no login:** `/root/task_system/scripts/ci_autofix.sh` runs as openclaw when the gate is red and: (1) **auto-declares an undeclared dependency** — the exact pyarrow class: extracts the missing module from the CI error (incl. pandas' "Missing optional dependency 'X'" phrasing, the real 07-02 signature), adds it to requirements.txt, verifies import + tests pass, commits + pushes; (2) detects **flaky** (passes locally ×2 → no-op); (3) **escalates a real logic bug** to a human. Guardrails proven end-to-end: capped retries (fires at 2), clean-tree freshness skip (won't touch a session's unpushed work), HARD forbidden-path gate (never auto-pushes a config/flag/vision/go-live/CI change), local re-verify, `git checkout` (never stash). Verified on the real pyarrow run (extracts 'pyarrow', would add+push; correctly skipped while unpushed work present). **Opt-in AI upgrade (deferred):** a guarded `claude` branch fixes genuine logic bugs unattended — dormant until claude is provisioned for the openclaw user (user away 2026-07-03; deterministic layer chosen as the safe default; Codex has the same root-only-auth hurdle). Note: `ci-monitor.sh`/`ci_autofix.sh` live in `/root/task_system` (not repo-tracked). (pyarrow live symptom already fixed, `ed143c9`.)

When the session-close test gate fails, the push is skipped and nothing else happens — build a process that automatically checks, fixes, and re-pushes; if that's not safely possible, shorten the regression gate so failures are caught and cleared faster; if even that's not feasible, make sure Claude proactively flags the stuck push at the start of the next session instead of staying silent.

## 60. Rebuild the discover plugin on the built-in Workflow engine — DONE 2026-07-02

**File:** `discover_rebuild_build.md`

Build the approved redesign of the /discover plugin — passes 0-4 on Claude Code's Workflow engine with evidence-rule kill-testing and a plan tournament — and ship it as v1.0.0; design and step-by-step plan are complete, no code written yet.

## 61. Run the research-and-build prompt for new bot features and fixes

**File:** `bot-deep-research-prompt.md`

CURRENT STATUS: prompt v2 ready to run — paste `ultracode — read todo/kickoffs/bot-research-and-build.md and execute it end to end` into a fresh session. One run does everything: verifies the bot's real code first, deep-researches improvements across six expert angles (with citations), gets its draft attacked by a second AI before ranking, pauses to let the user pick what gets built in plain English, then builds and verifies the picks. Replaces the older paste-into-an-outside-model prompt (kept as a variant).
