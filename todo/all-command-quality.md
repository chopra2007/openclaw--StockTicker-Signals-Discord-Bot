# Optimize `!all` output quality + feature surface (open-ended initiative)

**Status:** OPEN — initial acceptance bar MET 2026-05-19 (one shipped quality improvement); umbrella stays open as a menu for future sessions.
**Created:** 2026-05-16

> ### ✅ DONE 2026-05-19 — discover run `gemini-quality-all-command` (19 commits, 74292a6→1272317)
>
> The acceptance bar for this TODO ("shipped at least one user-visible quality improvement with before/after evidence") is **met** — the 2026-05-19 session shipped a full substance overhaul and the user confirmed `!all` output is now equal-or-better than Gemini on NVDA / AMD / TSLA. Completed levers:
> - **Trade-plan completeness** — anchor freshness cutoff + drawdown sanity gate + direction-aware ATR fallback; no more "—" SL/TP.
> - **Horizon coherence** — swing-horizon floor + horizon-aware SL drawdown gate; killed the "1-1 day horizon vs 20-day SL" mismatch.
> - **Anti-influencer prose** — removed the "cite by name" constraint, added yt-signal name-stripping pre-formatters.
> - **Real catalyst mining** — new SerpAPI catalyst pass in `gap_fill` (partnerships / analyst-day / stock-catalyst queries); `!all` now cites verifiable events (Meta-AMD MI450 6GW, OpenAI $100B-NVDA, Tesla-Samsung $16.5B) instead of options-expiry filler.
> - **Embed dedup** — dropped the 8 trade-plan-duplicating inline fields; only Direction / Confidence / Price remain alongside the LLM trade-plan table.
> - **Expected-move calibration** — `ATR×√N` → `0.7×ATR×√N` (≈ σ-based move); formula now shown in the field so the LLM stops inventing multipliers.
> - Float-precision leak fixed; cross-source conflict surfacing added.
>
> Full run log: `.claude/discover/gemini-quality-all-command/pass-5-execution-log.md`
>
> **What REMAINS open under this umbrella** (the "menu" — none are blockers, pick per-session): market-cap floor on `!all FAKEX`, data-sparseness warning banner, options-flow / max-pain integration into the trade plan, competitor / sector-context mini-block, earnings-week-aware horizon clipping, `compute_pattern_strength` for chart patterns, and the external feature audit. Architecture map + lever list below stays valid for whoever picks those up.

**Layperson:** The user wants to improve what `!all <TICKER>` produces. This is intentionally broad — the framing matters because most of the visible output isn't decided by the LLM. Before any session picks this up, read the architecture map below so you don't waste effort "fixing" things in the wrong place.

## Execution discipline (non-negotiable for this initiative)

**1. The goal is what matters.** This is an open-ended quality initiative — there is no "completion ceremony" to chase. The worst possible outcome is shipping code that fails live testing and then falling back to *"we can just ditch the code."* That outcome burns time, tokens, and the user's trust. Before writing any code, name the user-observable outcome that must hold true after the session ends ("the embed now shows a max-pain level for every ticker", not "max-pain integration is in"). If you can't name it crisply, do not start coding — scope down or pick a different lever.

**2. Pre-flight any feature that needs scraping or external-site access.** If the proposed feature pulls data from Unusual Whales, TipRanks, OptionStrat, Finviz, Seeking Alpha, or any other third-party site, **do a live access test first** — fetch the page or hit the endpoint manually with Firecrawl / WebFetch / curl and confirm you can actually extract the field you need from this VPS. If bot detection blocks you, a proxy returns empty, the data is paywalled, the markup is too dynamic to parse reliably, or the rate limits make production use untenable — **stop there and reconsider the lever before writing any code.** The failure mode this prevents: building a full end-to-end integration only to discover at live-test time that the source is inaccessible with no workaround. Capture the access-test result (worked / blocked / partial) in the external feature audit alongside the feature row, so the same pre-flight isn't redone next session.

## Architecture — who actually decides what

`consensus_engine/alerts/all_command/` is the package. Order of operations on a single `!all` invocation:

1. **`aggregator.py`** (802 lines) — the conductor.
   - Validates ticker format via `is_valid_ticker` only — **no market-cap gate** (main alerting engine has one; `!all` skips).
   - Fans out data fetches: Finnhub `/quote` (current price), yfinance OHLCV (technicals), Finnhub news, Brave + SearXNG (broader web), Reddit/social, YouTube indexed analyst calls, SEC EDGAR filings, TweetShift Twitter signals, internal #chat + #brief Discord history, prior vault excerpts.
   - Calls technical-indicator computation (RSI, EMAs, ATR, volume).
   - Calls `structured_fields.compute_*` and `levels.select_trade_plan`.
   - Packs everything into a `StructuredFields` dataclass at line 595.
   - Hands the clipboard to `narrator.synthesize_narrative`.

2. **`structured_fields.py`** (321 lines, 9 compute_ functions):
   - `compute_direction`, `compute_confidence_label`
   - `compute_buy_zone` (line 141), `compute_breakout_timeframe`
   - `compute_magnitude`, `compute_magnitude_band`
   - `compute_swing_horizon` (line 209), `compute_next_catalyst_days`
   - All pure arithmetic on the data the aggregator already fetched.

3. **`levels.py`** (469 lines) — TP1/TP2/TP3 + stop-loss anchor logic:
   - `extract_anchors_from_youtube_levels` (line 165), `extract_swing_levels` (214, from candles), `extract_anchors_from_search_snippets` (258, from news).
   - `cluster_anchors` (310), `rank_anchors` (375) — confluence + freshness + source-tier scoring.
   - `select_trade_plan` (430) — picks the final SL + 3 TPs.

4. **`narrator.py`** — synthesis prompt builder + LLM call:
   - System instruction (line 238): "COMPUTED SIGNAL is authoritative — never contradict its direction, confidence label, or price levels. Do NOT invent prices or levels."
   - `_build_synthesis_prompt` (~line 320) packs the COMPUTED SIGNAL + 18 evidence blocks (news, sec, twitter, social, yt_signals, yt_options, yt_evidence, technical, earnings_recap, chart_pattern, etc.) with per-section caps to stay under 15k input tokens.
   - LLM call at `_invoke_synthesis` (~line 423): `call_with_fallback(role="primary", max_tokens=8000, temperature=0.35)`.
   - The 5-model chain (re-selected 2026-05-16, see `.omc/research/llm-chain-2026-05-16/`) runs here.

5. **`output_filter.py`** — contradict-detection retry:
   - `detect_contradiction(narrative, structured)` (line 61) scans the LLM output for new/contradicting price levels.
   - `sanitize_or_retry` (line 86) — on contradiction, re-prompts the LLM with a hardened instruction. Returns `("", "fallback_data_only")` if retry also fails; engine then renders the deterministic embed.

6. **`embed.py`** — Discord embed renderer (color + footer + fields).
7. **`vault_writer.py`** — writes `<vault>/tickers/<TICKER>-all.md`.
8. **`cache.py`** — single-flight + 15-min TTL on `xref_cache` table keyed by `all_v<8-char-version-hash>:TICKER`.

## Output-quality levers (by where the work lives)

The 2026-05-16 isolation test showed all 5 chain models produce the same trade plan numbers — the only visible LLM-side variation is prose, catalyst selection, formatting, source-attribution style. So:

**LLM-side changes don't move the trade plan.** To improve the actionable numbers, work in `structured_fields.py` + `levels.py`.

**Engine-side (deterministic) levers:**
- `levels.select_trade_plan` — current weighting blends YouTube analyst calls + swing levels from candles + news mentions. Tune `_freshness_bonus`, `_distance_penalty`, `_confluence_bonus` for better target placement. Currently TP2/TP3 get "padded" when fewer than 3 anchors land — gpt-oss-120b annotates this self-aware-ly; others stay silent. Could add anchor-count to COMPUTED SIGNAL so every narrative can comment on it.
- `structured_fields.compute_buy_zone` — uses current price ± a band. Could incorporate VWAP, EMA20 support, or recent swing-low proximity.
- `structured_fields.compute_swing_horizon` — derived from `|TP1−spot|/(0.7×ATR)` capped at next catalyst. Could weight by recent realized volatility instead of headline ATR.
- `structured_fields.compute_next_catalyst_days` — currently earnings-only. Could include options expiry, ex-div, FDA dates, pre-announced events from `news_catalyst`.
- Add a `compute_pattern_strength` for chart patterns beyond the current `chart_pattern` block — engine already detects double-bottom etc., could score breakout-readiness.

**LLM-side (prose) levers** (everything below leaves the trade plan unchanged):
- `narrator._build_synthesis_prompt` — the CONSTRAINTS block tells the model exactly what sections to write. Tightening the wording (e.g. "every catalyst must cite an evidence row by index", "rationale column must be ≤ 25 words") removes the per-model wording drift the 2026-05-16 test surfaced.
- `narrator._build_synthesis_prompt` — evidence blocks are sent via `json.dumps(... default=str)`. The EARNINGS RECAP block already gets pre-formatted via `_format_earnings_recap` (added 2026-05-16, commit 732a475). Other blocks (news, sec, twitter, social, yt_*) still pass raw — could apply the same pre-formatting pattern for date strings, large dollar amounts, etc. to remove formatting variance between chain models.
- `narrator._build_constraints_block` — currently asks for "AT LEAST 2 catalysts". Could raise to AT LEAST 3 when ≥3 distinct source-types surfaced, fall back to 2 only when evidence is thin.
- `quality_bar.py` — already enforces minimum standards. Worth reviewing what it catches vs. what it lets through.

**Feature gaps** (things `!all` doesn't currently do):
- No market-cap floor — `!all FAKEX` succeeds-empty instead of replying "ticker not found on exchange." Fix: call `validate_ticker_market_cap` in `aggregator.handle_all` before the data fetch.
- No "data sparseness" warning — when ≤2 sources surface, the embed still renders confidently. Could add a "low-confidence: only N sources" banner.
- No options-flow integration in the trade plan — engine fetches options data (used in scoring) but the TPs don't incorporate max-pain or large-strike concentration.
- No competitor-context — for big tickers like AMZN, the narrative doesn't relate to AAPL/MSFT/GOOGL moves. Could pull a "sector context" mini-block.
- No earnings-week-aware horizon — if earnings is in 3 days, current horizon often spans the print; could clip horizon to T-1.
- Cache is binary (hit/miss). On miss the user waits 60-180s with no intermediate progress.
- Chart-pattern detection runs but only feeds the LLM. Could add pattern_strength to the visible embed.

## Existing prior art

- **memory: `project_all_command_v2_planning.md`** — there's already a v2-quality-rebuild planning effort in `.claude/discover/all-command-rebuild/v2-quality-rebuild/`. Start by reading that before scoping new work — may already capture some of the items above.
- **Layer C blind-compare with Gemini** is the human eval loop for any quality changes; should be re-run after any user-visible improvement.
- **TODO #2 (speed-accuracy-optimization)** overlaps with output latency improvements above.
- Float-precision fix (commit 732a475, 2026-05-16) was an early win in this initiative — see `_format_earnings_recap` in `narrator.py` for the pattern applied.

## External research — feature gaps from the web

The "Feature gaps" list above is everything *I* (the codebase author) already noticed. The high-leverage gaps are the ones nobody's looked for yet. Before scoping any internal lever, spend material time auditing what other stock/trading-analysis tools surface that `!all` doesn't. Sources to mine:

- **Direct competitors** (free + paid tiers): TipRanks, Seeking Alpha, Benzinga, Finviz, Stocktwits, TradingView analysis pages, Simply Wall St, Koyfin, Stock Analysis dot com, Yahoo Finance, Robinhood research pages. What sections does each ticker page have? Which are free-tier table stakes vs. paywalled premium?
- **Discord / Telegram trading bots** — Unusual Whales, FlowAlerts, AlertaPro, options-flow bots. What does their `/ticker` or `/all` equivalent produce? What flow / sentiment / dark-pool data do they surface that `!all` doesn't?
- **Sell-side research formats** — bank initiation reports, one-pagers, "morning notes". What sections are table stakes (catalysts, risks, peer comp, valuation tables, scenario fans)?
- **Retail trader subreddits** (r/wallstreetbets, r/options, r/stocks, r/investing, r/SecurityAnalysis) — top-upvoted DD post structure conventions. What sections do high-quality DDs always include?
- **Hedge fund letters / public memos** — public quarterly letters. What frames do they use for thesis articulation, position sizing, catalyst timelines?
- **Twitter/X fintwit accounts** — what data points do top-engagement ticker tweets reference (options flow, OI changes, gamma levels, short interest deltas, insider clusters)?

**The audit format — a markdown spreadsheet, not prose.** Produce a table with one row per missing feature and these columns: **Feature** | **Where I saw it** | **Build cost** (trivial / medium / big) | **How common** (count across competitor sources) | **Pre-flight access** (worked / blocked / partial / N/A — fill this in by actually hitting the source from this VPS per discipline rule 2 above).

Concrete examples of what good rows look like:

| Feature | Where I saw it | Build cost | How common | Pre-flight access |
|---|---|---|---|---|
| "Max pain" options level | Unusual Whales, OptionStrat | Medium — needs options chain data | 4/5 options tools | Blocked (UW Cloudflare) / partial (OptionStrat parseable) |
| "3 insiders bought in last 30d" badge | TipRanks, OpenInsider | Trivial — Form 4 data already fetched | Almost universal | N/A (use existing SEC pipeline) |
| Short-interest delta ("SI up 8% WoW") | Finviz, Stocktwits, Fintel | Medium — needs a SI data provider | Most retail tools | Worked (Finviz HTML stable) |
| Peer-comparison mini-table (P/E, growth vs. AAPL/MSFT) | Seeking Alpha, Koyfin | Big — needs peer ticker logic | Sell-side standard | Blocked (SA paywall) / Worked (Koyfin free tier) |
| "Earnings move history" ("avg ±6% on prints") | Benzinga, Estimize | Trivial — calc from existing OHLCV | ~half of tools | N/A (compute locally) |

The audit's job is to make trade-offs visible at a glance. Sort by **best ratio of "shows up everywhere" to "cheap to build" AND pre-flight = worked / N/A** — those rows are the high-leverage gaps with no surprises waiting. Ship them first. Rows where pre-flight is "blocked" are *not* candidates until a workaround is documented in the same audit.

Land the audit at `.claude/discover/all-command-rebuild/external-feature-audit-<YYYY-MM-DD>.md` before scoping any concrete code change. Use Firecrawl / WebSearch / WebFetch heavily — this is a "go deep" research pass, not a 10-minute skim. The audit becomes the shared menu future sessions draw from.

## How to scope a session

This TODO is intentionally broad — don't try to do it all in one session. Recommended first move: read the v2-quality-rebuild artifacts, then pick ONE lever from the lists above + write a focused spec for just that change (e.g. "tighten Trade Plan rationale to ≤25 words and re-test all 5 chain models for compliance"). Use the test methodology from `.omc/research/llm-chain-2026-05-16/probe_llm_chain.py` as the quality-regression harness.

**Acceptance for this TODO is "shipped at least one user-visible quality improvement with before/after evidence."** Not "completed all items above" — those are a menu, not a checklist.

---

## Update 2026-05-30 (run `all-levers-2026-05-29`)

Two more levers shipped from the menu (commits `53e3e35` + `7d77245`, live-verified on NVDA/AMD/DELL):
- **Max-pain** — `scanners/options.py:compute_max_pain`; nearest-weekly + nearest-monthly max-pain strike from the yfinance option chain; embed field only (no narrator). Textbook argmin-payout over listed strikes. Known caveat (user-confirmed, left as-is): for stocks that ran up, the monthly max-pain can sit far below spot because stale deep-ITM OI dominates — that's the correct definition, not a bug.
- **Peer relative strength** — `analysis/peer_comparison.py` + NEW `data/peer_groups.yaml` (sub-industry peer layer, separate from the A4 `sector_map.yaml` gate). 5-day stock move vs peers' average; curated peers → dynamic `.info` fallback → sector ETF. Embed field + narrator (curated-mean mode only). Config: `features.peer_comparison.*`.

Still OPEN — the menu has more levers. Also fixed a found bug: `!all` Trends gated on the non-existent key `features.serpapi_enabled` → corrected to `precision_engine.serpapi_enabled`.

## Update 2026-05-31 (run `all-quality-and-yt-score`)

Two more levers + three correctness fixes shipped (suite 1433 green, 0 regressions; live-verified on NVDA/AMD + deployed `!all NVDA` round-trip).

- **📊 Snapshot field** (commit `3fc4311`) — NEW `consensus_engine/scanners/snapshot.py`: one yfinance `.info` fetch (own bounded executor, won't starve the shared pool) → one compact embed field with **analyst price target + range + count + rating, forward P/E, short %/days-to-cover**. The single most-ubiquitous gap (table stakes on TipRanks/Yahoo/Finviz). Conditional-omit when `.info` empty/throttled (logged). Flag `features.snapshot.enabled` (defaults true in code; not in yaml to avoid bundling an unrelated pending consensus.yaml edit). **Live:** NVDA `🎯 $297 avg ($180–$500) · 58 anlsts · Strong Buy | Fwd P/E 17 · Short 1.3% (1.9d cover)`; deployed `sources_surfaced` 13→16.
- **R:R field** (commit `4a80547`) — `structured_fields.compute_risk_reward`: reward-per-1.0-risk from the plan's SL/TP1 vs spot, direction-aware, rendered inline `R:R 1:X`. **Omitted on ATR-fallback (low-confidence) plans** so synthetic levels can't produce an authoritative-looking but meaningless ratio. (NVDA/AMD currently hit atr_fallback → R:R correctly hidden; verified positive render via `build_embed` test.)
- **3 fixes** (commit `6a2c5b9`): BUG-1 earnings-days tz (utcnow→local date — killed a 7h/day trade-plan-vs-embed disagreement); BUG-3 scanner-failure logs debug→warning (no more silent source drops); BUG-4 footer source count now includes youtube_visual + recent_earnings.

Still OPEN — menu has more levers. Top remaining cheap/ubiquitous (yfinance, pre-flight GREEN): earnings track record (avg ±% post-ER move), 52wk-high/low distance, relative volume, P/C-OI ratio. Biggest optimization (flagged, NOT done — too risky for one session): the synth model-chain walks serially per model → 60–240s tail; race/short-timeout it.

## Update 2026-06-01 (run `all-quality-cheap-levers`) — branch `feat/allcmd`, commit `a178cf7`, NOT live yet

Shipped 2 of the 4 listed cheap levers; 17 new tests, full suite 1551 passed; live NVDA verified.
- **Relative Volume** — today's volume vs its 20-day average, as a "Rel Vol N.N×" embed field. Found+fixed `fetch_daily_candles` silently dropping the volume array; threaded `daily_candles` through the `data` dict to the StructuredFields construction. Live NVDA → **1.77×**.
- **52-week high/low distance** — pulled from the Snapshot's existing `.info` fetch (`fiftyTwoWeekHigh/Low` + price), rendered as a compact "N% below 52wk high" segment in the Snapshot field. Zero new fetch. Live NVDA → **10.7% below high**. (This value also now feeds #22's overextension bullet.)

**Deferred (path documented in the run's final-plan):** P/C-OI ratio (`_max_pain_for_chain` discards split call/put OI — needs a return-shape refactor) and earnings-move history (needs ~2y OHLCV + historical earnings dates, neither currently fetched). Stays OPEN (menu). Go live via the Step-4 handoff (`.claude/discover/parallel-6-21-22-STEP4-HANDOFF.md`), HELD pending the wolf session.

**LIVE 2026-06-01 09:52** — RVOL + 52wk merged to master (`9e0c760`) + pushed; real `!all NVDA` shows `Rel Vol 0.7×` and `6% below 52wk high` in the Snapshot field. Menu stays OPEN — next cheap levers: P/C-OI (sum call/put OI in `_max_pain_for_chain`), earnings-move history; biggest is still the serial model-chain latency.

**LIVE 2026-06-01 11:09** — two MORE cheap levers shipped (merged `d42603f`, pushed, live-verified on real `!all NVDA`):
- **Put/Call OI ratio** — `_max_pain_for_chain` now also returns the call/put OI sums (it computed then discarded them); `compute_max_pain` adds `pc_oi_ratio`; embed field "P/C OI". Live NVDA 0.42, AMD 1.39.
- **Earnings-move history** — NEW `scanners/earnings_move.py` (bounded executor + timeout, mirrors snapshot.py); avg abs % reaction over last 8 prints, reaction day picked by report time (after-close → next session); embed field "Earnings ±X.X% (N)". Live NVDA ±3.7%, AMD ±8.5%, TSLA ±7.5%. Pre-flight caught a wrong-alignment bug first (don't measure the report-day session for after-close reporters). avg cast to native float (no np.float64 into the cache/LLM).
- Also fixed a #22 scrub gap found during live verify: the model emits free-text `[evidence: the data ...]` tags the numeric-only regex missed — broadened `output_filter` to strip `[name]`/`[name: ...]` (with a `:`-guard so real phrases survive).

Menu STILL OPEN. Remaining biggest item: the serial model-chain latency (60–240s). Minor cosmetic: the scrub can leave a dangling "," when a tag followed a comma — low priority.

## Update 2026-06-02 — cleanup reliability + things to watch/optimize

Two cleanup-chain changes plus a set of lessons worth keeping. ("Cleanup" = the small AI calls that tidy up raw evidence — tweets, news, filings — before the main writeup. In code: `_batch_summarize` (searxng/news/sec/chat/brief batches) + `vault_excerpt`, role=text.)

**Shipped:**
- **Cleanup taken off groq — `5e64656`, LIVE.** Those ~7–9 cleanup calls per `!all` used to run on groq first, the same model the main writeup needs. They burned ~18–25k of groq's 100k/day free budget per command, so after ~5 commands groq ran dry and the writeup fell back to slow models. Now cleanup runs on a groq-free chain (`all_command_sanitize_chain`); the writeup keeps groq.
- **Tried nemotron as cleanup lead — TRIED AND REVERTED.** The free cleanup pool (gpt-oss-120b/20b) is unreliable: gpt-oss-20b returns "too busy" (429) ~half the time and gpt-oss-120b swings 2–11s, so cleanup often times out → trimmed raw text. (Our OpenRouter account is paid and barely used — 6¢ of a $5/day allowance — so the 429s are the *free pool's* shared limit, not us.) Tried prepending `nvidia/nemotron-3-nano-30b-a3b:free` — looked great in quick 3-item probes (~1s, valid summaries). **But it FAILED live and was reverted:** nemotron is a *reasoning* model — on the real 20-source cleanup batches its hidden reasoning eats the whole 512-token budget and it returns BLANK (confirmed via the API's usage counters: 408 reasoning tokens, 0 content). **Lesson: no reasoning models in the cleanup chain.** Reverted to the off-groq 2-model chain (the `5e64656` baseline).
- **KEY FINDING — cleanup failing has NO visible effect on the writeup.** Every live and clean test produced a valid narrative regardless of whether cleanup succeeded or fell back to trimmed raw text — the writeup is robust to messy/trimmed evidence. So free-model cleanup reliability is a **low-value** problem; don't keep chasing it with free models. The only thing that would actually make cleanup run reliably is a cheap PAID non-reasoning model (~0.1¢ per `!all`) — deferred (free-first by design).

**Issues to WATCH / TEST:**
1. **Cleanup fails quietly, not loudly.** When every cleanup model fails, it silently uses trimmed raw text (500 chars) — the writeup still renders, just from rawer input. Health check: during a real `!all`, grep the engine log for `LLM fallback chain exhausted for role=text`. That line = cleanup failed that batch (currently common — the free pool is flaky). Per the KEY FINDING above this is low-impact, but if you ever want it fixed, go paid-model.
2. **Groq can't do the writeup for big tickers.** For source-heavy tickers (e.g. NVDA, 20 sources) the writeup request is bigger than groq's free 12,000-tokens-per-minute cap, so groq rejects it (413) and the work hands off to the free models. So groq only ever "wins" the writeup on small tickers — the head-start speed trick rarely helps the biggest ones.
3. **Cleanup and the writeup share one 160-second budget.** A slow cleanup phase eats the time the writeup needs for its quality-retry passes; starve those and the writeup drops to the bare data-only fallback. This is exactly why bumping the cleanup deadline to 12s BACKFIRED (tested: 3 models × 12s = 36s cleanup tail → downgraded narratives). **Keep cleanup fast.**
4. **Testing trap that cost real time this session:** measuring the `!all` path by hooking into the AI-call layer (`call_with_fallback` / `synthesize_narrative`) breaks the head-start race logic and produces FALSE empty narratives — 100% false-empty *with* that hook, 100% valid *without* it (8 clean tickers). When testing `!all` end-to-end, only mock the edges (the 15-min cache and the Discord send), never the AI calls.

**Optimization IDEAS (not done):**
- **Pay pennies for reliable cleanup.** We use 6¢ of a $5/day OpenRouter allowance. Routing cleanup to the cheap *paid* gpt-oss (~0.1¢ per `!all`) would dodge the free-pool 429s entirely. Deferred (free-first by design) — revisit if nemotron also gets jammed.
- **Trim the writeup prompt for big tickers** so it fits groq's 12k/min cap and groq can actually do the writeup (faster, fewer hand-offs).
- **Guarantee the writeup a minimum slice of the 160s budget** so a slow cleanup phase can never starve its retries.
- **Add 1–2 more independent free providers** to the cleanup chain for extra resilience.

## Open item added 2026-06-10 — Smart levels alerts show closing price, not live price

Smart levels alerts (e.g. "$SPY approaching resistance @ $728.00 — current $725.43") label the price as "current" but it is actually the last closing price. The fix is to fetch a live quote (Finnhub `/quote` already in the codebase — same call `aggregator.py` uses) so the reported price is accurate even when the market is closed. Applies to all smart levels alert types (resistance, support, breakout).
