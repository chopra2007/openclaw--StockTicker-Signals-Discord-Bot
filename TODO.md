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

Continue improving what `!all <TICKER>` shows by picking one quality lever per session (max-pain, peer comp, options flow, etc.) from the documented menu. **2026-05-29:** options-flow lever shipped via #18 — recent autonomous-detected unusual flow now feeds the `!all` narrator (`get_options_flow_for_ticker` → structured-data summary). **2026-05-30 (run `all-levers-2026-05-29`):** shipped **max-pain** (weekly+monthly embed field) + **peer relative-strength** (5-day vs sub-industry peers, embed + narrator) + a new sub-industry **peer layer** (`data/peer_groups.yaml`, separate from the A4 gate map). Commits `53e3e35`+`7d77245`, live-verified. **2026-06-01 (run `latency-speedup`):** shipped the **slow-response fix** — `!all` synthesis now gives groq a head-start and races the 2 fallback models only on a stall (`llm.all_command_strategy: head_start`), with a structural-validity guard so a fast incomplete answer can't win, plus a groq circuit breaker. Scoped to `!all` only (6 other LLM callers untouched). Live-verified `!all TSLA`: tail **234s + failed narrative → 82.7s + valid** (commits `85ac88f`/`94d8276`/`9f1f537`). **Root-cause diagnosed 2026-06-01 (after the fix):** the groq "stall" is groq 429'ing on its free-tier **daily** token limit (100k/day, observed Used 98,960). Each `!all` burns ~18-25k groq tokens because the 9-call **sanitize** phase ALSO routes through the groq `all_command_chain` (`narrator.py:183`) on top of the 8k-token synthesis — so ~4-5 `!all` exhausts groq for the day, then everything 429s to the slow free models (the real tail). head_start handles this gracefully but is a symptom-fix. **Recommended root fix: route the 9 sanitize calls OFF groq onto the `openrouter/free` text chain** (trivial cleanup, no premium model needed) — roughly halves groq tokens/`!all`. **2026-06-02 — ROOT FIX SHIPPED + LIVE:** added a groq-free `all_command_sanitize_chain` (`[gpt-oss-120b:free, gpt-oss-20b:free]`); `_batch_summarize` (covers searxng/news/sec/chat/brief batches) + `vault_excerpt` now route through `_sanitize_chain()`; synthesis stays on the groq head-start chain. Commit `5e64656`, fast-forward-merged to master, engine restarted + live-verified `!all NVDA`: production logs show sanitize (role=text) tried ONLY the 2 free models (zero groq), synthesis attempted groq then fanned out, valid embed posted ("$NVDA — Full Analysis", 2061-char narrative). 1670 tests pass. **Observed caveat:** when both free models are transiently flaky (429/timeout, as during the verify run), sanitize degrades to its truncated-text fallback — output stays valid, but the cleanup quality drops that run. Optional follow-up: widen the free sanitize chain with more providers so one provider's rate-limit can't exhaust it. (Also: groq 413s on the source-heavy synthesis request — 12k TPM free-tier cap — so head_start fans out for big tickers; expected.) (2-stage-embed perceived-latency idea: REJECTED by user.) Stays OPEN — more levers remain in the menu (`all-command-quality.md`).

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

## 17. Read precise chart numbers from YouTube videos — DONE 2026-05-29

**File:** `youtube_vision_upgrade.md`

Teach the video-watcher to read the precise chart numbers (gamma lines, option-flow tables) the speaker glosses over. Task B (Gemini limit/model swap) + Task C (chart numbers → `!all` narrator) shipped earlier. **B1** strips title-card/promo/bare-ticker noise; **C1** daily chart-read coverage counter; **C2** Gemini stop-reason telemetry. **2026-05-30 (run `all-levers-2026-05-29`):** **B2** demonstrated — fresh chart-heavy videos do carry both signal+visual rows; surfaced that multi-stock videos dump every number onto the top ticker. **B3** (per-number ticker tagging) BUILT but flag-gated OFF (`youtube.visual.per_number_ticker_tagging: false`, commit `7d77245`) — flip true + restart to test. All of #17 now shipped or built.

## 18. Read live options flow and alert on unusual activity — DONE 2026-05-29

**File:** `options-flow-realtime.md`

Teach the bot to read near-real-time options data and alert on unusual flow. **Shipped:** FREE source = yfinance ~15-min chains (verified live); `scan_options_flow` (Balanced thresholds vol/OI≥5, vol≥500, premium≥$250k) + `options_flow` table + 15-min `options_flow_loop` (active watchlist ∪ fixed liquid core) firing instant alerts (per-ticker cooldown, staleness filter) + `!all` feed. Verified end-to-end on real data (MSFT $80M call sweep, NVDA $77M put detected; loop dedup/cap/cooldown/persist proven). Live alerts fire during market hours. Optional future upgrade: Tradier brokerage account for real-time-free (needs signup).

## 19. Research YouTube DB weighting in the score — DONE 2026-06-01 (verified already weighted)

**File:** `youtube_db_score_weighting.md`

Figure out whether YouTube database signals (video mentions, extracted levels) are currently weighted in the `!all` score, and whether they should be — then implement if the answer is yes. **DONE 2026-06-01 (run `latency-speedup` Pass-0, code-verified):** YouTube DB signals ALREADY feed the numeric score — `cross_reference.py` adds 15/10/5 pts by conviction → `breakdown.youtube` → `models.total`; rendered as `yt=N` in the footer (`embed.py:502`); direction parity via `_BULLISH_BIASED_FIELDS`. May-31 commit `2196ba5` made it visible (NVDA `yt=15`, AMD `yt=5`). No build needed (a well-evidenced "already weighted — here's where" is a valid done). Weight values 5/10/15 left unchanged (conviction-tiered, shared with the main scorer — changing them would alter live alerts).

## 20. Turn the Wolf market newsletter into a trade-finding brain — phase-1/2/3 LIVE; phase-4 BUILT (flag-OFF)

**File:** `wolf-macro-brain.md`

Read the Wolf on Wall Street emails (text + charts) so the bot tracks market tops/bottoms, sector rotations, and catalysts, and proactively flags actionable trades — louder when other sources agree. **Phase-1 (conviction tracker), phase-2 (cross-source confluence), and phase-3 (Gmail history backfill — 79 emails→72 theses — + midday/nightly/Sunday digest scheduler) are ALL LIVE in #news as of 2026-06-01 (user sign-off; commits 29ca428, d0cec7d, 99f2023, 9b6d3d4, 1977cd9, 14ae843), end-to-end verified. **Phase-4 BUILT 2026-06-02** (discover run `wolf-phase4`): #2 beneficiary inference (new `wolf_beneficiaries` v18; Codex-gated; ranked LONGs per macro/sector thesis, labeled "bot's read") + fixes #3 (thesis-alert retry) / #4 (scope canonicalization + live remap) / #5 (allowlist split). Commits 94ec4f7, 9fb9672, 35487fc, 4217c73. Regression gate clean (1686 pass). **#2 WENT LIVE 2026-06-02 (commit e6487db, user "go fully live"):** both flags on, engine restarted + verified (loop started, 9 picks/5 theses precomputed, live render confirms the #news section); first real post on the next scheduled digest window. NEXT: wire confluence into !all.**

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

## 26. Catch Wolf's hedged direction changes + retire stale calls

**File:** `wolf-hedged-stance-and-stale-theses.md`

When Wolf softly changes his mind on a stock (e.g. IGV: bullish-to-target, then "now I'm looking to short") or an old call goes stale after the move already happened, the bot should update instead of keeping his old view — this session had to hand-fix a stale IGV "bull".

## 27. A/B the !all "tidy text" step, then turn it off

**File:** `sanitize-ab-then-flip-off.md`

You approved turning off the AI "tidy text" pass on `!all` (saves ~9 AI calls per command) once an A/B check confirms the free models don't start inventing numbers without it — held this session because the providers were flaky; sanitize is still ON.

## 28. Evaluate the SMART LEVELS shadow soak, then decide go-live

**File:** `smart-levels-shadow-evaluate.md`

The new chart-based buy/stop/target engine for `!all` is running in shadow (logs only, no visible change) — after a day, compare its numbers to the current ones and decide whether to switch it on for real.
