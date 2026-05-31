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

Continue improving what `!all <TICKER>` shows by picking one quality lever per session (max-pain, peer comp, options flow, etc.) from the documented menu. **2026-05-29:** options-flow lever shipped via #18 — recent autonomous-detected unusual flow now feeds the `!all` narrator (`get_options_flow_for_ticker` → structured-data summary). **2026-05-30 (run `all-levers-2026-05-29`):** shipped **max-pain** (weekly+monthly embed field) + **peer relative-strength** (5-day vs sub-industry peers, embed + narrator) + a new sub-industry **peer layer** (`data/peer_groups.yaml`, separate from the A4 gate map). Commits `53e3e35`+`7d77245`, live-verified. Stays OPEN — more levers remain in the menu (`all-command-quality.md`).

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

## 19. Research YouTube DB weighting in the score

**File:** `youtube_db_score_weighting.md`

Figure out whether YouTube database signals (video mentions, extracted levels) are currently weighted in the `!all` score, and whether they should be — then implement if the answer is yes.

## 20. Turn the Wolf market newsletter into a trade-finding brain

**File:** `wolf-macro-brain.md`

Read the Wolf on Wall Street emails (text + charts) so the bot tracks market tops/bottoms, sector rotations, and catalysts, and proactively flags actionable trades — louder when other sources agree.
