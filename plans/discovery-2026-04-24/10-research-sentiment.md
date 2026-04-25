# Phase 1 Research — Sentiment Domain

**Worker:** disc-p1-sentiment
**Date:** 2026-04-24
**Branch:** `claude/multi-agent-tmux-setup-zWYEQ`
**Mission:** Propose 5–12 candidate sentiment-domain features that surface high-quality, actionable trade setups BEFORE mainstream price confirmation. Output is generative and intentionally over-proposes; later phases gate.

## Framing notes (read first)

Sentiment features are confirmation-class signals, not instant-trigger candidates per the alert philosophy. With one rare exception (a sharp, multi-source crowd-attention shock combined with options flow — covered as an instant-trigger booster, not a primary trigger), the features below are second-source confirmers that improve precision and add lead time when paired with the bot's existing primary triggers (options flow, insider, breakout, quant/factor, tweet).

Three lift dimensions are tracked:
- **Precision delta** — fewer false positives on alerts that fire.
- **Lead-time delta** — earlier detection vs. price-driven triggers.
- **Coverage delta** — net new actionable alerts without raising the false-positive rate.

All endpoints below were verified against current free public docs. Items that failed verification (Cloudflare-walled, ToS-prone, paywall-creep) live in the *Excluded* section.

### Operating model assumed by every feature

- All features run on a polling/streaming worker pool, not the alert hot path. They emit a structured `SentimentSignal` record `{ticker, signal_name, value, z, freshness_ts, confidence, source_class}` consumed by the existing scoring/cross-reference layer.
- Primary triggers (options flow, insider, breakout, quant) remain as today; the new features expand the *second-source* pool used to satisfy the 2-source rule and to enrich the LLM thesis input.
- 8-K / Form 4 rules from `CLAUDE.md` are unchanged. Where SEC EDGAR appears below (Feature 8), it is a *cross-form mention velocity* signal — not a per-filing trigger — so the 8-K standalone-prohibition is respected.
- Each feature documents a failure mode and a degradation path (continue, drop, suppress) so the supervisor loop knows what to do when the source goes dark.

### Lift-tracking discipline

For each feature we declare one primary lift dimension (precision, lead-time, or coverage) and an *evaluable* hypothesis. Phase 4 should write back-test queries against existing Discord history + price tape so each claim is measurable, not just stated.

---

## Feature 1 — Reddit Ticker Mention Acceleration (z-score, multi-sub)

- **Function:** Roll up ticker mention counts every 30 min across `wallstreetbets`, `stocks`, `investing`, `options`, `pennystocks`, `valueinvesting`, `swingtrading`, computing a per-ticker z-score of mention rate vs. its trailing 30-day mean. Alert support fires when z ≥ 3 in ≥2 subs simultaneously.
- **Rationale + measurable edge:** Mention *acceleration* (not raw volume) is the leading edge — it precedes intraday move continuation in WSB-style tickers and small/mid-caps with limited analyst coverage. **Edge metric:** target +30 min median lead-time delta on momentum/squeeze setups vs. current "tweet only" path; +3pp precision when used as second source for breakout candidates by filtering pump-and-fade tickers (low cross-sub coverage).
- **Source category:** Medium (aggregated public feed; OAuth required but no pre-approval at low rates).
- **Free + public source(s):** ApeWisdom public API (`https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}`, no auth, free, scans WSB+other subs twice an hour). Independent confirm via Reddit OAuth Data API (60 req/min/app under OAuth, 100 req/min for OAuth-authenticated apps, free tier intact through 2026 for non-commercial use).
- **Latency:** Intraday (30-min bars; ApeWisdom updates every ~30 min).
- **Failure mode:** Coordinated pumping by paid Discord/Telegram cohorts (manipulation vector). Mitigation: require ≥2 *independent* subs and require dispersion of authors (no single OP cluster).
- **Implementation notes:**
  - ApeWisdom endpoint requires no auth, returns JSON paginated lists. Schedule: every 30 min during cash session, every 2h after-hours.
  - Reddit OAuth needed only for live PRAW polling of the long-tail subs ApeWisdom does not aggregate (e.g., `valueinvesting`, `swingtrading`, `options`). Register a script-type OAuth app; with OAuth, 100 req/min/app is comfortable for ≤6 subs at 5-min cadence.
  - Z-score baseline: trailing 30 calendar days, weekday-matched, log-transformed counts to handle Poisson tail.
  - Author dispersion: store per-mention `(author_id_hash, sub, ts)` for 7 days; reject signals where >40% of mentions share an author or where ≥3 of the top 5 authors appear in each other's reply chain.
- **Existing-code interaction:** `consensus_engine/scanners/reddit_trend.py` is the natural home; this is an upgrade (multi-sub + acceleration), not a new module.

---

## Feature 2 — Wikipedia Pageview Spike (per-ticker article)

- **Function:** Pull hourly pageviews for the ticker's company Wikipedia article and flag z ≥ 2.5 vs. trailing-28-day weekday-matched baseline. Use as +1 confirmation source toward the 2-source rule.
- **Rationale + measurable edge:** Moat/Curme/Preis (Sci. Reports 2013) and follow-on work show retail attention on Wikipedia precedes price moves in single names; transfer-entropy work across 447 stocks 2008–2017 confirmed predictive flow. Wikipedia spikes are slow, robust, and uncorrelated with options/news triggers — high marginal information. **Edge metric:** +2pp precision delta when used as second source on tweet-driven primary signals; ≥45 min lead-time delta on retail-narrative tickers.
- **Source category:** Medium (regulated/audited platform metadata, no scraping).
- **Free + public source(s):** Wikimedia Pageviews API: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/{article}/hourly/{start}/{end}` — 200 req/sec public limit, no auth, no key. Article resolution via OpenFIGI free API (no daily/monthly cap; v3 endpoint required after July 2026 sunset).
- **Latency:** Hourly (1–2 h delay from Wikimedia ingest).
- **Failure mode:** Article ambiguity (e.g., common-noun tickers like `ALL`, `BABY`, `MOON`) and bot-driven pageview spikes (vandalism/scraping). Mitigation: filter against bot UAs already excluded in `all-access/user`, and require company-page disambiguation (validate via FIGI symbology then lock the canonical Wikipedia article).
- **Prior art:** Moat, Curme, Avakian, Kenett, Stanley, Preis, "Quantifying Wikipedia Usage Patterns Before Stock Market Moves," *Scientific Reports* 3:1801 (2013). Follow-on: Brown & coauthors, transfer-entropy work across 447 stocks 2008–2017 ("Wikipedia and Stock Return," ResearchGate 2017). Also: ScienceDirect S1057521920302076 (2020) on Wikipedia searches and stock returns.
- **Implementation notes:**
  - Article resolution: maintain a `ticker → wikipedia_article_slug` map seeded from OpenFIGI + Wikidata. Validate by checking the article's infobox for ticker symbol; reject ambiguous matches.
  - Baseline: 28-day weekday-matched mean and stdev of log-transformed hourly views; only fire when current hour's z ≥ 2.5 AND prior-hour z ≥ 1.0 (rules out single-hour spikes from a viral non-financial event like an ad campaign or a celebrity reference).
  - Cache: 1-hour TTL per article. Endpoints respond fast (< 200ms typical).
- **Existing-code interaction:** New module `wikipedia_attention.py` in `consensus_engine/scanners/`. No overlap with current scanners.

---

## Feature 3 — GDELT Global Tone Drift (organization + theme filter)

- **Function:** Query GDELT Doc 2.0 every 15 min for articles mentioning the company name in `Organization` filter; track (a) volume z-score (`timelinevol`) and (b) average tone (`timelinetone`). Alert when volume z ≥ 2 AND tone moves >1.5σ from 30-day mean (positive *or* negative — directional).
- **Rationale + measurable edge:** GDELT scans 100K+ global news outlets every 15 min in 65 languages, well beyond US wire coverage. Multiple peer-reviewed studies (Chinese equities, S&P 500, Italian sovereign, Saudi index) confirm tone-volume features have predictive power on returns/volatility. The bot today has US-anchored news; GDELT plugs the *international* coverage hole. **Edge metric:** ≥20% net-new coverage on tickers with foreign exposure (semis, ADRs, multinationals) without false-positive inflation.
- **Source category:** Medium (aggregated public feed, official API).
- **Free + public source(s):** GDELT Doc 2.0 API: `https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=timelinetone&format=json`. Tone filter syntax: `tone>5`, `tone<-5`, `toneabs>10`. Rate-limited (sub-1 QPS shared) — implementation must cache and batch. Python client: `gdelt-doc-api`.
- **Latency:** Intraday (15-min ingest cadence).
- **Failure mode:** Organization-name disambiguation (e.g., "Apple" → fruit) — must combine `organization` filter with `theme:ECON_STOCKMARKET` and/or company-name proximity. Mitigation: maintain a curated org-name → ticker map; reject low-confidence matches.
- **Prior art:** Multiple peer-reviewed studies confirm GDELT tone has predictive lift: BBVA Working Paper 22/05 on Chinese equities; ScienceDirect S0927538X22001056 on volatility; ASITE study on PSE composite index; arXiv 2505.16136 (FinBERT + GDELT macro alpha case study reporting Sharpe 5.87/4.65 on FX). The U.S. equity result of "GDELT improves on a purely macroeconomic approach" is the most relevant for our retail bot.
- **Implementation notes:**
  - Recommended query template: `query=(domain:reuters.com OR domain:bloomberg.com OR domain:wsj.com OR domain:cnbc.com OR ...) AND ("{company_name}" near10 ("stock" OR "shares" OR "trading"))&mode=timelinevolinfo&format=json&maxrecords=250`. Adjust per ticker.
  - Throttle: GDELT enforces shared sub-1-QPS; cap to 1 query / 60 s / instance and cache 15-min windows. Use `gdelt-doc-api` Python client (alex9smith) which already implements polite retry.
  - Combine the `timelinevol` and `timelinetone` series into a single bivariate signal (volume z and tone z) before alerting.
- **Existing-code interaction:** `consensus_engine/scanners/news.py` already pulls news; this adds a new `gdelt.py` module that operates *parallel* to news.py rather than replacing it (different latency, different coverage).

---

## Feature 4 — News Headline FinBERT Sentiment with Catalyst-Language Score

- **Function:** Run FinBERT (locally, free model) on every headline + lede the bot already pulls (Yahoo RSS, Nasdaq RSS, CNBC RSS). Compute (a) classifier score, (b) a *catalyst-intensity* dictionary score over financial event terms ("guides higher", "raises", "beats", "upgrade", "FDA approves", "settled"). Combined drift > threshold = +1 source.
- **Rationale + measurable edge:** FinBERT (~69% accuracy on financial sentiment) is materially better than VADER (~56%) for the domain and runs locally with no API cost. Pairing classifier + catalyst-term lexicon recovers edge on neutral-classified headlines that contain hard-news language. **Edge metric:** +4–5pp precision on "news-driven" alerts; ~15 min lead-time delta when polling RSS at 60s vs. waiting for analyst-tweet aggregation.
- **Source category:** Medium for the input (Yahoo/Nasdaq/CNBC RSS = aggregated public feeds); Compute is local and free (Hugging Face `ProsusAI/finbert` or `yiyanghkust/finbert-tone`, MIT/CC licenses, run via `transformers` lib offline). No third-party inference quota dependency.
- **Free + public source(s):** Yahoo Finance RSS: `https://finance.yahoo.com/rss/headline?s={TICKER}`; Nasdaq RSS index; CNBC RSS feeds. FinBERT model: `https://huggingface.co/ProsusAI/finbert` (download once, run locally).
- **Latency:** Real-time (RSS polling at 60–90s; FinBERT inference ~50ms/headline on CPU).
- **Failure mode:** Yahoo RSS occasionally throttles by IP and changes URL templates without notice. Mitigation: triangulate against ≥2 RSS sources; circuit-breaker on RSS failure; FinBERT itself is robust because it's local.
- **Prior art:** FinBERT achieves ~69% accuracy vs. VADER's ~56% on financial sentiment (DeepWiki/dshilman benchmark and ACM 3677052.3698675 FOMC eval). DistilRoBERTa fine-tuned on financial news (`mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`) is a faster alternative if CPU latency matters. ProsusAI/finbert is the standard production choice; yiyanghkust/finbert-tone is a strong alternative for tone-specific tasks.
- **Implementation notes:**
  - Run FinBERT on CPU via `transformers` pipeline; ~50ms/headline on a modest server. No GPU required.
  - Catalyst-language lexicon: 200–500 phrases tagged into events (`guidance_raise`, `analyst_upgrade`, `regulatory_approval`, `lawsuit_settled`, `acquisition_offer`, `earnings_beat`). Use Loughran-McDonald financial dictionary as base + curated additions. Score is a hard-news intensity index, separate from the FinBERT softmax.
  - Combine: `composite_score = 0.6 * finbert_z + 0.4 * catalyst_z`. Threshold on the composite, not the individual components.
  - Polling: Yahoo RSS every 60s during market hours, every 5 min after hours; CNBC/Nasdaq RSS every 2 min. Dedupe by article URL hash before scoring.
- **Existing-code interaction:** `consensus_engine/scanners/news.py` already polls RSS; this adds the FinBERT inference step + catalyst lexicon. Can be implemented as a new `sentiment/` subpackage with two modules (`finbert.py`, `catalyst_lexicon.py`) and called from `news.py`.

---

## Feature 5 — YouTube Search-Volume + Upload-Velocity Per Ticker

- **Function:** Twice-daily YouTube Data API v3 query for `q="{ticker} stock"` filtered to `publishedAfter` last 24h. Track (a) upload count z-score, (b) total view count of new uploads, (c) channel diversity (unique channels mentioning vs. last 14d baseline). Spike across all three = +1 source.
- **Rationale + measurable edge:** YouTube finance creators (1M+ niche channels) front-run mainstream coverage on retail-narrative tickers (EVs, biotech, AI plays, meme rotations) by hours to days. Channel-diversity term filters single-creator hype. The current `youtube.py` scanner appears to consume listed channels; this is a *broad search* feature, complementary not duplicative. **Edge metric:** ≥30 min lead-time delta on retail-driven momentum names; +20% coverage on under-followed small caps.
- **Source category:** Medium (official Google API).
- **Free + public source(s):** YouTube Data API v3 `search.list` endpoint. Free quota = 10,000 units/day; `search.list` costs 100 units/call → 100 searches/day. With ~50 watchlist tickers polled twice daily that fits. `videos.list` is 1 unit/call for view counts (cheap).
- **Latency:** Intraday (twice daily; can shift to hourly on small watchlist).
- **Failure mode:** Quota exhaustion if watchlist scales — mitigate with dynamic ticker prioritization (only score tickers with another active signal). YouTube can also be gamed by bot uploads; channel-diversity filter mitigates.
- **Implementation notes:**
  - Free quota arithmetic: `search.list = 100 units`. With 10,000 units/day, that's 100 searches/day. Strategy: triage to "active" tickers (any other signal in last 24h) for `search.list`; for the long tail, just call cheap `videos.list` (1 unit) on already-known channel uploads.
  - Use `q="{ticker} stock"` AND `q="{company_name} stock"` separately to avoid `q="ALL"` collisions on common-noun tickers.
  - Channel-diversity score = `unique_channels_today / unique_channels_baseline_14d`. Only fire when ratio ≥ 1.5 AND z ≥ 2.
  - Cache: 6-hour TTL per ticker; only re-query when an active signal appears.
- **Existing-code interaction:** Existing `consensus_engine/scanners/youtube.py` (per project memory: FinalYTplan shipped 2026-04-13 with Phase A-D YouTube intelligence). This new feature is the *broad search* counterpart to the curated-channel listener; explicitly different. Phase 2 should confirm no overlap with the curated-channel reliability-weighting logic.

---

## Feature 6 — Google Trends Cross-Confirm via Multi-Backend Wrapper

- **Function:** Maintain a Google Trends backend with three fallbacks: (1) official Google Trends API alpha (when available), (2) `pytrends` (treat as best-effort), (3) Exa AI search-trend proxy (already used in repo per memory). Query daily-resolution interest-over-time for ticker + brand keyword; flag breakouts vs. 12-week baseline.
- **Rationale + measurable edge:** Preis et al. (Sci. Reports 2013) showed Google Trends search-volume changes precede DJIA moves; Wikipedia paper (Feature 2) extended for individual stocks. Edge today comes from *combining* both attention proxies — they fail at different times. **Edge metric:** When both Google + Wikipedia agree (z ≥ 2 each), historical evidence supports +5pp precision delta at the cost of slower latency (daily).
- **Source category:** Medium (Google Trends, Wikipedia) but `pytrends` is fragile so wrap with fallbacks.
- **Free + public source(s):** Official Google Trends API alpha (Google for Developers, 2025 rollout, structured "interest over time"). `pytrends` PyPI lib (best-effort; documented breakage every ~2 months). Exa AI fallback already in repo.
- **Latency:** EOD / daily.
- **Failure mode:** `pytrends` blocks (frequent, per GitHub issues #66, #523). Mitigation: triple-backend wrapper; never depend on a single trends source. If both Google and Wikipedia fail, drop the source from the 2-source rule for that day rather than degrade.
- **Prior art:** Preis, Moat, Stanley, "Quantifying Trading Behavior in Financial Markets Using Google Trends," *Scientific Reports* 3:1684 (2013) — the seminal paper. ResearchGate 300829814 (2016) "Anticipating Stock Market Movements with Google and Wikipedia" — directly relevant to the combined-attention thesis.
- **Implementation notes:**
  - Backend selector: try official Google API first (when generally available); on fail or alpha-only restriction, fall back to `pytrends`; on `pytrends` rate-limit, fall back to Exa AI (already provisioned per project memory).
  - Detection: 12-week rolling baseline; fire when current week's interest exceeds baseline 95th percentile.
  - Attention pairing: only mark as "attention-confirmed" when *both* Google Trends AND Wikipedia (Feature 2) trip in the same 48h window. This is a key cross-source rule that shrinks false positives by an order of magnitude vs. either alone.
- **Existing-code interaction:** Per project memory, Pytrends fallback to Exa is already coded. This feature formalizes the multi-backend wrapper and adds the official-API path as primary.

---

## Feature 7 — Influencer Cluster-Convergence (independent-voice count)

- **Function:** From the Discord/TweetShift listener stream the bot already runs, cluster mentions of a ticker by author over a 4-hour rolling window. Score = (number of *independent* authors mentioning) × (network-distance penalty for follower-graph similarity). Alert when N≥4 independent voices converge inside the window AND none of them are in each other's reply chain.
- **Rationale + measurable edge:** A single high-conviction analyst is noise; *uncorrelated convergence* across multiple independent voices is signal. Today's pipeline treats each tweet as ~equal weight; cluster-convergence captures the actual phase change in coverage. **Edge metric:** +6pp precision delta on tweet-triggered alerts (filters single-account hype); modest negative lead-time delta (~10 min) — purely a precision feature.
- **Source category:** Low (anon/pseudonymous social text) — but feature is metadata-only (author IDs and counts), not text scraping.
- **Free + public source(s):** Existing TweetShift Discord stream (no new dependency). For follower-graph similarity proxy, use historical co-mention overlap from the bot's own message log (no external API). Optional: Bluesky AT Protocol public posts via `app.bsky.feed.searchPosts` (App Password required, otherwise unauthenticated public-data reads are open and rate-limit-free for the global IP cap of 3,000 calls / 5 min) for a second platform.
- **Latency:** Real-time (streaming).
- **Failure mode:** Sybil attacks (fake-account cohorts). Mitigation: weight by author age + historical message volume; reject newly-created accounts.
- **Implementation notes:**
  - Independence test: two authors are "independent" if (a) neither retweets the other in the last 30d, (b) the cosine similarity of their last-100-mention ticker history is < 0.6, (c) they were not in the same reply chain in the current cluster.
  - Convergence threshold: N≥4 independent authors mentioning the same ticker within a 4h window AND median author age ≥ 90 days AND median per-author tweet count > 50.
  - Score with a "novelty" multiplier: if cluster includes ≥2 authors who have never mentioned this ticker before, boost confidence; their first mention is informationally heaviest.
- **Existing-code interaction:** `consensus_engine/scanners/discord_tweetshift.py` already ingests TweetShift; this is a derived feature on top of the message stream. New module `cluster_convergence.py` consuming TweetShift output.

---

## Feature 8 — SEC EDGAR Full-Text Search Mention Velocity (regulated catalyst proxy)

- **Function:** Daily query of SEC EDGAR Full-Text Search (EFTS) for a ticker/CIK across all form types in a rolling 30-day window. Track (a) mention count z-score, (b) form-type diversity (3+ form types in week = elevated activity). Output is +1 confirmation source for non-8-K-driven alerts.
- **Rationale + measurable edge:** Regulated/timestamped/auditable. EFTS catches things 8-K-only watchers miss: 13D/G activist filings, S-1 amendments, prospectus updates, comment letters, competitor mentions. Per repo's alert philosophy, 8-K never fires standalone, but EFTS-derived *cross-form mention velocity* gives a quality second source without violating the rule. **Edge metric:** +3pp precision delta when paired with options flow on small caps (where activist 13D/G is highly informative).
- **Source category:** **High** (regulated, timestamped, auditable, official SEC).
- **Free + public source(s):** EFTS API `https://efts.sec.gov/LATEST/search-index?q={query}&forms={form}&dateRange=custom`. No API key, free, rate-limited to 10 req/sec across all EDGAR APIs. Required: `User-Agent: name email@domain` header.
- **Latency:** T+0 to T+15 min after filing acceptance.
- **Failure mode:** EFTS rate-limit IP block (10 min). Mitigation: per-ticker daily polling, exponential backoff, batch by date range. Also: ticker collisions (CIK-locked queries fix this).
- **Implementation notes:**
  - EFTS query format: `https://efts.sec.gov/LATEST/search-index?q=%22{cik}%22&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD`. Anchor on CIK rather than free-text ticker to avoid disambiguation noise.
  - User-Agent: required per SEC fair-use; format `"AppName Contact email@domain"`. Without it, requests are silently 403'd.
  - Velocity computation: rolling 30-day daily count of unique filings mentioning the CIK, z-scored against trailing 12-month baseline (exclude this 30-day window from baseline to avoid contamination).
  - Form-type diversity: track how many distinct form codes (`10-K`, `10-Q`, `8-K`, `13D`, `13G`, `S-1`, `424B*`, `4`, `SC TO-T`, etc.) appear in the rolling window; ≥4 distinct types = elevated activity.
  - Compliance: this feature does not violate the "8-K never standalone" rule — it consumes 8-K *as one of multiple form types* in an aggregate count, never alerts on a single 8-K.
- **Existing-code interaction:** `consensus_engine/scanners/sec_edgar.py` and `sec_watcher.py` already exist. This adds a *velocity* layer on top, not a new ingestion path. SEC watcher loops are gated off by default per project memory; this feature uses the existing EFTS query function but in a separate scheduling path.

---

## Feature 9 — Hacker News + Tech-Community Mention Pulse

- **Function:** Once-hourly Algolia HN search (`https://hn.algolia.com/api/v1/search_by_date?query={ticker_or_company}&numericFilters=created_at_i>{ts}`). Track post + comment counts vs. trailing 30-day baseline; flag z ≥ 3 with ≥3 distinct submitters/commenters.
- **Rationale + measurable edge:** HN front-runs tech narrative on AI infra, semis, dev-tools, biotech-API, fintech-platform names by hours-to-days. Coverage is incomplete for non-tech tickers but very high signal where it overlaps. **Edge metric:** ≥60 min lead-time delta on tech/AI tickers; coverage gap means it's a niche additive source, not a base layer.
- **Source category:** Medium (official Algolia API, no auth, free, no documented hard rate limit beyond fair-use).
- **Free + public source(s):** Algolia HN Search API (`https://hn.algolia.com/api/v1/`). Documented as free-tier public API; no key required.
- **Latency:** Real-time (Algolia indexes within minutes).
- **Failure mode:** Coverage hole on non-tech names (energy, traditional retail, REITs). Mitigation: only enable for sector-tagged tickers (Tech, AI, Semis, BiotechSaaS, FintechPlatform).
- **Implementation notes:**
  - Endpoint: `https://hn.algolia.com/api/v1/search_by_date?query={ticker_or_name}&tags=story&numericFilters=created_at_i>{epoch_24h_ago}` for stories; same with `tags=comment` for comments.
  - Submitter diversity: require ≥3 unique submitters/commenters in the spike window; suppress signals where one user posts repeatedly.
  - Pair with a "tech-relevance" guardrail: only emit if the matching stories have ≥1 of `(news.ycombinator.com|github.com|techcrunch.com|theinformation.com|stratechery.com|...)` in their referenced URLs OR in a curated tech-domain whitelist. This drops irrelevant generic mentions.
  - Polling: hourly; results cached 1h.

---

## Feature 10 — Crowding Exhaustion Detector (retail-saturation flag)

- **Function:** Composite indicator that *negates* a buy alert when retail attention is already saturated. Inputs: (a) Reddit mention z-score (Feature 1) > 5, (b) Google Trends/Wikipedia (F2/F6) at >95th percentile of trailing 6 months, (c) ApeWisdom rank in top-5 for ≥3 consecutive days. If all three trip, suppress new long alerts on the ticker for 24h and flag setup as "crowded — fade-risk".
- **Rationale + measurable edge:** The bot's biggest non-obvious failure mode on momentum names is alerting *after* the retail crowd is fully positioned — exactly when reversal risk is highest. This feature is a *negative* gate, not a trigger. **Edge metric:** -5 to -8pp false-positive rate on momentum-class alerts (precision improvement via suppression); zero coverage cost because no genuinely-new setup gets blocked (a brand-new accelerating signal won't satisfy the 3-day persistence input).
- **Source category:** Medium (uses other features' aggregated feeds; no new endpoint).
- **Free + public source(s):** Re-uses ApeWisdom, Wikipedia API, Trends fallback chain. No new dependency.
- **Latency:** Daily (one composite computation per ticker per session).
- **Failure mode:** Mis-calibrated thresholds suppress real moves. Mitigation: log suppressed alerts and back-test threshold quarterly; the "crowded fade-risk" flag should *appear* in alert payload even when not full-suppressing, so the LLM thesis can adjudicate.
- **Implementation notes:**
  - Decision rule (proposed defaults; tune in calibration phase):
    - F1 z-score > 5 (mention rate ≥ 5σ above 30-day mean)
    - F2 OR F6 attention proxy at ≥ 95th percentile of trailing 6 months
    - ApeWisdom rank in top-5 for ≥ 3 consecutive days
    - ALL three conditions met → suppress new long alerts on the ticker for 24 h; emit a "crowded — fade-risk" flag in the LLM thesis context.
  - Asymmetry: the feature suppresses *new long* alerts only. New short / contrarian / fade alerts are *enhanced* by the same conditions because crowding exhaustion is bullish for fade setups.
  - Logging: every suppressed alert must be recorded with full inputs so retrospective analysis can adjust thresholds.
- **Failure-recovery:** if any input feature is dark, the gate degrades gracefully: with ≤1 input live, the gate is disabled (cannot suppress).

---

## Feature 11 — Headline Tone-Drift Velocity (rate-of-change, not level)

- **Function:** Compute first-derivative of FinBERT sentiment over 8h rolling windows on each ticker's headlines. Alert when *delta* exceeds 2σ — i.e., the *change* in tone is sharp, not just the absolute level. Pair with same-window volume z (count of new headlines).
- **Rationale + measurable edge:** Sentiment *level* is slow and arbitrary; sentiment *velocity* catches narrative inflection (e.g., guidance-cut → analyst capitulation → tone flip). Most retail dashboards report level; using velocity is differentiated. **Edge metric:** ≥45 min lead-time delta on guidance/earnings narrative shifts vs. analyst-rating waterfalls.
- **Source category:** Medium (RSS inputs from Feature 4) + local FinBERT compute.
- **Free + public source(s):** Same RSS sources as F4 (Yahoo, Nasdaq, CNBC, plus optional GDELT for international). No new endpoint.
- **Latency:** Intraday (8h rolling, recomputed every 60 min).
- **Failure mode:** Sparse headlines on small caps make velocity noisy. Mitigation: minimum 8 headlines in window required to compute; otherwise mark as "insufficient signal" rather than emit a noisy reading.
- **Implementation notes:**
  - Velocity = `(tone_window_t - tone_window_{t-8h}) / 8h`. Compute with EWMA smoothing (α=0.4) to suppress single-headline jitter.
  - Pair velocity with volume z to avoid emitting on a single headline that flips tone — sparse data should never fire a velocity alert.
  - Why this is differentiated from F4: F4 alerts on absolute tone *level*; F11 alerts on the *change* in tone. Earnings days, guidance shifts, and analyst capitulation events show up clearly in F11 hours before F4 absolutes drift past their thresholds.
- **Existing-code interaction:** Reuses the FinBERT pipeline added by Feature 4. F4 + F11 should ship together as one delivery (they share infrastructure).

---

## Feature 12 — Bluesky/Threads Cross-Platform Convergence (post-Twitter diversification)

- **Function:** Same convergence logic as Feature 7 but extended to Bluesky `app.bsky.feed.searchPosts` (with App Password) and any Threads public-API access available. Treats finance-Bluesky as an emerging independent voice cluster — different cohort than X.
- **Rationale + measurable edge:** Finance-Bluesky has small but high-quality independent analyst cohort that overlaps minimally with X. When *both* X and Bluesky converge, that's a true cross-platform signal — orthogonal to X-only TweetShift. **Edge metric:** +2pp precision delta on tweet-triggered alerts via independent cross-platform confirmation; effectively zero new coverage today (Bluesky stock-mention volume is low) but rises with platform growth.
- **Source category:** Low–Medium (open AT-Protocol API but UGC text).
- **Free + public source(s):** Bluesky AT Protocol — public posts read freely with no auth at the IP cap (3,000 calls / 5 min); search needs an App Password but is otherwise free. Threads has limited public API access — treat as "if available, additive" not core.
- **Latency:** Real-time.
- **Failure mode:** Bluesky volume on most tickers is currently too low to be predictive; will fail silently except on mega-cap names. Mitigation: ship as opt-in per-ticker, not blanket.
- **Implementation notes:**
  - Bluesky `app.bsky.feed.searchPosts` requires an App Password (free, generated per-account in account settings). Public-data reads of profiles/feeds are unauth-friendly within the IP cap.
  - Watchlist: enable for the top 50 tickers by current bot alert volume; expand if the platform finance cohort grows.
  - Convergence rule: identical to Feature 7 (independent-author count + age + dispersion checks). The signal fires only when the *same ticker* converges on Bluesky AND TweetShift in the same 4h window.
- **Cost-of-failure:** zero — if Bluesky volume is too low, the feature simply does not fire and adds no false positives.

---

## Cross-feature concerns and dedup notes for Phase 2 synthesis

- **F4 + F11 share infrastructure** — both use FinBERT on RSS. Ship as one capability, expose two signals.
- **F2 + F6 are paired by design** — the most precise attention signal is when *both* trip in 48h. Phase 4 should treat them as a joint signal in scoring, not as two independent +1 sources.
- **F7 + F12 share convergence logic** — F12 is F7 with a Bluesky data feed added. Same engine, two input sources.
- **F1 + F10** — Feature 1 emits acceleration; Feature 10 detects exhaustion. Same input data; opposite alerting logic. They must live in the same module so the rolling state is shared.
- **F3 + F8** — both are about "what's *not* on Twitter": GDELT covers international news, EDGAR covers regulated filing flow. Together they patch the two biggest blind spots in the current pipeline (US-tweet bias, foreign-news bias).
- **No overlap with existing scanners by name:** the existing modules (`reddit_trend.py`, `news.py`, `youtube.py`, `sec_edgar.py`, `social.py`, `discord_tweetshift.py`) handle ingest; the new features mostly add *derivative analytics* (z-scores, FinBERT scoring, velocity, convergence, EFTS aggregation) on top of existing or augmented ingestion.

## Calibration & evaluation plan (Phase 4 input)

For each numeric edge claim above, Phase 4 should:
1. Replay the bot's existing alert history for the last 90 days (Discord channel logs).
2. For each historical alert, compute what each new feature *would have emitted* at that moment using a backfilled feed.
3. Bucket alerts into outcome groups (10-min, 1-h, 1-day price tape, +/- thresholds).
4. Report (precision-with-feature, precision-without-feature, lead-time-with-feature, lead-time-without-feature) per feature, per outcome bucket.
5. Lock thresholds at the F1-maximizing point on the precision/recall curve, with per-sector overrides where the data demands.

Without this calibration step, the lift estimates above are hypotheses, not findings. Phase 2 / Phase 3 critics should treat them as such.

---

## Summary table

| # | Feature | Source class | Latency | Primary edge dim | Role |
|---|---|---|---|---|---|
| 1 | Reddit mention z-score (multi-sub) | Medium | 30 min | Lead-time | Confirmer |
| 2 | Wikipedia pageview spike | Medium | Hourly | Precision | Confirmer |
| 3 | GDELT tone+volume (intl) | Medium | 15 min | Coverage | Confirmer |
| 4 | FinBERT headline sentiment | Medium + local | Real-time | Precision | Confirmer |
| 5 | YouTube search/upload velocity | Medium | Twice daily | Lead-time | Confirmer |
| 6 | Google Trends multi-backend | Medium | Daily | Precision | Confirmer |
| 7 | Influencer cluster-convergence | Low (metadata) | Real-time | Precision | Confirmer |
| 8 | SEC EDGAR full-text mention velocity | **High** | T+15 min | Precision | Confirmer |
| 9 | HN/Algolia tech-community pulse | Medium | Real-time | Lead-time | Niche confirmer |
| 10 | Crowding exhaustion (negative gate) | Medium | Daily | Precision (suppression) | Negative gate |
| 11 | Sentiment velocity (dY/dt) | Medium + local | 60 min | Lead-time | Confirmer |
| 12 | Bluesky/Threads cross-platform | Low–Medium | Real-time | Precision | Confirmer |

Phase 2 should especially scrutinize Features 7+12 (overlap with existing TweetShift) and Features 4+11 (both depend on FinBERT pipeline; could be a single capability).

---

## Excluded (and why)

- **Twitter/X public scraping (Nitter, snscrape, twscrape, etc.)** — Cloudflare/IP-block risk + Twitter ToS hostility. Existing TweetShift listener (gateway, not scraper) is the safe path; do not add scraped X scrapers.
- **StockTwits unofficial scraping** — Per project memory, StockTwits already disabled. The "free" StockTwits API surfaces (rapidapi mirror, scraping wrappers) are unstable; the official sentiment endpoint requires partner status. Skip.
- **4chan /biz/ board scraping** — High noise, low signal, ToS gray-area on commercial use, regular Cloudflare challenges, manipulation-heavy. ApeWisdom already covers the meaningful subset; do not scrape directly.
- **Pushshift / Pushshift mirrors (live querying)** — Pushshift was killed 2023; PullPush is best-effort but rate-limited (15 req/min soft, 30 req/min hard, 1000/hr cap) and dependent on a single volunteer-hosted endpoint. Acceptable for *historical backfill only*, NOT for live alert path.
- **Discord public servers via self-bot/scraping** — Violates Discord ToS for self-bots (account ban risk). Only the bot's own subscribed channels via official Bot API are acceptable, which is what TweetShift already does.
- **`pytrends` as a standalone source** — Too fragile (breaks every ~60 days per GitHub issues). Acceptable only inside the multi-backend wrapper in Feature 6, never as the sole trends signal.
- **Tradestie WSB API as standalone source** — Old endpoint returning 403 as of late 2025; downgraded to ApeWisdom + Reddit OAuth combo (Feature 1).
- **News full-article scrapers (Bloomberg/WSJ/FT)** — Paywalled. Headline-only via RSS is acceptable; full-article scraping is out.
- **Truth Social, Telegram public channels, Mastodon-fediverse** — Truth Social has no real public API; Telegram requires per-channel join and has gray-area ToS for monitoring; Mastodon is federated and lacks a single ingestion endpoint, so coverage of finance content would be incomplete and brittle. Skip.
- **TikTok / "FinTok" scraping** — TikTok actively blocks scrapers; no free official API for video metadata at meaningful scale. Skip.
- **Custom NLP via paid LLM APIs (OpenAI, Anthropic)** — Out of scope (paid). FinBERT covers the need locally.
- **Reuters / AP / Dow Jones wires** — Paid. RSS aggregation through Yahoo/Nasdaq/CNBC is the free alternative.
- **Quiver Quantitative / WallStreetZen / FinChat free dashboards as data sources** — These are downstream consumers of similar signals; using them as a source means scraping HTML which is brittle and ToS-prone. Build the underlying signals directly from primary sources instead.
- **Glassdoor / Indeed sentiment as company-health proxy** — interesting but free APIs are non-existent and scraping is ToS-prone. Skip.
- **Crunchbase / PitchBook startup mentions** — Paid, also out-of-scope (most listed equities aren't startups).
- **AlphaVantage news/sentiment endpoint** — has a free tier but its sentiment is shallow vs. running FinBERT locally on RSS, and the rate limit (5 req/min, 500/day on free) is too tight for real-time use. Skip in favor of local FinBERT + RSS.
- **FRED for sentiment proxies** — FRED is macro-economic time-series, not retail sentiment. Out of domain for this researcher; flagged here because some teams confuse "free finance API" with "free finance sentiment API."

## Open questions for synthesis (Phase 2)

- Is Feature 9 (HN pulse) worth the implementation cost given its narrow sector coverage? Phase 2 should rank cost-vs-coverage tradeoff against more universal signals.
- Should Feature 12 (Bluesky) be deferred until platform stock-mention volume passes a threshold? Currently borderline.
- Does the Crowding Exhaustion Detector (Feature 10) belong in this domain or with the risk-management/scoring layer? It is a negative gate, not a positive signal; placement matters for the alert pipeline.
- For the FinBERT pipeline (F4+F11), should the model be cached as a single shared service across all sentiment workers, or instantiated per-worker? Phase 4 implementation choice with material latency implications.

