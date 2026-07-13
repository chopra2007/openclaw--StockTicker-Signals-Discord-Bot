# Wolf newsletter → trade-finding macro brain

**Status:** phase-1 + phase-2 + phase-3 + **phase-4 ALL LIVE in #news** (phase-4 went live 2026-06-02, user "go fully live"). Phase-4 = beneficiary inference (#2) + fixes #3/#4/#5. Confluence-into-!all: DONE+LIVE (flag wolf_confluence_field_enabled: true config:614, chain aggregator.py:188, 8 tests pass, live-verified — see line ~170). Phase-3/4 RS follow-ups (1-month RS horizon `rs_window_days:21`, large-RS anti-chase guard `extended_pct:45`/`extended_penalty:0.7`): CONFIRMED SHIPPED 2026-06-02 (commit 98e0de9, `wolf_beneficiaries.py:267,312-317,355,401-405`, 2 tests) — NOT outstanding (audit 2026-07-03). Shorts side is LIVE too (10 short rows today), so any "shorts deferred to v1.1" note is stale. Item kept OPEN (user 2026-07-03) only for one unscoped idea: WIDEN the confluence/flow inputs (today just 2 signals feed confluence — news catalyst + options-flow direction); needs a definition of "wider" before it's buildable. Asset-direction convention: DONE (verified 2026-06-05; RE-VERIFIED accurate 2026-06-06 Wave 8 — macro_universe.yaml has `reviewed_at: "2026-06-02"`, the header comments state the convention explicitly (OIL bull = oil rising; YIELDS bull = yields rising; DXY bull = dollar strengthening), and the BONDS block is an explicit inverse alias of YIELDS — claim stands).
**Created:** 2026-05-31

**CURRENT STATUS (2026-07-12):** All named phases live. New since 07-12 (commit `7edf7a4`): the "widen confluence inputs" idea is now CLOSED — roster widened from 2 to 7 sources across 5 independence buckets (twitter, youtube, options, insider, macro), so correlated sources (e.g. options-flow + the Schwab order book) can't double-vote. Built on top of that: a confluence TIMING gate ("act only when 2+ independent source families agree, one of them fast-moving") — BUILT and logging verdicts in shadow (`timing.collect` on, `timing.enabled` off — an "act" verdict cannot raise an alert tier yet). Its backtest was inconclusive (only 6 paired samples vs the pre-registered n≥10 bar); the decision is re-taken when paired n≥10 accrues. No open idea remains — only the data-accrual wait on `timing.enabled`.

**➡️ 2026-07-11: user reframed #20 — confluence is a TIMING tool (Wolf is right but early). Build from "User direction — 2026-07-11" at the bottom of this file: inventory ALL available bot data, score confluence to pinpoint when Wolf's call is actionable. That's the design goal a fresh session should plan from.**

## Phase-4 — beneficiary inference (#2) + fixes #3/#4/#5 — LIVE, 2026-06-02
Built via `discover` run `wolf-phase4` (artifacts `.claude/discover/wolf-phase4/`). Regression gate CLEAN (1686 pass, 0 regressions).
- **#2 beneficiary inference (headline, commit 94ec4f7):** precompute loop infers ranked beneficiary LONGs per active macro/sector thesis → NEW `wolf_beneficiaries` table (schema **v18**) → digest reads it → renders a clearly-labeled "🤖 Bot's read — inferred, not Wolf's picks" section. Ranking = peer-relative **1-month** RS (user choice) with an absolute outperformance floor (no manufactured winners); catalyst (direction-aligned) + options flow (premium dominance) lift confidence; confluence = thesis-level multiplier; pure-RS caps 🟡, 🟢 needs ≥2 signals. Longs-only v1. Universe: curated `consensus_engine/data/macro_universe.yaml` (macro/index/asset) or derived from `peer_groups.yaml` (sector bull-only). New: `consensus_engine/analysis/wolf_beneficiaries.py`, `main.wolf_beneficiary_loop` (independent sibling, self-gated), `db.get/replace_beneficiaries`. **Codex cross-model gate PASSED** (folded: no sign-flip, abs floor, aligned catalyst, premium flow, ETF-mode penalty); Gemini unavailable. **Two flags default OFF** (`wolf.beneficiaries.enabled`=precompute, `surface_in_digest`=post; OFF window = shadow-run). Live shadow render verified vs 38 seeded theses (YIELDS bull→GS, OIL bull→CVX/XOM, IGV bull→SNOW/DDOG/TEAM); real-test caught+fixed a sector-bear direction bug. **WENT LIVE 2026-06-02 (commit e6487db, user "go fully live", skipped shadow-run):** both flags true, engine restarted + verified (loop started, 9 picks/5 theses precomputed, live render confirms the section). First real #news post on the next scheduled digest window.
- **#5 (4217c73):** Gmail allowlist split `allowed_emails`+`allowed_domains` (backward-compat) + fixed `backfill_wolf._wolf_sender` positional `[0]` trap.
- **#4 (35487fc):** scope aliases nas100→NDX / sp-500→SPX / transports→TRANSPORTS (+ TRANSPORTS in `_MARKET_IDS`); one-off live remap (`scripts/wolf_phase4_remap.py`) re-scoped id22/id40, superseded duplicate id61. Resolves phase-3 follow-up (4)'s deeper parser-scoping item.
- **#3 (9fb9672):** thesis-alert send-retry on `wolf_news.post_event` mirrors the digest retry (skip only if status=='posted'). Resolves phase-3 follow-up (4)'s retry item.
- Side fix (33acc78): made a pre-existing flaky Brave body-enrichment test hermetic (it depended on the live Brave daily-counter file; surfaced by the gate, not a phase-4 regression).
- **Phase-4 follow-ups (tracked):** large RS deltas verified REAL (MU +96% in 21d on the melt-up tape) → **anti-chase guard added (commit 98e0de9, LIVE):** names up ≥45% over the window are dampened, capped 🟡, flagged "⚠ extended — chase risk" (SNOW/DDOG flagged; GS/CVX stay 🟢). Remaining: rs_window stays 1-month (user choice; 63d was research rec); shorts side deferred to v1.1; widen confluence/flow inputs later. ~~confirm macro_universe asset-direction convention (bull=up) vs newsletter wording~~ — DONE 2026-06-05 (macro_universe.yaml reviewed_at 2026-06-02; BONDS/YIELDS inverse alias explicit in file comments). (98e0de9 unpushed — atop concurrent !all commits — pushes at next close.)

## Phase-3 — Gmail backfill + digest scheduler — BUILT (not yet live), 2026-06-01
Built via `discover` run `wolf-phase3-digests` (artifacts in `.claude/discover/wolf-phase3-digests/`; full execution
log at `pass-5-execution-log.md`). Two pieces:
- **Build 1 — backfill** (`scripts/backfill_wolf.py`): re-reads Wolf's All-Mail oldest→newest through the live reader
  (internalDate as the clock, NO #news posting) to seed `macro_theses` with history. Schema **v17**:
  `wolf_emails_processed.received_at` + new `wolf_call_outcomes` table. `wolf_theses.ingest(source_id=)` is now
  idempotent per source email (crash-safe resume). Empty-state precondition + `--rebuild`.
- **Build 2 — digests** (`wolf_digest.py` + `wolf_outcomes.py`): `wolf_digest_loop` (run_all, stop_event, crash-isolated,
  gated by `wolf.digests.enabled` = OFF) posts midday / nightly / Sunday-recap briefings to #news from existing data
  (theses+stage, confluence scoreboard, Wolf's market lean, and — Sunday — how his actionable calls moved). Triggers
  key off `received_at` (backfill can't fire a digest). Outcomes are humble (never "nailed it").
- **Tests:** 22 new (`tests/test_wolf_backfill.py` 8, `tests/test_wolf_digest.py` 14); full wolf surface 152 green.
- **Backfill DONE (user sign-off 2026-06-01):** ran as openclaw, engine stopped → 79 emails → **72 theses (38 active)**,
  verified (0 dup-src, no leakage, evidence sorted), engine restarted healthy. Live history now seeded.
- **GO-LIVE DONE (user sign-off 2026-06-01, commit 14ae843):** `wolf.digests.enabled:true`, `wolf_digest_loop: armed`.
  Real end-to-end #news post verified (discord_msg_id 1511181708765171743); outcome scorer verified on real data
  (25 scored). First scheduled digest fires on the next Wolf email in a PT window. **Phase-3 fully LIVE.**
- **Phase-3 follow-ups (tracked):** (1) Wolf vision BudgetManager bypass (live, ~9 calls/day) → dedicated
  `wolf_vision` budget bucket. (2) **Beneficiary inference (phase-4)** — digest "beneficiaries" omitted until then.
  (3) Option to phase nightly-only first (Codex SIMPLIFY) — shipped all 3 instead, flags OFF.
  (4) The LIVE phase-1/2 thesis-alert path (`wolf_news.post_event`) also never retries a failed Discord send (only the
  phase-3 digest path got the retry fix). Lower severity there — the next material escalation re-posts under a new
  dedupe key — but worth adding the same retry-on-non-posted-row logic to the shared path eventually.
  (5) DONE (commit 2150659): NAS100→QQQ, TRANSPORTS→IYT in wolf_scope._SCOPE_PROXY (checked regardless of scope_type);
  verified on real data (NAS100 +10.2% with, TRANSPORTS −5.0% against; 0 inconclusive). [Deeper parser-scoping fix
  — canonicalize NAS100 to NDX(market) in resolve_scope so the THESIS thread is correct, not just the outcome proxy —
  still open, touches the live reader.]
  (6) DONE (commit 2150659): format_digest caps each bucket at max_theses_per_field + appends "…and N more". Verified.

## Progress / what's shipped
- **Phase-1 / Type-1 (Wolf-over-time conviction tracker): SHIPPED + LIVE 2026-06-01** (user sign-off). Reader → per-thesis threads (scope+direction in `macro_theses`) → conviction tracker (stage progression + timeframe widening + position intent) → clean Discord **embed** alert to #news, firing ONLY on a material escalation. New `consensus_engine/analysis/wolf_conviction.py`; rides `evidence_log_json` (no DB schema change). Quality fixes from real-email replay on the May semis-short arc: acting⟺explicit-position gate, junk style-word scope filter, LLM-extraction retry, chart-image timeframes into the ladder, **inverse-ETF direction flip** (SOXS→SMH bear), embed format. Config flips: `wolf.dry_run:false`, `gmail_watcher.enabled:true`, added `api_keys.discord_news_channel_id`. Commits dd90348 → b817834. Detail: memory `project_wolf_phase1_live`.
- **Re-scope (user, 2026-05-31):** dropped the within-email "3-of-3 charts agree" idea (one email = one view). "Confluence" = (1) **Wolf-over-time [DONE]** and (2) **cross-source [NEXT]**.
- Known caveat at go-live: Gemini vision quota exhausted → alert LEVELS blank until ~midnight PT reset; text/story/timeframes/quote work.

## Phase-2 / Type-2 — SHIPPED + LIVE 2026-06-01 (enabled, critical @-ping ON)
Cross-source confluence shipped via the `discover` run `wolf-confluence` (artifacts in `.claude/discover/wolf-confluence/`). Pure SQL+dict, **no LLM** — cheap/fast/stable. For each live Wolf thesis it checks whether YouTube / Twitter / options / SEC-buys agree within 21 days, rolled up by scope, each source casting ONE net vote: Wolf alone=surface, +1 source=high, +2=critical (@-ping). Disagreement → "analysts divided". Writes ONLY to a new `wolf_confluence_checks` table (one row/thesis, bounded) — cannot pollute `!all`/ticker alerts.
- New `consensus_engine/analysis/wolf_confluence.py`; new `wolf_confluence_loop` in main.py (runs on stop_event → overnight/weekend-safe); confluence field on every Wolf embed + a standalone louder alert on tier-up; reuses phase-1 outbox + @-ping.
- Gates passed: opus critic (B1 sector-map fix + 6 HIGH), Gemini cross-model (unbounded-growth BLOCKER → one-row-per-thesis), 1578/1578 tests green (baseline 0), independent reviewer = SHIP, LIVE-verified on real data (NVDA bull→critical w/ twitter+youtube; XLK/SMH/NDX roll-ups correct; OIL=surface; level-less capped; hysteresis holds).
- **ENABLED 2026-06-01** (user sign-off): `wolf.confluence.enabled: true` + `wolf.enable_critical_ping: true` in `config/consensus.yaml`; engine restarted; `wolf_confluence_loop: started` verified; schema 16 + `wolf_confluence_checks` table live; pushed to origin/master. **CAVEAT — not yet proven on a REAL Wolf-email thesis** (0 active theses at enable time; verified only against real source data + a seeded thesis). Watch the next Wrap (~12:10am PT) for the first real confluence alert.
- **Deferred follow-ups (tracked):** (1) **Wolf-echo filter — WONTFIX (2026-06-06, Wave 8 #32).** The idea was to drop a source row that merely re-quotes Wolf so an echo doesn't fake confluence. CORRECTED rationale: real echoes are **~0** because the newsletter is **paid/private** — analysts on Twitter/YouTube don't cite "Wolf on Wall Street", they cite their own work. The earlier worry pointed at ~135 `%wolf%` Twitter hits, but those are **$WOLF / Wolfspeed** ticker noise, not newsletter echoes (verified: the hits are options-volume scanner tweets listing `$WOLF` alongside other tickers — none reference the newsletter). With no real echoes, a filter would only add cost + a false-drop risk → closed. **Probe table CORRECTION:** the tweet body lives in **`ticker_signals`** (has `raw_text`, 2982 twitter rows, all with text; 135 `lower(raw_text) LIKE '%wolf%'`), NOT `signal_events` (which has NO `raw_text` column). Read-only verification done via `sqlite3 -readonly consensus.db`. (2) **per-Twitter-author vote granularity — DECISION: KEEP one-net-vote (2026-06-06, Wave 8 #33).** Twitter casts ONE net vote per confluence check by design (anti-crowding). Switching to per-author would let a single chatty account tip a thesis: e.g. **MarketRebels has ~299 tweets in 21 days** (verified, top of 30 distinct authors) — under per-author voting that one account could push a thesis to the critical / @-ping tier on its own, exactly the crowding the one-net-vote design prevents. So per-author voting is rejected; at most use a **distinct-author count as a display hint** ("N accounts" in the embed), never as extra votes. (3) VIX/UVXY direction semantics (excluded in v1). (4) asset-class two-hop matching (XLE→OIL; excluded in v1, conservative). (5) minor: `_run_confluence_cycle` does one redundant upsert on a tier-up.

## (superseded) NEXT — Phase-2: cross-source confluence (Type-2)
Compare Wolf's thesis vs OTHER sources the user follows — **YouTube + TweetShift/Twitter — WITH sector roll-up** (e.g. a YouTube "bearish semis/nasdaq" + a TweetShift "big bearish NVDA & MU" → both semis → reinforce Wolf's SMH short). Higher-risk: reads several LIVE tables and touches the live `!all` data.
**Agreed process (2026-05-31):** write a dedicated confluence plan → run the **Codex (gpt-5.5) adversarial review gate** on it → then build (TDD + verify). The plan supersedes the thin phase-2 sketch in the discover `final-plan.md` (known BLOCKER there: must read THREE source tables — `signal_events` twitter/youtube, `options_flow` side→dir, `ticker_signals[sec]` sentiment→dir — NOT just signal_events; plus scope matrix, Wolf-echo filter, YT cluster-cap, recency decay, non-Wolf level-bearing requirement for high/critical).
**HARD PRECONDITION:** verify Codex can actually READ the plan + code files (a cheap access probe) BEFORE dispatching the review — it once fell back to a stale GitHub copy on perm-denied; don't burn credits on a blind review (memory `feedback_verify_codex_file_access`). Detailed direction also saved at `.claude/discover/wolf-news-brain/pass5-confluence-direction.md`.

## North-star goal
Find **actionable trades.** Turn the "Wolf on Wall Street" email feed into a market-context "brain" that surfaces trade leans, sector rotations, and catalysts — and **proactively pings** when a market/sector top or bottom is forming or a catalyst lands, **louder when other sources agree.** "Being more informed" is the means, not the end.

## Operating principles (user directive, 2026-05-31) — read first
1. **Verify, don't assume.** No assumptions — confirm with **live, real-world tests** that things actually work in real scenarios (real Wolf emails, real chart images, real posts to a test channel). And when something looks blocked, **assume you CAN do it** and work from there: diagnose → fix → find an alternative path (CLAUDE.md real-world-testing ladder) before ever concluding it's impossible.
2. **Found a better way → take it.** If a cleaner/better approach to any piece emerges mid-build, use it. The mechanics suggested below are a *floor, not a ceiling* — don't stay locked to them.
3. **Thought of a new improvement → build it.** If you think of new ways to make the feature better, add them.

(These encourage autonomy on *how* to build. They do NOT remove the stop gates — still get sign-off before any LIVE Discord post or before enabling the watcher in production, and still surface genuine ambiguity.)

## What's already DONE (the connection)
- Gmail connected: **teche2014@gmail.com** OAuth complete, token auto-refreshing (verified), scope `gmail.modify`. Headless connect helper: `/root/.openclaw/gmail/oauth_connect.py`. Proven reading the inbox live.
- `config/consensus.yaml` `gmail_watcher` block wired: `token_path`, `credentials_path`, `sender_allowlist: [support@wolf-on-wallstreet.com]` — but **`enabled: false` on purpose** (committed on master).
- Sole inbox source = the Wolf newsletter (`support@wolf-on-wallstreet.com`), ~5–10 emails/day, some 40+ charts.

## Why the CURRENT watcher is inadequate (must rebuild, not tweak)
`consensus_engine/scanners/gmail_watcher.py` only decodes `text/plain` bodies + runs `extract_tickers` (regex). The Wolf emails:
- Are **HTML-only** (no `text/plain` part) → current decoder returns empty → extracts nothing.
- Carry the real signal in **remote chart images** (`wolfonwallstreet-trade.com/wp-content/uploads/...jpg`) + a SendGrid tracking pixel to skip; occasionally a news/social screenshot. Current watcher ignores images entirely.
- Are macro/commentary, not ticker lists — and `extract_tickers` blacklists exactly what matters (SPY/QQQ/VOO/DOW/FED/CPI…).
→ Needs a new reader: **HTML text + vision image-reading + LLM structured extraction.**

## FULL REQUIREMENTS (interview, 2026-05-31)

### Trade output style
- Output unit: **directional lean + key level**, **watchlist of candidates**, **sector-rotation calls**. NOT exact entry/stop/target.
- Timeframe: mostly **swing→position (1 week–months)** + long-lead top/bottom calls. Tag the timeframe per idea.
- Instruments: **stocks, ETFs, options, futures** (all). Options/gamma angle matters.

### Stateful thesis tracking (CORE)
- A top/bottom call evolves over weeks–months as **stages**: "a top is forming" (months out) → "negative divergences building" (weeks out) → "imminent top, I've started a short in the Nasdaq" (acting). Track each major thesis and its **current stage**; detect stage changes. **Wolf revealing an actual position = highest-signal stage.**
- A call stays **ACTIVE until invalidated** (price breaks the key level the wrong way, or Wolf drops it).

### Proactive alerts → new #news channel
- Ping at **every stage**: first warning, evidence building, imminent/acting, AND **key level breaks**.
- **Critical** tier @-mentions the user; send **ANYTIME incl. overnight** (Wraps land ~12:10–12:40am PT). No quiet hours.

### Confluence (the big lever)
- Match Wolf's calls against: **14 YouTube channels** (esp. technical/top-bottom callers), **options flow** (yfinance + CheddarFlow), **Twitter/TweetShift**, **SEC** (Form 4/insider). Each source needs a derived directional "stance."
- Match at **all levels**: whole-market top/bottom, sector/group, individual stocks, asset classes (oil/gold/bonds/yields/BTC/dollar).
- **Tiers:** Wolf alone = surface; **Wolf + 1 other = high-conviction**; **Wolf + 2+ = critical.**
- Do **BOTH**: a conviction tag on every call ("N others agree") AND a dedicated louder alert when sources line up.
- "Agreement" only counts other analysts' calls from the **last ~2–3 weeks**.
- **Disagreement is itself a signal** — surface "analysts divided — Wolf top vs N bullish."
- All sources **weighted equally** for now (no accuracy-based weighting yet).

### Catalysts & beneficiaries
- Catalysts: **only what Wolf mentions** (no independent calendar/news scanning). Map them to sectors/names.
- Beneficiary inference: **YES, but only for BIG catalysts** (war escalation, Fed surprise) — infer up/down names (oil spike → up: XLE/OIH/HAL/SLB; at risk: airlines, cruise). Always mark as the bot's inference, not Wolf's.

### History / backfill
- Read **everything available** in Gmail (All Mail, not just inbox / not just new) to reconstruct the current state of his months-long theses. (Inbox held ~74; All Mail likely has more/older.)

### Digests (all Pacific time)
- **Midday:** event-triggered (~1 min) after his ~12:00–1:05pm PT afternoon email (the one that sometimes reveals trades he's started).
- **Nightly:** event-triggered after his **Wrap** (the long/40+-chart comprehensive evening email). Trigger window **7pm–2am PT** — Wraps land just after midnight PT; do NOT cut off at 11:59pm.
- **Sunday:** ~10am PT weekly recap (clock-based).
- **Sunday post-10am email** → short **add-on update** appended to that Sunday digest.
- **Quiet day** (no email) → no digest, no "nothing to report" note.
- **Weekly recap tracks what actually played out** → log call outcomes (track outcomes; weight equally).
- Digest content: regime (top/bottom-prone) + active theses & their stage + watchlist + confluence scoreboard + beneficiaries.

### Personalization & integration
- **Keep general** — no user positions/watchlist.
- **Phased:** build the new proactive **#news lane FIRST**; wire into `!all` + existing ticker alerts in a **later** phase.

## What Wolf's emails contain (extraction targets)
- Breadth + **3C divergences** (his proprietary price-vs-strength money-flow indicator; charts hand-labeled "divergence"/"confirming").
- Candle patterns + exact levels (SPX 7500→7340, NDX 29679/30000, DJIA 50000, IWM 286.50–287.50, SOX 12548/12616/12710).
- Sector rotation (Tech / Semis SOX / Software IGV vs Energy/defensives).
- Intermarket (WTI, 2/10/30y yields, Dollar, gold, BTC, VIX; "war correlation" = stocks inverse to oil & yields).
- Geopolitics (Iran/Hormuz; "Barak Ravid"/Axios headline-timing pattern), Fed speakers, econ data (PCE/GDP/jobless).
- Named stocks on earnings (DELL/HOOD/BBY/DLTR/KSS/NVDA/COST/MU).
- **Charts carry the real signal** (levels + divergence labels) → vision image reading is essential.

## Possible next steps (priority-ordered)
1. **Reader rebuild** — HTML text extraction (replace text/plain-only `_decode_body`); fetch remote chart images (skip the SendGrid pixel) and read via vision model (Gemini flash, like the video-frame path); LLM structured extraction → JSON (thesis, regime/stage, index/sector/asset views + levels, named stocks, catalysts, 3C status). Keep the regex symbol scan.
2. **Stateful store** — a "market read" + per-thesis state (stage, key levels, active/invalidated) that updates per email and persists across restarts.
3. **Confluence engine** — derive a stance per source (YouTube/options/Twitter/SEC), match against Wolf at all levels within a ~2–3wk window; tiered conviction; disagreement detection.
4. **Proactive alerting** — create the #news channel; post stage-change + level-break + confluence alerts; @-ping on critical (anytime).
5. **Digest scheduler** — event-triggered midday/nightly (Wrap window 7pm–2am PT) + clock Sunday 10am + Sunday add-on; content above; weekly recap with outcome tracking.
6. **Beneficiary inference** for big catalysts.
7. **Backfill** — ingest full Gmail history to seed state.
8. **Phase 2** — integrate into `!all` + existing alerts.

## Files / code involved
- `consensus_engine/scanners/gmail_watcher.py` (rebuild)
- `consensus_engine/main.py` (watcher task wiring, ~line 676)
- `config/consensus.yaml` (`gmail_watcher` block, ~line 673)
- `consensus_engine/utils/tickers.py` (`extract_tickers` — keep + supplement)
- `consensus_engine/llm_client.py` (extraction); Gemini vision (see memory `reference_gemini_video_models`)
- YouTube pipeline + `/root/.openclaw/sources.json` (14 channels), options-flow watcher (yfinance), TweetShift, SEC watcher — confluence sources
- `consensus.db` (already has `seen_gmail_messages`/`seen_gmail_bodies`; add tables for theses / market-read / calls)
- Discord: new **#news** channel + posting path
- Token: `/root/.openclaw/gmail/token.json`; helper `/root/.openclaw/gmail/oauth_connect.py`

## Open questions (build-side; decide during build)
- LLM/vision **cost**: ~100 charts/day possible; Gemini free-tier per-key/day limits — may need batching/caps or a paid key. (Images are far cheaper than video.)
- How to reliably identify "the Wrap" vs intraday notes (size / chart-count / subject heuristic).
- How to derive a comparable **stance** from each confluence source — does the existing YouTube pipeline already emit a directional stance, or does that need adding?
- Exact scope of "all available history" in Gmail (All Mail depth).
- Align watcher `SCOPES` to `gmail.modify` on rebuild (current list is readonly+labels; labeling needs modify).

## Anything else
- Connection + direction also in memory: `project_gmail_wolf_connected.md`, `project_wolf_macro_brain_direction.md`.
- Sample emails + ~100 charts saved at `/tmp/wolf_charts/` during research (ephemeral; re-pull via the token if needed).
- Kickoff for a fresh session: `todo/kickoffs/wolf-macro-brain.md`.

### Session notes — 2026-06-13 (discover run todo-sweep) — #20 health + live thesis-quality bugs
- Pipeline ALL GREEN (112 emails parsed 0 errors; macro_theses/confluence/beneficiary/digest loops all firing). The TODO header's "NEXT" items are actually SHIPPED+LIVE: confluence-in-!all (flag true, aggregator.py:188) and shorts-side beneficiaries (flag true, 9 short rows). 63d-RS is a closed decision (stays 21d). #20 = done-soak on features.
- **BUT 3 live thesis-quality bugs found** (these surface to users via digest/confluence/beneficiaries): (1) SPX(143)+NDX(144) stored BULL but Wolf wrote bearish ("bounce to a lower high, forming an H&S top") — direction-guard carve-out over-fires; fix = the "lower-high/H&S=bear" clause (verifier tested 5/5 clean). (2) Stale IGV bull (id 140) persists as confluence-critical + drives 3 LONG beneficiary ideas though Wolf abandoned it — needs the #26 staleness sweep. (3) Orphan wolf_beneficiaries rows for invalidated theses 114/126 (clear on invalidate). All tracked under #26's plan. Full notes: .claude/discover/todo-sweep-2026-06-13/research/wolf.md.

### Session notes — 2026-06-21 (discover run todo-20-46) — #20 goal verified ACHIEVED + live
- **Goal confirmed achieved and LIVE** (independent re-verification, did not trust the file): all 4 phases real, not just claimed. consensus-engine active (PID checked); wolf_confluence_loop + wolf_beneficiary_loop FIRING (confluence rows written 2026-06-21 05:52 UTC for active bear theses NDX/SPX, direction-correct; beneficiary loop every ~30 min producing BOTH longs and shorts — e.g. UAL/AAL long, XOM/DVN/COIN/MSFT short). Confluence-into-!all wired (aggregator.py:188 → embed.py:845). All wolf.* flags true.
- **Named "remaining" follow-ups all DONE**: anti-chase guard (extended_pct=45/penalty=0.7, live), shorts-side beneficiaries (shorts_enabled=true, live short rows), confluence-into-!all field. The 1-month (21d) RS horizon is a CLOSED user decision. The 3 thesis-quality bugs from the 2026-06-13 note belong to #26 (not #20) and are cleared in live data.
- **Gmail data-pipe scare resolved (load-bearing for the north-star).** Found zero Wolf emails ingested since 2026-06-18 19:57. Did a POSITIVE liveness probe (ran as openclaw to preserve token ownership): refresh token still valid → refreshed cleanly, Gmail API returned 201 Wolf emails, newest 2026-06-18 12:57 PDT. **The 3-day silence is benign: Fri 2026-06-19 was Juneteenth (NYSE/NASDAQ closed) → no trading-day email, then the weekend.** Token ownership stayed openclaw:openclaw (no ownership-trap). Next Wolf email lands when markets reopen Mon 2026-06-22; watcher will ingest it.
- **Residual risk (separate, tracked):** the recurring ~7-day Gmail OAuth refresh-token death (Testing-mode app). Alive now (refreshed 2026-06-21 07:03 UTC). Permanent fix needs the user to move the OAuth app to Production / add a service account — outside #20's build scope. Not a regression introduced by any work; the feed is healthy today.

### Session notes — 2026-06-24 (discover run todo-sweep-2026-06-24) — goal RE-VERIFIED + Gmail token watchdog SHIPPED
- **Goal re-verified LIVE (did not trust the file):** all 4 phases live; Wolf email ingested **today** 2026-06-24 13:05 UTC (wolf_emails_processed MAX received_at; 137 rows); macro_theses 73 total/16 active; wolf_confluence/beneficiary/digest loops all wired (main.py:1016-1023) and firing; gmail_watcher.enabled + all wolf.* flags ON; both services active. The north-star (proactive trade-finding brain) is achieved and running.
- **BUILT + verified: Gmail token watchdog** — `/root/task_system/scripts/gmail_token_watchdog.sh` + systemd `gmail-token-watchdog.{service,timer}` (every 6h, mirrors wolf-confluence-dark-watch). It proactively refreshes the token AS openclaw (ownership stays openclaw:openclaw 600), catches `google.auth.exceptions.RefreshError`, and on `invalid_grant`/expired writes a LOUD alert to notifications.log + best-effort #news with the exact copy-paste re-auth two-step (`oauth_connect.py url` → approve → `exchange "<url>"`). Idempotent (state file: alert once on healthy→dead, daily reminder while dead, reset on recovery), 5-day age tripwire, 3x retry guard so a transient network error can't fake a DEAD alarm. This is proactive keep-warm + specific invalid_grant classification — it does NOT duplicate the two existing reactive detectors (health.py 24h freshness; dark-watch 6h confluence-blank).
- **Bug found+fixed during live verification:** the #news DEAD-post `python3 -c` interpolated the raw exception repr (which contains single quotes) into a python string literal → **SyntaxError in production** (the loud Discord alert would have silently failed; only notifications.log survived). Fixed: clean error string (`e.args[0]` → "invalid_grant: Bad Request") + pass the message via an env var into a single-quoted `python -c` reading `os.environ` (special chars can't break the literal). Re-tested end-to-end against the real Google token endpoint with a BOGUS-refresh-token fixture (no real secret, #news neutered): detection→DEAD exit2, alert written with correct re-auth, idempotent suppression on 2nd same-day run, real token.json untouched. Live HEALTHY run of the installed service confirmed (token refreshed, ownership preserved).
- **CORRECTION — the "recurring 7-day Testing-mode death" is STALE; the permanent fix was already applied 2026-06-07.** Verified against the journal (back to Mar 27): the LAST `invalid_grant`/"expired or revoked" death was **2026-06-07 23:13** — the death that triggered the Production publish that same day (memory [[reference-gmail-token-7day-expiry]]: app `akashbot-495306` moved Testing→In-production). **ZERO auth deaths in the 17 days since**; the only recent gmail errors are transient SSL blips (Jun 19/23 `EOF in violation of protocol`), and a Wolf email was ingested 2026-06-24 18:33. A 7-day Testing clock could not survive 17 days — so the app IS in Production and the weekly death is resolved. The 2026-06-21 "Testing-mode app / permanent fix needs Production" note carried stale pre-06-07 framing forward.
- **So the watchdog is defense-in-depth, NOT a stopgap for an unfixed clock.** Production stops the 7-day clock but tokens can still die from: 6-month non-use, a Gmail password reset (revokes gmail-scoped tokens), manual revoke, or Google tightening restricted-scope (gmail.modify) policy. The watchdog catches those loudly+early instead of a silent outage. **No user console action is needed right now** — `gmail-production-fix.md` is kept only as the re-publish recipe IF the status is ever found back in Testing (worth a periodic glance at console.cloud.google.com → APIs & Services → OAuth consent screen → should read "In production").

### Session note — 2026-06-29 (run `todo-55-47-research`) — re-verified live; Wolf market read now surfaced in !market
- **Re-verified LIVE + healthy** (did not trust the file): confluence/beneficiary/digest loops all wired + flags ON, gmail watcher ON; 78 macro_theses (18 active), 18 confluence rows, 16 beneficiary rows, newest Wolf email recent. Done-soak holds; nothing to build for #20.
- **NEW cross-link (#47):** the `!market` dashboard now LEADS with Wolf's **market-level** theses + cross-source confluence (built commit c2210ff, deploy pending). So Wolf's top/bottom calls (currently NDX/SPX top-forming, analysts divided) are now visible on-demand in `!market`, not only pushed to #news. Pure read of `macro_theses`/`wolf_confluence_checks`; no change to the Wolf pipeline itself.

### User direction — 2026-07-11 (how to think about confluence + timing — plan from this)

The user reframed what #20's "widen confluence" is really for. A new session should design from this, not just add one more input.

**The real problem:** Wolf is **often right, but frequently early** — sometimes days, sometimes months ahead of the move. Being right but early is still a losing trade if you act on his timing alone.

**What confluence is for:** confluence (other signals agreeing with Wolf) can **pinpoint the timing** — it tells us *when* Wolf's call is finally lining up with what the rest of the market/data is showing, so we flag it when it's actionable, not when Wolf first says it.

**The task for the planning session:**
- Look at **all** the data the bot already has access to — **not just the already-built features** (news catalysts + options-flow direction, the current two inputs). Inventory everything available: options data (Schwab real-time), insider/Form-4, social/retail sentiment, analyst swarm, technicals/levels, breadth/macro legs, YouTube mentions, etc.
- **Decide a smart way to track and score confluence** as a *timing* signal — i.e. score how many independent data sources are now agreeing with a standing Wolf thesis, and surface the thesis louder only when that agreement crosses a threshold (the "party has arrived" moment), rather than when Wolf is still early and alone.

**Design questions to resolve in the plan:**
- Which of the available signals are genuinely *independent* of each other (don't double-count StockTwits+Reddit as two votes — see #65).
- How to weight fast vs slow signals for a *timing* read.
- What threshold flips a standing-but-early Wolf thesis into an actionable louder alert.
- How to measure whether confluence-gated timing actually beats acting on Wolf's raw call (needs the 5d/20d outcome grading from #55 to backtest).

### Session notes — 2026-07-12 (#20 confluence WIDENED + timing gate, commit 7edf7a4)

This closes the one thing the item was being kept open for — "widen the confluence inputs,
needs a definition of 'wider'". The definition landed: **independence buckets**.

- Roster widened from 4 sources to **7 sources across 5 independence buckets** (twitter, youtube,
  options, insider, macro). Each bucket casts **at most one net vote**, so options-flow + the Schwab
  chain snapshot (the same order book) can no longer corroborate each other. Same for SEC + form4.
- New `wolf_confluence.score_timing()`: says **"act"** only when 2+ independent families agree AND at
  least one is a **fast** mover (twitter/options). Slow-only agreement is a thesis, not a trade.
- Shipped **OFF**: `wolf.confluence.timing.collect: true` (compute + store), `timing.enabled: false`
  (an "act" verdict may NOT raise a tier). Live proof: thesis 174 (RUT) scored `act` and its tier
  stayed `surface`, `alerted_tier` unchanged.
- **Retail bucket dropped, deliberately:** `reddit_posts` has no ticker and no sentiment;
  `apewisdom_mentions` has a ticker but no direction. Attention is not a side — inventing one would
  manufacture the agreement this feature exists to detect.
- **Backtest (`scripts/wolf_timing_backtest.py`): INCONCLUSIVE.** 46 actionable theses, the gate would
  have fired on only 9 → paired n=6 (5d) / n=5 (20d), under the pre-registered n≥10 bar. NOT the
  honest-negative case (gated proven worse) — just underpowered.

**Owed before `timing.enabled` ever flips:** re-run the backtest when paired n≥10 (the shadow soak
accrues `timing_first_act_at` forward). It changes overnight @-ping behaviour, so a live shadow soak
is owed too. No threshold re-tuning to force a pass.
Full log: `.claude/discover/todo-55-20-plan/pass-5-execution-log.md`.

### Session notes — 2026-07-12 later (#20 side effect of the gap fixes)

`wolf_timing_backtest.py` now uses `resolve_benchmark_dynamic()` for thesis proxies (a
stock-scoped thesis on a long-tail name gets its real sector ETF instead of the SPY default).
No change to the timing gate itself; the paired-n≥10 re-run condition is unchanged.
