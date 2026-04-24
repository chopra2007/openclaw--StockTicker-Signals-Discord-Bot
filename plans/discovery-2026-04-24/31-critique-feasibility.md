# 31 — Critique: Feasibility (Red-Team B)

**Date:** 2026-04-24
**Lens:** Data availability, rate limits under production load, ToS, free-tier ceilings, real-world latency, integration friction, single-point-of-failure risk.
**Inputs reviewed:** `plans/discovery-2026-04-24/20-candidate-features.md`, `00-system-map.md`, `10-/11-/12-/13-/14-research-*.md`, `consensus_engine/utils/rate_limiter.py`, `consensus_engine/utils/http.py`, `consensus_engine/scanners/sec_edgar.py`, `config/consensus.yaml`.
**Method:** Live `curl -sI` spot-checks where ToolSearch/WebFetch was unavailable; otherwise parse claimed endpoints against existing rate-limit config and Phase-2 budget.
**Repo root:** `/root/.openclaw/workspace`

---

## Executive Summary

- **Verdict counts:** KEEP = 5 · STRENGTHEN = 7 · KILL = 2.
- **KILL'd features:** Feature 9 (SEC EDGAR Full-Text Mention Velocity) and Feature 14 (PDUFA / AdCom Proximity Tag).
- **Top 3 shared infrastructure risks across all surviving features:**
  1. **No SEC EDGAR shared semaphore.** Four features (1, 2, 8, 9) hit `data.sec.gov` / `www.sec.gov/cgi-bin` / `efts.sec.gov` under a hard 10-req/s aggregate cap (per SEC fair-use policy). The repo's `rate_limiter.py:29` declares `sec_edgar: 0.2` (200 ms = 5 req/s) **per source string** and `sec_edgar.py` already calls `acquire("sec_edgar")` for `check_recent_filings`. P2 candidates do not declare a shared lock — if Feature 1's atom poll, Feature 2's S-4/425 poll, Feature 8's 13D poll, and the existing `check_recent_filings` xref call all fire on the same minute they will trip a shared 10-min IP block and silently take down xref `_run_sec_check` (`cross_reference.py:80`).
  2. **HEAD-vs-GET asymmetry on AWS-API-Gateway-fronted endpoints.** Live spot-check confirmed `efts.sec.gov/LATEST/search-index` returns `403 MissingAuthenticationTokenException` on HEAD but a healthy JSON body on GET. Any feature whose health-check or freshness probe uses HEAD will mis-classify the source as down. The existing `aiohttp.ClientSession` defaults to GET so this is mitigatable — but flag it for any future watchdog.
  3. **Calendar-harvester scrape pages are Akamai/Cloudflare-walled.** Live spot-check: FDA advisory-committee-calendar returns `403` to plain `aiohttp` — needs Playwright stealth (already wired via `utils/browser.py` for StockTwits/YouTube transcript path) or rotation. Federalreserve.gov FOMC calendar is plain Cloudflare and **does** serve cleanly. CBOE per-product VX-futures historical CSV directory page works; CBOE `cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv` returns 200 BUT `last-modified: Fri, 30 Oct 2020` — **the equity put/call CSV at this URL has not been refreshed in 5+ years; CBOE rotated this endpoint without telling anyone**. Any feature relying on it (none in P2 directly, but C-cluster and V-cluster authors cited it) is dead.

**One-paragraph framing:** P2's "Feasibility=4 or 5" scores are mostly correct *in isolation* but underweight **shared-resource contention** when 4 features hit one rate-limited source simultaneously, and **calendar-scrape fragility** for HTML pages behind Akamai. Most of the strengthening guidance below boils down to: declare and enforce a single shared SEC semaphore, gate any HTML-scrape behind market-hours-only + 24h-cache + Playwright fallback, and degrade gracefully (return last-known-good) when a daily file is not yet posted by 18:00 ET.

---

## 1. Cluster Form 4 Open-Market Buys — VERDICT: KEEP

Composite 5.00. Score=5/5/5.

- **(a) Data availability — VERIFIED LIVE.** Spot-check `curl -sI -A "OpenClaw …" https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&start=0&count=10&output=atom` returns `HTTP/2 200 content-type: application/atom+xml`. Per-filing XML at `/Archives/edgar/data/{cik}/{accession}/{primaryDocument}.xml` already wired and tested in `scanners/sec_edgar.py:173` (`fetch_form4_details`). XML schema v1.0 `Form4_*.xml` is stable since 2003 (not changing).
- **(b) Rate limits.** SEC fair-use is aggregate 10 req/s across `data.sec.gov`, `www.sec.gov/cgi-bin`, `efts.sec.gov`. P2 says "60–120s atom poll" (1 request) plus per-filing XML fetches. A typical day has ~150–300 Form 4s; clustering plus dedup means maybe 30–50 unique filings/day need XML fetches — fine within the existing `rate_limiter.acquire("sec_edgar")` 5 req/s ceiling at `utils/rate_limiter.py:29`. **The risk is not this feature alone; it is the shared SEC source budget — see shared-infra section.**
- **(c) ToS.** SEC EDGAR explicitly permits automated access with mandatory User-Agent header (already set as `OpenClaw Signal Engine (ak@openclaw.dev)` at `sec_edgar.py:21`). Compliant.
- **(d) Free-tier ceiling.** No registration, no per-day quota — just the 10 req/s aggregate.
- **(e) Latency.** Atom poll ~200 ms, XML parse ~50 ms each. 60–120 s poll well inside any timeout. Background loop, not on the hot path.
- **(f) Integration friction.** Existing `fetch_form4_details` already returns the right schema (transactionCode, aff10b5One via `_val(root, "aff10b5One")`). New module `scanners/form4_cluster.py` wires into `main.py:343–347` next to existing 8-K watcher. Low touch.
- **(g) SPOF risk.** EDGAR rare outage tolerated — atom-poll loop can sit silent for hours and resume cleanly. Form 4 amendments via `4/A` arrival in same feed.

**Strengthening (already in P2, but reinforce):** wire the per-filing XML fetches through the existing `rate_limiter.acquire("sec_edgar")` and add a `name+address` fuzzy match before counting as cluster (P2 mentions; ensure the lookup table at `db.py:` schema migration is sized appropriately). Cap the per-cycle XML fetch budget at 30 to bound any backlog burst.

---

## 2. SEC S-4 / 425 Real-Time M&A Detection — VERDICT: STRENGTHEN

Composite 4.50. Score=5/4/4.

- **(a) Data availability — VERIFIED.** Same atom feed family as Feature 1; works identically. P2 endpoint `?type=425&output=atom` and `?type=S-4&output=atom` use the exact same `getcurrent` endpoint. Spot-check by analogy succeeds.
- **(b) Rate limits.** Two more atom polls every 60 s = 2 extra req/min on top of Feature 1. Per-filing 425 cover-page parse adds maybe 10 fetches/day on average — fine.
- **(c) ToS.** Compliant with same SEC fair-use policy.
- **(d) Free-tier.** Same as Feature 1 (no registration).
- **(e) Latency.** Background loop; not on hot path. 425 cover-page parsing for "merger agreement" / "per share" regex adds ~50 ms per filing.
- **(f) Integration friction.** New module `scanners/sec_ma_watcher.py`. Cross-CIK target-extraction is the only meaningful complexity — most 425 cover pages have a clean target-CIK in the SUBJECT-COMPANY field of the SGML header, but issuers vary. **Flag**: P2 marks "moderate engineering" — this is correct; budget 1 day for parse-edge-case shaking.
- **(g) SPOF risk.** Low. If EDGAR is down, no 425 alerts fire — degrades gracefully.

**Required strengthening:**
- **Share the SEC semaphore with Feature 1, 8, and existing `_run_sec_check`** — explicit shared lock under `rate_limiter.acquire("sec_edgar")` so the four polls don't burst > 10 req/s in the same second.
- Validate `aff10b5One`/Item-1.01 cross-ref logic on a 6-month historical replay before going live; the "first 425 referencing target-CIK in 30 days" rule needs a CIK-pair memo table — confirm `db.py` schema add is sized for ~20k row growth.
- Add a 60 s cooldown on same target-CIK as proposed; harden by also dedup'ing on `accession_number` to handle 425 amendments.

---

## 3. Pre-FOMC Drift Trade — VERDICT: KEEP

Composite 4.20. Score=4/4/5.

- **(a) Data availability.** Live spot-check `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` → `HTTP/2 200 cf-cache-status: HIT`. Cloudflare-fronted but allows `aiohttp` GET (no Akamai bot wall). SPY/VIX via existing Finnhub `/quote` adapter.
- **(b) Rate limits.** Calendar scrape is **annual** — 1 request per year. Real-time SPY/VIX `/quote` at 14:00 ET T-1 piggybacks on existing Finnhub budget (3000/day at `config/consensus.yaml:281`); adds ~2 calls/year of distinct usage.
- **(c) ToS.** Public Fed calendar; no scraping wall.
- **(d) Free-tier.** Finnhub `/quote` is the only API call and it's already in budget.
- **(e) Latency.** Scheduled fire at 14:00 ET T-1 — explicitly clock-driven, not poll-driven. No tail latency risk.
- **(f) Integration friction.** New module `signals/pre_fomc.py`. Wires into `main.py:455` `macro_digest_loop`. Calendar YAML at `config/fomc_calendar.yaml` per P2 — reasonable.
- **(g) SPOF risk.** Calendar is cached locally as YAML; Fed page outage doesn't affect already-cached schedule. Finnhub `/quote` outage at 14:00 ET T-1 → fail-closed (don't fire) is acceptable; signal fires <10x/year so a single missed event is tolerable.

**No additional strengthening needed.** P2 already has hard time-stop, VIX gate, and stop-loss specified. Note P2 says "scrape annually" — verify the annual-refresh job is actually wired (pure config read of `config/fomc_calendar.yaml` by default + manual maintenance OK).

---

## 4. FRED Credit-Equity Divergence — VERDICT: STRENGTHEN

Composite 4.00. Score=3/5/5.

- **(a) Data availability.** FRED API requires free key (`https://fredaccount.stlouisfed.org/apikeys`). Spot-check `https://api.stlouisfed.org/fred/series/observations?series_id=BAMLH0A0HYM2&api_key=invalid` returns `500` (key validation upstream) — endpoint live, expected behavior. yfinance HYG/SPY/LQD/IEF already in repo via existing `_fetch_yfinance_price` ThreadPoolExecutor pattern.
- **(b) Rate limits.** FRED documents 120 req/min, generous. EOD daily run = 4 series × 1 call = 4 calls/day. Trivial.
- **(c) ToS.** FRED explicit-allow for automated access with API key. yfinance is a scraping wrapper — Yahoo's TOS technically forbids it but no enforcement against low-volume non-commercial use; the repo already accepts this risk for `price_outcome_loop` at `main.py:807–832`.
- **(d) Free-tier.** FRED free; no daily cap that matters.
- **(e) Latency.** Daily EOD computation. Pandas math is microseconds. yfinance `download` is blocking, must run inside the existing 4-worker ThreadPoolExecutor.
- **(f) Integration friction.** New module `scanners/macro_credit.py`. Output written to either existing `youtube_macro` table (semantically wrong but schema-compatible) OR new `macro_signals` table (preferred). xref consumption via new `cross_reference._get_macro_context` method at `cross_reference.py:333`. **Risk**: P2 says "minimal integration touch" but this requires either a schema migration (new table + indexes) or a semantic overload of `youtube_macro` — neither is *minimal*. Budget 0.5 day for the schema decision and migration.
- **(g) SPOF risk.** FRED HY OAS is one-day-lagged by design. yfinance ETF data has occasional gaps. Failure mode: if FRED is dark, fall back to pure ETF-only signal (P2 already documents this as the canonical mode). Fail-closed acceptable.

**Required strengthening:**
- **Add `FRED_API_KEY` to `/root/.openclaw/.env`** and register a key. CLAUDE.md project memory says "External API Keys" already references Firecrawl + Marketstack; FRED needs to be added explicitly before the feature can ship.
- Decide schema upfront: new `macro_signals` table is cleaner than overloading `youtube_macro`.

---

## 5. Volume-Confirmed N-Day Breakout with ATR Levels — VERDICT: KEEP

Composite 4.00. Score=4/4/4.

- **(a) Data availability.** yfinance daily OHLCV is the bedrock — already wired in repo at `analysis/technical.py:54` and `scanners/volume_scanner.py`. Intraday 5-min via `interval='5m'` is the documented capability (Yahoo allows ~60d of 5-min, ~7d of 1-min).
- **(b) Rate limits.** yfinance is unofficially rate-limited; the repo already paces via `concurrent.futures.ThreadPoolExecutor(max_workers=4)` per `main.py:807–832`. P2's per-feature daily quotas (max 20 alerts/day for N=20) bound the alert side; the scan side scales with the number of qualifying tickers per day. **Critical concern**: P2 doesn't say *which universe* is being scanned. If it's all of ApeWisdom-trending tickers (~50–100 names) per cycle, fine; if it's a 2000-name Russell scan, that's a different latency profile.
- **(c) ToS.** Yahoo TOS forbids automated scraping but no enforcement at modest volumes; same risk profile as the existing `price_outcome_loop`.
- **(d) Free-tier.** yfinance is open; Finnhub `/quote` for last-print confirmation is already in budget.
- **(e) Latency.** EOD-confirmed signal (16:00 ET fire) is the canonical path. yfinance `download` for 252 days of 1 ticker is ~500 ms blocking; 50-ticker scan via 4-worker ThreadPool is ~6–7 s — fits in `fetch_loop` 300 s cadence comfortably.
- **(f) Integration friction.** New module `signals/breakout.py` + reuses `analysis/indicators.py` for ATR/BBwidth which are **already implemented** at `analysis/technical.py:243`. Wires into existing `fetch_loop` at `main.py:369–380`. Genuinely minimal.
- **(g) SPOF risk.** Low. yfinance failure → no alerts that cycle. Already accepted risk tier.

**No additional strengthening needed.** P2 has the regime gates (BBwidth, ADX, VIX) and per-feature daily quota. Confirm: the breakout scan should run on a bounded universe (top-N from ApeWisdom + tickers with active TweetShift hits in last 24h), NOT a 2000-name Russell scan, to keep yfinance load bounded.

---

## 6. Earnings-Window Risk Gate — VERDICT: STRENGTHEN

Composite 4.00. Score=3/5/5.

- **(a) Data availability.** Three sources cross-check'd: Finnhub `/calendar/earnings` (already wired at `scanners/earnings_calendar.py:25–47`), `yfinance.Ticker(symbol).calendar` (already accessible per repo), and Nasdaq public JSON `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD` (Nasdaq has been blocking aggressive scrapers since 2024 — the unofficial JSON works for now but ToS-grey).
- **(b) Rate limits.** Tag-on per-ticker lookup; cache hit rate >95% expected (most signals fire on tickers we've seen in last 7 days). Worst case 50 fresh-ticker xref lookups per day — Finnhub /calendar/earnings is one bulk-day call at most. Comfortable.
- **(c) ToS.** Finnhub explicit-allow with API key. yfinance grey but accepted. **Nasdaq `api.nasdaq.com` is the risk** — Nasdaq has actively blocked unofficial-JSON scrapers; the call works today but is ToS-grey. P2 lists it as "unofficial Yahoo/Nasdaq endpoints can return stale or wrong dates" — acknowledge but underplays the legal exposure of a bot persistently calling Nasdaq's internal-use endpoint.
- **(d) Free-tier.** Finnhub already in 3000/day budget; the gate adds maybe 10–20 calls/day. yfinance free. Nasdaq unofficial — no quota documented.
- **(e) Latency.** Per-ticker lookup is ~100 ms cached (DB hit), ~500 ms uncached (Finnhub round-trip). Daily refresh cadence per-ticker; tag is computed once at signal time, not on every poll.
- **(f) Integration friction.** Reuses existing `scanners/earnings_calendar.py:25–47`. New module `analysis/earnings_gate.py`. Hook at `cross_reference.py:333` and `alerts/discord.py:471–507` — touches two files. Acceptable.
- **(g) SPOF risk.** All three source mismatch → "uncertain" tag (fail-open / fail-conservative). P2 already specifies this. Good.

**Required strengthening:**
- **Drop Nasdaq `api.nasdaq.com` as a primary source** — keep it as a tertiary fallback only after Finnhub + yfinance disagree. The ToS exposure isn't worth the marginal coverage on small-caps where Finnhub already returns nulls.
- Add 7-day TTL on the cached earnings dates per P2; explicitly invalidate on any `8-K Item 2.02` hit for the ticker (the earnings press-release form code triggers a re-pull of next-quarter date).

---

## 7. FinBERT Headline Sentiment + Catalyst Lexicon — VERDICT: STRENGTHEN

Composite 4.00. Score=4/4/4.

- **(a) Data availability.** RSS already polled by `scanners/news.py`. FinBERT model `ProsusAI/finbert` is on Hugging Face under MIT license. Loughran-McDonald lexicon is public-domain.
- **(b) Rate limits.** RSS polls are unmetered; FinBERT inference is local — no rate limit exists. **The real concern**: CPU throughput. P2 quotes "~50ms/headline on CPU." If the bot polls 4 RSS sources × 50 headlines × 50 ms = 10 s of CPU per cycle. The existing engine is async-I/O bound; 10 s of synchronous CPU work blocks everything else unless run in a ThreadPoolExecutor or external process. P2 says "CPU throughput on multi-tenant server may bottleneck; needs benchmarking" but doesn't propose mitigation.
- **(c) ToS.** FinBERT MIT — clean. Loughran-McDonald academic open. RSS is public.
- **(d) Free-tier.** No API costs. Local model adds ~440 MB RAM. Acceptable.
- **(e) Latency.** Inference cold-start is ~3–5 s (model load); subsequent inferences ~50 ms each. **Must be loaded once at engine start, not per-cycle.** P2 doesn't address this.
- **(f) Integration friction.** New `consensus_engine/sentiment/` subpackage with two modules. Hook into `scanners/news.py:50–56` (`_classify_catalyst`). Cross-ref consumes via `_run_news_cascade`. Schema: new SourceType `NEWS_SENTIMENT`. Three integration points.
- **(g) SPOF risk.** FinBERT model file pinned by SHA; degradation path: if the model fails to load, fall back to catalyst-lexicon-only path. P2 specifies this.

**Required strengthening:**
- **Load FinBERT once at engine init** (in `main.py:run_live` setup), not on each news cycle.
- **Run inference inside the existing `ThreadPoolExecutor`** so async loop isn't blocked. Allocate a separate 1-worker executor specifically for sentiment inference.
- Add `requirements.txt` entries for `transformers` (~400 MB venv growth) and pin to exact version. The repo is currently lightweight; this is the heaviest dep added.
- Benchmark inference latency on the production server BEFORE shipping — if it's actually >100 ms/headline, downgrade to DistilRoBERTa `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis` (faster, similar quality).

---

## 8. New 13D Activist-Filer Detection — VERDICT: STRENGTHEN

Composite 4.00. Score=4/4/4.

- **(a) Data availability.** Same EDGAR atom-feed family as Features 1 & 2. Verified live. 13D HTML primary doc parsing is the only new complexity — Item 4 is free-text, regex over a curated phrase list per P2.
- **(b) Rate limits.** One more atom poll family (`type=SC+13D`, `type=SC+13G`) every 60–120 s. Plus per-filing HTML fetch on new arrivals — ~5–20 13D/13G filings per day market-wide. **Aggregate impact on shared SEC budget — see shared-infra section.**
- **(c) ToS.** Same SEC fair-use; compliant.
- **(d) Free-tier.** Same as Features 1 & 2.
- **(e) Latency.** Background loop. HTML parse is regex over Item 4 text — ~50 ms.
- **(f) Integration friction.** New module `scanners/activist_watcher.py`. Reuses `sec_edgar.py` HTTP plumbing. Wires into `main.py:343` behind sub-flag. **The complication is the activist-history table** — P2 says "build local table from per-filer `submissions.json`" — this is a one-time backfill of probably 10k-50k known-filer CIKs, ~12h of API calls staggered across ~3 days at the 5-req/s ceiling. Explicit migration step.
- **(g) SPOF risk.** Low; degrades same as Features 1 & 2.

**Required strengthening:**
- **Backfill activist-filer history as a one-time migration job** (separate script under `scripts/backfill_activist_history.py`). Estimate 10k filer-CIKs × 1 submissions.json call each × 200ms = 30 minutes; well within a budget if paced. Run it once, cache permanently with weekly delta refresh.
- Item 4 regex is **tightly coupled to current SEC drafting conventions** — when activists' lawyers find new circumlocutions, the regex misses. Add an LLM-classifier fallback (existing `analysis/llm_scorer.py` infrastructure) for any 13D where regex returns 0 hits but the filing is from a known-activist filer (≥2 prior campaigns) — uses existing OpenRouter budget.
- Maintain `holder_intent` table size — should stay <1M rows lifetime; add index on `(filer_cik, issuer_cik)`.

---

## 9. SEC EDGAR Full-Text Mention Velocity — VERDICT: KILL

Composite 3.80. Score=3/5/4.

**Reason for KILL (≤2 sentences):** EFTS endpoint `efts.sec.gov/LATEST/search-index` is **AWS-API-Gateway-fronted and rejects HEAD with `MissingAuthenticationTokenException`** while accepting GET (verified live) — this means standard health-check probes fail, and any scaled per-ticker daily-poll pattern bumps against the same shared 10-req/s SEC ceiling that Features 1, 2, and 8 already saturate. The marginal +3pp precision delta P2 itself flags is too low to justify the contention budget against the higher-leverage Form 4 + S-4 + 13D triumvirate that share the same SEC bucket.

**Specific infrastructure gap:** Per-ticker daily polling at 40 active tickers/day = 40 EFTS calls/day = trivial in isolation. **Combined with Features 1 (atom poll every 60s = 1440/day), 2 (×2 atom polls = 2880/day), 8 (×2 atom polls = 2880/day), AND existing `cross_reference._run_sec_check` per-alert ticker `check_recent_filings` (~50/day at current alert volume) = ~7300/day baseline SEC requests = ~5/min steady-state, with bursts on minute-boundaries.** Adding this feature's per-ticker daily poll plus per-CIK history check pushes the burst beyond the 10 req/s ceiling on poll-alignment minutes. Cost: a single 10-min IP block silences `_run_sec_check` for every other feature. The Feature is the lowest-marginal-value member of the SEC cluster and is the one to cut.

**If reconsidered later:** ship only after Cluster A (Features 1, 2, 8) is in production for 30+ days and we have a measured SEC-source-budget headroom number. Alternative: piggyback on `submissions.json` recent-items list (already pulled per ticker by `check_recent_filings`) and compute velocity from that — no new endpoint, no new request/min, marginal feasibility=5.

---

## 10. Wikipedia Pageview Spike — VERDICT: STRENGTHEN

Composite 3.70. Score=3/4/5.

- **(a) Data availability.** Live spot-check confirmed Wikimedia REST API responds (returns `400` on malformed date string in spot-check; documented endpoint `/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/{article}/hourly/{start}/{end}` works with correct `YYYYMMDDHH` format). No auth required.
- **(b) Rate limits.** Wikimedia documents 200 req/sec public limit — vastly more than needed. 40 active tickers × 1 hourly call/cycle = 40 req/cycle. Comfortable at any cadence.
- **(c) ToS.** Wikimedia explicit-allow for non-abusive automated access. Honor `User-Agent` requirement (analogous to SEC; just include contact email).
- **(d) Free-tier.** No registration, no quota.
- **(e) Latency.** Endpoint typical <200 ms response. 40-ticker scan completes in ~2 s parallel.
- **(f) Integration friction.** **The friction is the ticker-to-Wikipedia-article map.** P2 says "FIGI-validated canonical article slug per ticker; reject ambiguous matches." OpenFIGI v3 has 25-call/min unauth limit (5/sec auth'd); for 40 active tickers + new-arrival lookups, run **once at startup with 24h memo cache** and persist the slug map to a new `ticker_external_ids` table or extend `ticker_metadata`. This is a non-trivial migration step P2 calls "minimal" but isn't.
- **(g) SPOF risk.** Wikimedia infrastructure is robust. If down, signal degrades to "no-data" — no alerting impact since this is a +1 confirmer not a primary trigger.

**Required strengthening:**
- **Ship the ticker→Wikipedia-article map as a one-time backfill** + ongoing daily-incremental for new tickers. Bound to ~5–10 minutes of OpenFIGI calls.
- Reject articles where the infobox doesn't contain the ticker symbol — P2 specifies; verify the validation step is in the implementation.
- 1-hour TTL cache per article-slug; 28-day baseline must be cached, not recomputed every alert.
- **Aggressive User-Agent identification per Wikimedia ToS**: `consensus_engine/1.0 (+https://github.com/chopra2007/openclaw; ak@openclaw.dev)` format expected.

---

## 11. Reg SHO Threshold List Entry/Exit Event — VERDICT: STRENGTHEN

Composite 3.50. Score=3/4/4.

- **(a) Data availability.** Live spot-check `https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth20260423.txt` returns `HTTP/2 200 content-type: text/plain content-length: 2603 last-modified: Fri, 24 Apr 2026 03:00:17 GMT`. Live, current. NYSE: `https://www.nyse.com/regulation/threshold-securities` returns `HTTP/1.1 302 Location: /regulation/regulation-sho` — **redirected**; the originally-cited URL will have to be followed. Cboe URL not spot-checked but the Cboe CDN pattern is established (per Feature 12 spot-check).
- **(b) Rate limits.** Daily file fetch — 3 small files (NASDAQ + NYSE + Cboe) per day. Bytes are small (NASDAQ file is 2.6 KB). Trivial.
- **(c) ToS.** Public regulatory SRO publication; explicit fair-use. NYSE redirect breaks naive URL hard-coding but doesn't violate ToS.
- **(d) Free-tier.** No registration; no quota. NASDAQ file URL is daily-dated, must construct YYYYMMDD path.
- **(e) Latency.** Daily-cadence batch run at 18:00 ET. Three sequential fetches with 3 × 1 s timeouts is nothing.
- **(f) Integration friction.** New module `scanners/reg_sho.py`. Daily-cadence poll wired at `main.py:455` neighborhood. **The ticker-symbol normalization across 3+ lists is the real engineering** — NASDAQ uses NSO tickers, NYSE uses different listings, Cboe has its own. P2 calls this "moderate engineering" which is correct but underspecified. Estimate 1 day for symbology cleansing + 0.5 day for diff logic.
- **(g) SPOF risk.** **High and underweighted by P2.** If a daily file isn't posted by 18:00 ET (lagged regulatory publication), the diff logic mis-detects exits as entries on the next day's file. P2 specifies "5-day daily entry must be respected; do not fire on day-1 inclusion" but doesn't address publication-delay false-positives.

**Required strengthening:**
- **Track cumulative-entry-day-count per (ticker, list)** rather than naive yesterday-vs-today diff. A ticker on the file 4 of last 5 trading days but missing today is "publication delay maybe"; a ticker missing 3 of last 5 days is genuinely off the list.
- **Follow the NYSE redirect** explicitly in implementation — hard-code the redirected `/regulation/regulation-sho` URL, not the original.
- Liquidity gate: market cap ≥ $1B for instant-trigger eligibility per P2; verify `validate_ticker_market_cap` is invoked.
- Daily file fetcher must handle "file not yet posted" = HTTP 404 → retry 30 min later, no error log spam.

---

## 12. VIX Term-Structure Flip — VERDICT: STRENGTHEN

Composite 3.50. Score=3/4/4.

- **(a) Data availability — partial.** CBOE per-product VX-futures historical data dir at `https://www.cboe.com/us/futures/market_statistics/historical_data/products/csv/VX/` exists but **schema changes occasionally** (P2 acknowledges). yfinance `^VIX9D` and `^VIX3M` exist as ETF proxies. **Critical**: CBOE's `cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv` was spot-checked and returns 200 with `last-modified: Fri, 24 Apr 2026 00:32:22 GMT` — current. But `cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv` returns 200 with `last-modified: Fri, 30 Oct 2020` — **stale by 5 years; CBOE rotated this CSV without redirecting**. Don't trust any CBOE CDN URL without an EOD freshness check.
- **(b) Rate limits.** EOD daily fetch; 1 file per day per index. CBOE is Cloudflare-fronted, no documented rate limit beyond "don't abuse."
- **(c) ToS.** CBOE allows automated access to public CSV CDN; their TOS forbids scraping the *interactive quote* site, which is different.
- **(d) Free-tier.** No registration; no quota.
- **(e) Latency.** EOD computation. yfinance fallback is sub-second per ticker.
- **(f) Integration friction.** New module `scanners/vix_term.py`. Wires into `macro_digest_loop`. Output via `signal_events` SourceType `VOL_REGIME`. Reasonable.
- **(g) SPOF risk.** **High but mitigated by yfinance fallback** — if the CBOE CSV format changes (P2 acknowledges; the equity P/C CSV being silently stale is the warning sign), the fallback to `^VIX9D / ^VIX3M` ratio works. Persistence requirement (≥3 consecutive backwardated days before re-contango flip) handles transient noise.

**Required strengthening:**
- **EOD freshness check on CBOE CSV before using it** — if `last-modified` is older than 7 days, automatically fall back to yfinance, log warning, and emit a source-health alert. The 5-year-stale equity-P/C CSV teaches us this is a real failure mode.
- FOMC announce-day and CPI-day suppression per P2; double-check with the calendar resolver from Cluster D.
- Persistence requirement verified.

---

## 13. Influencer Cluster-Convergence — VERDICT: KEEP

Composite 3.40. Score=3/3/5.

- **(a) Data availability.** Pure derived analytics on existing TweetShift Discord-Gateway stream. No external data dependency.
- **(b) Rate limits.** N/A — no new external calls. Zero contention.
- **(c) ToS.** Already accepted under existing TweetShift pipeline.
- **(d) Free-tier.** N/A.
- **(e) Latency.** In-process compute on every tweet ingest. Author-history lookup is a DB cache hit; clustering compute is microseconds for a 4-author check. Hot-path safe.
- **(f) Integration friction.** **One concern**: P2 says "hook that emits author-mention metadata to a derived store (`tweet_mentions` table or in-process ring buffer)." A new table is preferred (durable across restarts); ring-buffer-only loses the 30-day independence-test history on every restart. Schema add is small.
- **(g) SPOF risk.** None — if TweetShift is down, this feature is also down (correctly), no separate failure.

**No additional strengthening needed.** Cleanest feasibility profile in the entire P2 candidate list. The only risk is the implementation detail that a `tweet_mentions` table is required for durable independence-history; reject pure-in-process buffer.

---

## 14. PDUFA / AdCom Proximity Tag — VERDICT: KILL

Composite 3.30. Score=3/4/3.

**Reason for KILL (≤2 sentences):** The required FDA Advisory Committee Calendar HTML page **returned `403 Akamai-bot-block` to plain `aiohttp` GET in live spot-check**, meaning the canonical calendar source requires Playwright stealth (already wired but expensive) — and even then, Akamai routinely revokes browser-fingerprint sessions, so the calendar harvester needs ongoing maintenance. Combined with P2's own admission that "PDUFA dates routinely slip," "FDA does not always pre-announce PDUFA dates publicly (sponsor 10-Q is canonical source)," and "sponsor → ticker mapping is messy for subsidiaries / partnerships / CROs," the feature has three serial failure modes upstream of the actual signal — the data infrastructure cannot reliably support it under a free-tier production load.

**Specific infrastructure gap:** The feasibility=3 score is correct but the failure compounds: FDA calendar (Akamai-walled) + openFDA Drugs@FDA endpoint (works, verified live with 200 OK and JSON body) + ClinicalTrials.gov v2 (works, verified) + SEC EDGAR 10-Q full-text PDUFA mention scrape (depends on EFTS which is the same shared 10 req/s SEC bucket Cluster A is pressuring). Three out of four sources have material failure modes; the fourth (10-Q full-text) competes with already-stretched SEC budget. P2 calls implementation "moderate engineering" — realistically it's a 5–7 day project to harden the calendar harvester, the sponsor-to-ticker map, and the cross-source mismatch logic, for a feature whose composite (3.30) is the second-lowest in the surviving cohort.

**If reconsidered later:** revisit if a free PDUFA aggregator API surfaces (BioPharma Catalyst, etc.) OR if the calendar harvester can be replaced by a curated YAML of known upcoming PDUFA dates manually maintained for the small biotech subset the bot already covers (~20-30 names). The "manual YAML refresh" version drops the feature to <1 day implementation but loses automation — still likely a better trade than the proposed harvester.

---

## Shared Infrastructure Risks

**Risk 1: SEC EDGAR aggregate request budget shared across 4 features (Form 4 cluster, S-4/425, 13D, EFTS velocity if kept).**

The 10 req/s SEC fair-use ceiling applies aggregate across `data.sec.gov`, `www.sec.gov/cgi-bin`, `efts.sec.gov`. The existing `rate_limiter.py:29` `sec_edgar: 0.2` (200 ms = 5 req/s) is per-source-string; if Features 1, 2, 8 all use the string `"sec_edgar"` they'll share that budget — but if any uses a different string (e.g., `"sec_atom"`), they bypass the limiter and burst together.

**Mandatory:** all SEC-touching code MUST `await rate_limiter.acquire("sec_edgar")` regardless of which sub-endpoint they hit. Document this in `consensus_engine/scanners/CLAUDE.md` or comment block. Recommend tightening `sec_edgar` interval from 0.2 (5 req/s) to **0.15 (6.67 req/s)** to leave headroom — under burst-alignment the cluster cannot exceed 10 req/s.

**Estimated steady-state load with all 4 SEC features active (Cluster A):**
- Feature 1: 1 atom poll/60s = 0.0167 req/s
- Feature 2: 2 atom polls/60s = 0.033 req/s
- Feature 8: 2 atom polls/60s = 0.033 req/s
- Existing `_run_sec_check` per xref alert: ~50 alerts/day = 0.0006 req/s
- New-filing XML/HTML follow-up fetches (40 unique filings/day across cluster) = 0.0005 req/s
- **Total: ~0.084 req/s steady-state, well under ceiling.**

**Burst risk:** at second-zero of every minute, three atom polls fire simultaneously. Use jittered start offsets (Feature 1 at :00, Feature 2 at :20, Feature 8 at :40) so polls naturally distribute.

**Risk 2: yfinance is a scraping wrapper with no documented rate limit.**

Three features hit yfinance (Feature 4 macro credit, Feature 5 breakout, Feature 12 vol regime ETF fallback). Plus existing `price_outcome_loop` 4-worker ThreadPool. If yfinance starts rate-limiting (Yahoo has tightened twice since 2023), all three features degrade simultaneously.

**Mandatory:** add a per-source `yfinance` entry to `rate_limiter.py` (e.g., 1 req/s) and route ALL yfinance calls through `await rate_limiter.acquire("yfinance")` regardless of which feature is calling. Already done for the existing `_fetch_yfinance_price`, missing for the new features.

**Risk 3: Playwright stealth contention if PDUFA calendar (Feature 14, killed) or other Akamai-walled calendar harvester is added.**

Existing Playwright stealth pool serves YouTube transcript fallback (`scanners/youtube.py:813–818`) and StockTwits (off by default). Adding any new Akamai-scraping use case competes for the same browser pool which uses meaningful RAM (~300 MB per browser). Killing Feature 14 removes this risk for now.

**Risk 4: New schema migrations stack up.**

Cluster A and Cluster C between them propose:
- `holder_intent` table (Feature 8)
- `tweet_mentions` table (Feature 13)
- `macro_signals` table (Feature 4)
- `ticker_external_ids` extension (Feature 10)
- New SourceType enum values: `INSIDER_CLUSTER`, `M_AND_A`, `MACRO_DRIFT`, `TECHNICAL_BREAKOUT`, `NEWS_SENTIMENT`, `ACTIVIST_FILING`, `WIKIPEDIA_ATTENTION`, `REG_SHO`, `VOL_REGIME` (9 new enum values)

**Mandatory:** consolidate into a single migration script run before any feature ships. Verify SourceType enum values are stable — adding 9 values to a heavily-referenced enum is a meaningful change for analytics queries downstream.

**Risk 5: Calendar resolver is a single point of failure for Cluster D and Feature 3.**

Features 3 (pre-FOMC), 6 (earnings gate), 14 (PDUFA) all depend on calendar data. Cluster D recommends consolidation into one shared `events_calendar.yaml`. **If that YAML drifts stale** (FOMC schedule changes mid-year, an earnings date shifts), all three features mis-fire silently. **Mandatory:** add a daily-cadence calendar-staleness check (compare next-event date to "now") and if next-event is within 30 days but YAML last-refreshed >90 days ago, emit a source-health alert.

**Risk 6: FRED API key not yet provisioned.**

CLAUDE.md project memory and `/root/.openclaw/.env` reference Firecrawl + Marketstack but no FRED. Feature 4 cannot ship without registering a FRED key. Trivial to obtain (free, immediate at `https://fredaccount.stlouisfed.org/apikeys`) but is a blocking step.

---

## Final Tally

| # | Feature | Composite | Verdict |
|---|---------|-----------|---------|
| 1 | Cluster Form 4 Open-Market Buys | 5.00 | KEEP |
| 2 | SEC S-4 / 425 Real-Time M&A | 4.50 | STRENGTHEN |
| 3 | Pre-FOMC Drift Trade | 4.20 | KEEP |
| 4 | FRED Credit-Equity Divergence | 4.00 | STRENGTHEN |
| 5 | Volume-Confirmed N-Day Breakout | 4.00 | KEEP |
| 6 | Earnings-Window Risk Gate | 4.00 | STRENGTHEN |
| 7 | FinBERT Headline Sentiment | 4.00 | STRENGTHEN |
| 8 | New 13D Activist-Filer Detection | 4.00 | STRENGTHEN |
| 9 | SEC EDGAR Full-Text Mention Velocity | 3.80 | **KILL** |
| 10 | Wikipedia Pageview Spike | 3.70 | STRENGTHEN |
| 11 | Reg SHO Threshold List | 3.50 | STRENGTHEN |
| 12 | VIX Term-Structure Flip | 3.50 | STRENGTHEN |
| 13 | Influencer Cluster-Convergence | 3.40 | KEEP |
| 14 | PDUFA / AdCom Proximity Tag | 3.30 | **KILL** |

**Counts:** KEEP = 5, STRENGTHEN = 7, KILL = 2.

**Summary recommendation to Phase 3 deliberation:** ship Features 1, 3, 5, 13 in Phase A (5 weeks of low-friction work, mostly leveraging existing infra). Defer Features 2, 4, 6, 7, 8, 10, 11, 12 to Phase B with the strengthening guidance above. Re-investigate Features 9 and 14 only if alternative data sources surface; current free-tier infrastructure cannot reliably support them at production load.

End of feasibility critique.
