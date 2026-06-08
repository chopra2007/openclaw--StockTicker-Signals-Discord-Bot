# Wolf/Gmail/YouTube/SEC follow-ups — EXECUTION plan (2026-06-08)

Source: `.claude/discover/full-audit-2026-06-06/SESSION-PLAN-2026-06-08.md`
Planning: workflow `wf_ac3d719f-909` (17 agents: design+adversarial-critique per item + synthesis).
User decisions captured 2026-06-08 (AskUserQuestion):
- Q1 Turn ON now: **all four** — Wolf SHORT, un-hide agreement board + YouTube links, named SEC insiders, 3 safe !all guards.
- Q2 IGV + fill: **Fix ON, then re-read backlog** (validate IGV→BEAR before posting).
- Q3 Tidy-text: **A/B 4 tickers, then sanitize OFF.**
- Q4 Hold set: **Hold big items + start SMART LEVELS shadow + move options room.**

## Critique-corrected scope (what actually gets built)
- **#1 IGV** — prompt-only fix behind `wolf.direction_guard.enabled` (flip ON). DROP the level cross-check (false-drops real bull theses, can't catch id=72). Key the prompt on FADE/peak/sell-the-bounce framing, NOT mechanical words ("fill the gap"/"back-test" appear in genuine bull text). Hysteresis DEFERRED (separate flag, not built this session).
- **#2 backfill** — internal. ONE code fix: add `"DELETE FROM wolf_beneficiaries"` to `_REBUILD_CLEAR` (backfill_wolf.py:48-55) so the id-renumber doesn't orphan 12 beneficiary rows. Run `--rebuild` AFTER #1 flag ON + #4 done, engine stopped, chown back to openclaw.
- **#3 confluence** — SPLIT. (A) un-hide level-less agreement: 1-line gate at wolf_digest.py:87 behind `wolf.confluence.board_show_levelless`. (B) YouTube links: thread `video_id` (raw id, like sample_tickers) through db SELECT → SourceVote → render URL in wolf_news, behind `wolf.confluence.links_enabled`. Do NOT build URLs inside the pure score_confluence. (C) Twitter links = design-only, NOT built. Preserve test tripwire test_wolf_confluence.py:201 ("YouTube (N ch" prefix).
- **#4 vision** — internal. Budget 30→80 (config). Migrate wolf_vision off direct-Gemini to OpenRouter via `models.openrouter_client.chat_completion` looping the VERIFIED chain `[nvidia/nemotron-nano-12b-v2-vl:free, google/gemma-4-31b-it:free]`. Keep SSRF guard + _parse_json + _validate. Remove orphaned Gemini helpers. **Gate #2 backfill on one REAL chart read through the new chain succeeding.**
- **#5 silent alarm** — internal. FOLD into existing `chain_health_loop` (health.py:341) using existing `health_check.daily_time_et`. NO second loop/config key. Two literal MAX queries (wolf_emails_processed.received_at, youtube_signals.extracted_at). Per-feed sticky state keyed by feed id. Ships with `health_check.enabled` (already true).
- **#6 audit** — no build. Flip approved flags (below). SHORT reality: only ~5 eligible bears (DJIA/RUT/SMH/NDX/SPX), picks render green/yellow dot (not red), up to ~60-min throttle delay before first short appears.
- **#7 YouTube resume** — internal. Migration tuples (NOT try/except) at db.py:799-810: `attempt_count INTEGER DEFAULT 0`, `last_attempt_at REAL`. has_video_been_processed returns False for 'failed' when attempt_count<cap (`youtube.max_retries`=5); 'missing' stays terminal. process_video bumps counter on 'failed'. New get_retryable_youtube_videos drains DB backlog oldest-first into youtube_scan_once. DROP: timezone fix, #5-heartbeat wiring, RSS widening, distinct budget-skip status. Verify commands.py:1439.
- **#8 SEC insiders** — user-visible (flip ON). Flag `sec_watcher.named_insiders_in_alert` (NOT features.* — avoids KNOWN_FEATURES edit). cross_reference.py `_run_sec_check`: flag OFF → byte-identical; ON → fetch fetch_form4_details per Form 4 (cap ~5), append named lines to sec_summary. Reuse ONE renderer (commands.py _sec_and_reply emoji style). Cap field <1024 chars. NOTE: enriched summary ALSO feeds LLM thesis prompt (cross_reference.py:418→llm_scorer.py:119) — verify thesis with flag ON.

## Dependency chain (hard)
#4 vision (deploy) → probe one REAL chart read → #1 flag ON → #2 backfill --rebuild → replay IGV history → confirm BEAR. #2 must NOT run before #4 (starves chart reads) or before #1 (re-bakes bull bug).

## Build waves (avoid shared-file races; agents forbidden from editing config/consensus.yaml — Claude owns all config)
- Wave A (parallel, disjoint files): #1, #4, #8.
- Wave B: #7 alone (heaviest db.py change).
- Wave C (parallel): #3, #5 (disjoint; #5 avoids db.py).
- Then Claude: all config flags + budget, deploy #4, real chart-read gate, flip #1, run #2 backfill, IGV replay, A/B sanitize, flip approved user-visible flags, SMART LEVELS shadow, options room, restart, full verification + regression gate.

## Config changes Claude will make (after code lands)
Internal deploy (no decision): wolf_vision_calls 30→80; wolf.vision.models chain; youtube.max_retries 5; #5 health feeds block.
Flip ON (user-approved): wolf.direction_guard.enabled; wolf.beneficiaries.shorts_enabled; wolf.confluence.board_show_levelless + links_enabled; sec_watcher.named_insiders_in_alert; all_command.market_cap_gate_enabled; all_command.sparse_banner.enabled; all_command.risk_price_gate_strict.
After A/B: all_command.sanitize_enabled → false.
Q4: all_command.levels.technical_engine_enabled true + technical_engine_shadow_mode true (shadow only); api_keys.options_flow_channel_id = 1512934341485924432.
HOLD (build/flag-OFF, not flipped): chart-pattern field, horizon_realized_vol, synthesis_prompt_trim, youtube_score.*, per_number_ticker_tagging, options selection_mode, wolf.direction_guard.hysteresis.

## Verify against REAL output (not just tests)
Real !all (guards + sanitize-off), real #news (Wolf SHORT, agreement board, IGV bear), real #chat SEC named insiders, YouTube backlog drains in DB, services active, symlink intact, no drift alert, full pytest vs `.test-baseline` (currently empty).
