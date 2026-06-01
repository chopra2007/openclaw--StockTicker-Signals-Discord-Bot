# Wolf newsletter → trade-finding macro brain

**Status:** IN PROGRESS — phase-1 (Type-1 over-time conviction tracker) **LIVE in #news 2026-06-01**; phase-2 (Type-2 cross-source confluence) **BUILT + tested + live-verified, flag OFF — pending sign-off to enable**.
**Created:** 2026-05-31

## Progress / what's shipped
- **Phase-1 / Type-1 (Wolf-over-time conviction tracker): SHIPPED + LIVE 2026-06-01** (user sign-off). Reader → per-thesis threads (scope+direction in `macro_theses`) → conviction tracker (stage progression + timeframe widening + position intent) → clean Discord **embed** alert to #news, firing ONLY on a material escalation. New `consensus_engine/analysis/wolf_conviction.py`; rides `evidence_log_json` (no DB schema change). Quality fixes from real-email replay on the May semis-short arc: acting⟺explicit-position gate, junk style-word scope filter, LLM-extraction retry, chart-image timeframes into the ladder, **inverse-ETF direction flip** (SOXS→SMH bear), embed format. Config flips: `wolf.dry_run:false`, `gmail_watcher.enabled:true`, added `api_keys.discord_news_channel_id`. Commits dd90348 → b817834. Detail: memory `project_wolf_phase1_live`.
- **Re-scope (user, 2026-05-31):** dropped the within-email "3-of-3 charts agree" idea (one email = one view). "Confluence" = (1) **Wolf-over-time [DONE]** and (2) **cross-source [NEXT]**.
- Known caveat at go-live: Gemini vision quota exhausted → alert LEVELS blank until ~midnight PT reset; text/story/timeframes/quote work.

## Phase-2 / Type-2 — BUILT 2026-06-01 (flag OFF, awaiting sign-off)
Cross-source confluence shipped via the `discover` run `wolf-confluence` (artifacts in `.claude/discover/wolf-confluence/`). Pure SQL+dict, **no LLM** — cheap/fast/stable. For each live Wolf thesis it checks whether YouTube / Twitter / options / SEC-buys agree within 21 days, rolled up by scope, each source casting ONE net vote: Wolf alone=surface, +1 source=high, +2=critical (@-ping). Disagreement → "analysts divided". Writes ONLY to a new `wolf_confluence_checks` table (one row/thesis, bounded) — cannot pollute `!all`/ticker alerts.
- New `consensus_engine/analysis/wolf_confluence.py`; new `wolf_confluence_loop` in main.py (runs on stop_event → overnight/weekend-safe); confluence field on every Wolf embed + a standalone louder alert on tier-up; reuses phase-1 outbox + @-ping.
- Gates passed: opus critic (B1 sector-map fix + 6 HIGH), Gemini cross-model (unbounded-growth BLOCKER → one-row-per-thesis), 1578/1578 tests green (baseline 0), independent reviewer = SHIP, LIVE-verified on real data (NVDA bull→critical w/ twitter+youtube; XLK/SMH/NDX roll-ups correct; OIL=surface; level-less capped; hysteresis holds).
- **TO ENABLE (after sign-off):** set `wolf.confluence.enabled: true` (+ optionally `wolf.enable_critical_ping: true`) in `config/consensus.yaml`, restart `consensus-engine.service`, tail logs for "wolf_confluence_loop: started".
- **Deferred follow-ups (tracked):** (1) Wolf-echo filter (drop a source row that merely re-quotes Wolf — planned §2b, not yet wired into the gather queries; low risk since Twitter rows carry no text and analysts rarely cite the newsletter). (2) per-Twitter-author vote granularity (currently Twitter = 1 net vote). (3) VIX/UVXY direction semantics (excluded in v1). (4) asset-class two-hop matching (XLE→OIL; excluded in v1, conservative). (5) minor: `_run_confluence_cycle` does one redundant upsert on a tier-up.

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
