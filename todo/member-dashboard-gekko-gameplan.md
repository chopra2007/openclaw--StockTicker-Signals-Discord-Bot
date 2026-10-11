# Market Edge dashboard: Gekko-quality gameplan (DRAFT for Codex review)

Written 2026-10-10 Pacific by Claude (Opus 5.5) on the Hetzner VPS. **Planning only.** No code, deploys,
data purchases or production changes are approved. Implementation waits until (1) Codex reviews this
plan, (2) the plan is revised, and (3) the owner approves the revised version.

Every claim below is labelled:
- **[V] Verified** this session (command or file read on this server, 2026-10-10).
- **[A] Audit**: taken from the Gekko audit package and not re-checked here.
- **[As] Assumption**: believed true but not yet proven; each has a named check.
- **[D] Owner decision** needed (collected in Section 9).

---

## 1. Context a reviewer needs

**Goal (owner's words, condensed).** Bring Market Edge's design, features and user experience up to or
beyond Gekko (gekko.app). The owner likes Gekko's dense Home and Charts screens (lots of good information,
interactive visuals, clear layout without clutter), and also its Ideas board, Smart Money pages, chart
signal markers, trend-coloured candles and the GekkoIndex idea. Good design and solid implementation come
first. Signal accuracy can improve over time. Proof that our signals predict better is NOT required before
useful product work. Do not assume Gekko's accuracy is proven, and never promise copies of Gekko's
proprietary formulas.

**What Market Edge is [V].** An invitation-only member website at https://akash.ignorelist.com, built on
top of the owner's Discord stock-alert bot.
- Frontend: Next.js 16 / React 19 in `web/member-dashboard/` (about 2,400 dense lines). Charts are
  hand-drawn inline SVG. There is no chart library.
- Backend: Python API plus a background worker in `member_dashboard/`. The site has its own SQLite
  database (14 migrations). It reads the bot's database `consensus.db` only through a per-source
  permission list (`FeedSource` in `member_dashboard/contracts.py`).
- The deployed copy is `/opt/member-dashboard/current`. Its content matches the workspace; the only
  difference is line endings.
- Look: dark only, "Gekko meets iOS", black page, one card colour, monospaced numbers. The owner approved
  this on 2026-10-07.

**Audit package [V].** `/opt/research/gekko-audit-2026-10-10/` contains:
- `START-HERE-VPS.md` and `gekko-next-session-handoff.md`
- `gekko-competitive-audit.md`: feature inventory and feasibility
- `gekko-output-quality.md`: tests of Ideas and Smart Money output
- `gekko-index-signals-comparison.md`: GekkoIndex, signal markers, same-stock plan comparison
- JSON evidence and screenshots (`gekko-home-quality.jpg`, `gekko-chart-desktop.jpg` and `gekko-smci-signals.jpg` are the design benchmarks)

**Standing owner rules that shape this plan [V], from project memory and CLAUDE.md.**
- **Free data only for the dashboard** (owner, 2026-10-06): "I don't want to go down the rabbit hole of
  subscribing or paying for data." So paid-data items in this plan are listed as "not possible free".
  They are not offered as purchases. Today's request says "leave paid-data dependencies until later",
  which fits this rule. Whether to ever reopen paid data is decision D2.
- All times shown to users are Pacific. Never show Eastern time.
- Dashboard money and safety caps stay on: a $3/day AI spend cap, and a 15 calls/minute share of the
  Schwab login (the bot uses the same login).
- Before any shipped feature counts as done, its real live output must be checked in a browser, at the
  real time it runs.

**Server capacity [V].** 4 CPU cores, 7.6 GB RAM (5.1 GB available), 20 GB free disk (73% used). The
dashboard has an on/off switch to save memory. This is enough for Phases 1–2 as scoped below. Phase 3
history expansion needs its own capacity check.

---

## 2. What already exists (verified inventory)

### 2.1 Screens and features [V], from source reads

| Screen | What it does today | Gap against the Gekko benchmark |
|---|---|---|
| **Overview** (`src/app/page.tsx`) | Strip of 5 index tiles (S&P 500, Nasdaq, Dow, Russell 2000, VIX); Alerts / Setups / Analyst-calls lists shown **one tab at a time**; side column with a track-record gauge and a mini watchlist | Shows one list at a time, so it is sparse. No index chart, heatmap, sector or theme movers, smart-money feed, market news or market brief |
| **Ticker report** (`ticker-report.tsx`, `price-chart.tsx`) | Price, day change, after-hours price, key stats; **line/area chart** with 1D/5D/1M/6M/1Y ranges, entry-zone band, stop and target lines, drag-to-read; then analysis, trade plan with reasons, risks, SEC filings (Form 4 buy/sell labels, real 8-K summaries), options activity, daily and weekly expected move, ticker chat | No candles, volume, moving averages, zoom/pan, weekly bars, event markers, or sizing panel. Single long column instead of a 3-panel workspace |
| **Screener** | Screens the newest ~30 symbols per signal source from the last 7 days [A]. Explained matches, column picker, up to 20 saved screens kept in the browser only | Not market-wide (Gekko: 5,623 symbols [A]). Saved screens don't follow the member to another device |
| **Watchlist** | One list, up to 50 tickers per member, live quotes | No named or automatic lists |
| **Track record** (`/record`) | Bot alerts since 2026-10-04 graded 1h/1d/5d against the S&P. Percentages hidden below 20 graded alerts | Good honesty discipline. Keep it |
| **Assistant / History / Admin** | Market chat with live data, saved reports and chats, invitations | Gekko has no research chat [A], so this is a differentiator |

### 2.2 Data and historical coverage [V]

**Important finding (not in the audits): each ticker report already downloads 1 year of daily
open/high/low/close/volume bars from Schwab, then throws away everything except the close before
sending the chart.** See `analysis_collector.py` lines 223 and 348–349. So candles and volume need no new
data source and no extra Schwab calls. The contract caps the series at 400 points; that cap must be
raised for 5 years (about 1,260 points).

| Data | Where | Coverage | Fit for |
|---|---|---|---|
| Daily price bars (OHLCV) | Schwab `/pricehistory`, fetched live per report | Decades for ordinary stocks (NVDA from 1999). Split-adjusted, not dividend-adjusted | Candles, volume, moving averages, 5Y/weekly, trend colours, patterns, seasonality |
| 15-minute bars | Schwab, live | About 41 calendar days rolling; nothing stored | 1D/5D charts |
| Live quotes | Schwab `/quotes`, one 100-symbol call per minute (5 indexes, then watched tickers, then recent alert tickers) | Live only | Strip, watchlist, heatmap (room to add about 16 ETFs) |
| Stored ETF daily bars | `data/market_store/` (20 benchmark, sector and factor ETFs) | Back to 2012 | Home index chart, sector heatmap, spreads |
| Stored daily bars, 539 symbols | `data/mmhl_daily/` | Varies. **Known traps:** fake $0.0001 rows, a `_meta.json` file, 24 funds mixed in | Research only; don't use for display without cleaning |
| Bot alerts | `alert_history`: 8,764 rows, 1,194 tickers | 2026-03-27 → now | Chart markers, Ideas evidence, track record |
| Group (#alerts) alerts | `swarm_alerts`: 77 rows | 2026-10 → now | Chart markers, Home feed |
| Analyst calls | `analyst_post_views`: 3,241 rows, 650 tickers | 2026-08-17 → now | Chart markers, Ideas evidence |
| Unusual options | `options_flow`: 270,597 rows, 483 tickers, with bid/ask-inferred side | 2026-06-01 → now | Chart markers, Smart Money options page |
| Daily options summary | `schwab_options_snapshots`: 1,567 tickers (put/call ratios, max pain, open interest, IV) | 2026-07-01 → now, after the close | Options panel, positioning inputs |
| Implied volatility | `iv_snapshots`: 472 tickers | 2026-06-29 → now | Expected-move history |
| FINRA daily short-sale volume (off-exchange) | `finra_short_volume`: 3,035 tickers | 2026-05-11 → 2026-10-08, daily | Positioning input for our own timing score (with careful labelling) |
| FINRA short interest | `finra_short_interest`: 2,285 tickers | 2026-03 → 2026-09, twice a month | Key stats, Smart Money |
| Planned insider sales (Form 144) | `form144_filings`: 194 tickers | 2026-07-02 → now | Insider page and markers |
| Form 4 insider trades | Fetched live from SEC per report, with buy/sell classification | On demand, 90 days | Chart markers on the report. A central feed needs a pipeline (Phase 2) |
| Congress trades | `congress_trades`: 108 rows, 41 tickers | **Stale** (newest about May 2026) | Not usable without a new pipeline |
| Market context | `sector_rs_daily`, `factor_rs_daily`, `market_breadth_daily`, `trend_daily`, `regime_daily` | June 2026 → now (regime from 2025-06) | Home rotation, breadth and regime panels |
| Security list | `ticker_metadata`: 5,581 tickers (name, market cap, exchange); `ticker_sector_cache`: 905 | Current | Seed for a broader universe and sector filters |
| Free whole-market history | DoltHub `post-no-preference/stocks` (daily bars, including delisted firms) and `/options` (weekly end-of-day chains, ~610 symbols, 2019+) | Free web queries. **Local clones were removed** (offloaded) | Phase 2–3 backfills |

### 2.3 Subscriptions and paid datasets [V]

- **Schwab Trader API**: free with the owner's brokerage account. This is the main market-data source.
  It is shared with the bot, the token needs a weekly manual re-login, and **whether Schwab's
  individual-developer terms allow showing its numbers to members is unresolved** (recorded in
  `todo/member-dashboard-design-review.md`). See decision D1.
- **Databento**: prepaid credit with about **$112.55 left** of $125. Historical options minute quotes.
  Used for research, not member display. Display licensing unknown. Not planned for dashboard use.
- **Finnhub free tier**: quotes only. Earnings estimates, analyst upgrades, transcripts and sentiment all return 403.
- **Free**: yfinance, SEC EDGAR, FINRA files, Google/Bing News feeds, DoltHub, self-hosted SearXNG.
- **Search/scrape keys**: SerpAPI keys 1–2, Firecrawl. Marketstack free tier (100 calls/month).
- **AI**: dashboard capped at $3/day.
- **No paid equity data subscription exists.** There is no source for analyst ratings history, consensus
  estimates, website traffic, or broad historical options flow.

### 2.4 Work underway that this plan must account for [V]

1. **Live but uncommitted changes.** The feed concurrency repair, 2028 market calendar and normal member
   limits (all 2026-10-10) are deployed, but still uncommitted in the workspace (11 modified files). Local
   `master` is also 2 commits behind GitHub. These must be committed and synced before any new branch,
   or the work collides.
2. **Open TODO #121 follow-ups:** worker network allowlist (egress), and a backlog of 17 failing browser
   tests. New chart and Home work will add browser tests, so the backlog makes regressions hard to see.
3. **Two builders.** Codex on the owner's Windows PC (reaching this server over `ssh Hetzner`) has done
   most dashboard work. Claude works here. Both must not edit the same files at once (decision D6).
4. **Line endings.** Workspace files use Windows line endings (CRLF), which inflates diffs (the raw
   diff shows 5,880 changed lines, about 300 real). Fix this before the next large change.
5. **Outdated memory corrected:** "testing phase, all member throttles lifted" is no longer true. Normal
   limits were restored on 2026-10-10.
6. **Uncommitted bot options-flow edits** (`consensus_engine/scanners/options.py`, about 50 real lines)
   touch the `options_flow` table that Smart Money would read. Their status must be known first.

### 2.5 Audit findings re-checked or updated

| Audit claim | Status |
|---|---|
| Chart is custom line/area, 1D–1Y, plan lines | **Confirmed [V]**, plus the new finding that OHLCV is already fetched and discarded |
| Market Edge lacks market-wide coverage | **Confirmed, with nuance [V]**: 5,581-ticker security list, 3,035-ticker FINRA data and 1,567-ticker options snapshots already exist. Price history is per request, not stored |
| Existing trade plans come from `trade_map.py` (levels, ATR, swings, volume profile, options walls) | Not re-read; consistent with `analysis_collector.py` calls [V] |
| Some first targets pay less than the stop risks (HOOD 0.51, BURL 0.81, NVDA 0.66) | [A]. Treated as a real display problem in R1 |
| Screener = 30 symbols per source per 7 days | [A], not re-checked |
| Member UI never tested signed-in by the audit | Still true. This plan's acceptance checks require signed-in browser checks |

---

## 3. Design principles (apply to every phase)

1. **Dense desktop, focused phone.** At ≥1280 px wide, use a 3-column workspace: left 280 px, middle
   flexible, right 320 px. Compact rows of 28–32 px, 13 px data text, monospaced numbers, small
   upper-case panel headings like Gekko's. Panels collapse. On phones, one column holds the same blocks
   in priority order; side panels become tabs under the chart. Never a shrunken desktop.
2. **One ticker context everywhere.** Clicking any ticker in Overview, Ideas, Smart Money, Screener or
   Watchlist opens the same chart workspace, carrying the plan or event that was clicked.
3. **One plan record.** The card, chart lines, sizing panel and outcome state all read the same saved
   plan version. A member's edits in the sizing panel are a private "my copy". They never rewrite the
   published plan. This fixes the TEAM/AMGN mismatch the audit found in Gekko.
4. **Every number has a time and a source.** Each Home block shows "updated 1:05 PM". Each chart marker's
   tooltip shows what happened, the event date, **when we knew it** (filed or detected time), and a
   source link.
5. **Labels are honest.**
   - Options flow is "inferred from volume, open interest and bid/ask", never "confirmed buying".
   - FINRA short volume is "off-exchange short-sale volume", never "institutional buying".
   - Price-based signals that share inputs are grouped as one family, so a cluster never looks like
     independent confirmation.
   - Rates appear only with their sample count, and percentages are hidden below 20 samples (the
     existing track-record rule).
6. **Marker grammar.** Shape + colour + layer name, and a legend with toggles. Bullish markers go below
   bars, bearish above. The family is never shown by shape alone.

---

## 4. Phase 1: design and workflow wins using existing data

**User benefit.** The site feels like a professional research terminal. Members find an opportunity,
see its evidence on a real candle chart, size the trade, and follow it, all without retyping a ticker or
price. No new data sources are needed.

### R1 (recommended FIRST release): "Chart workspace"

**Deliverables.**
1. Candle chart with volume bars, using the OHLCV the report already fetches. Ranges 1M / 3M / 6M / 1Y / 5Y
   (change the Schwab request from `period='1y'` to `'5y'`, which is still one call). Daily/Weekly switch
   (weekly bars built from daily). Crosshair readout of open/high/low/close/volume and date. Zoom and pan.
   Log/linear scale. Up to 3 moving averages (20/50/200 by default, editable). Keep 1D/5D from the
   existing 15-minute bars.
2. Plan overlay: entry-zone band, stop line, T1–T3 lines, **each target labelled with its own reward/risk**
   (for example "T1 112.84 · 0.5R"). A visible warning when T1 pays less than the risk: "Target 1 is a
   nearby obstacle / partial exit, not a full trade target." Display only; no change to how plans are
   generated (see D5).
3. Event markers from stored data, each a toggle layer with a legend:
   - bot alerts (`alert_history`)
   - group alerts (`swarm_alerts`)
   - analyst calls (`analyst_post_views`)
   - unusual options (`options_flow`, blue = bullish, gold = bearish, labelled "inferred")
   - insider open-market buys/sells (from the Form 4 data the report already fetches)
   - next earnings date
   Clustered markers on one bar merge into one marker with a count and a list.
4. 3-panel desktop layout on the ticker page:
   - left: plan and sizing panel (account size and % risk, giving shares, $ at risk and $ per target; editable private copy; "reset to published")
   - middle: chart
   - right: key stats, compact watchlist, latest news
   The existing analysis, risks, SEC, options and expected-move sections move below the chart as compact
   collapsible panels.
5. "Open on chart" from every setup and alert card, landing with that plan or event highlighted.
6. Phone layout: chart full width (pinch zoom), then a tab bar with Plan / Events / Stats / Research.

**How it fits together.** Overview card → workspace with the plan drawn and the marker pulsing → the
member adjusts sizing in the left panel → watchlist star in the header. A marker tooltip links to the
original post, filing or contract.

**Reused capabilities.**
- `analysis_collector.market()` (OHLCV and 15-minute bars)
- `trade_map` levels and `setup_levels` (plans)
- existing Form 4 classification, quotes, watchlist, news and ticker chat
- the zod contract layer (it must grow a candle shape)

**Dependencies and missing data.**
- **Chart library [As]:** TradingView Lightweight Charts (Apache-2.0, free, about 45 KB, has candles,
  volume, markers and per-bar colours) works in a Next 16 client component. *Check:* a half-day trial
  before committing. The licence requires a TradingView attribution link (D4).
- **New permissions:** the dashboard has no read permission for `options_flow` yet. The feed allowlist
  covers alerts, analyst views, signal events, research and swarm alerts. Adding a permission follows the
  existing owner-permission pattern (like `bot-swarm-alerts`).
- **Time handling:** markers must use "detected/filed at" for when we knew it. Transaction date shows as
  a separate field.

**Approach and tradeoffs.**
- A library beats extending the hand-drawn SVG: zoom, pan, crosshair and markers are weeks of work to
  hand-build. Cost: a new dependency and an attribution logo.
- Markers come from one new API endpoint (`/ticker/{t}/events?from=`) that reads stored tables, so the
  page doesn't grow per-source calls.
- Keeping the published plan read-only and sizing as a private copy avoids building plan versioning in R1.

**Effort:** about 6–9 builder-days, plus 1–2 days of review and browser checks.
**Maintenance:** low (library upgrades, marker query upkeep).
**Recurring cost:** $0 for data. No extra Schwab calls, just a larger response. No AI.

**Acceptance criteria (all checked live, signed in, desktop 1440 px and phone 390 px).**
- NVDA report shows real candles and volume for 5Y. The crosshair values match the Schwab daily bar for
  a spot-checked date.
- A setup card's "Open on chart" shows the same entry, stop and targets as the card, with per-target R:R
  that matches hand arithmetic (two tickers checked). HOOD-style T1 < 1R shows the warning.
- Each of the 6 marker layers toggles. Each tooltip has event date, known-at time (Pacific) and a working
  source link. At least one ticker shows ≥4 layers at once without overlap clutter.
- Changing account risk updates shares and dollar risk. "Reset" restores the published plan. Reloading
  never shows a different plan than the card.
- On phone: no sideways page scroll; the chart stays usable; all panels are reachable.
- Existing report sections still render. The browser suite shows no new failures beyond the recorded backlog.

### R2: "Dense Overview"

**Deliverables (layout modelled on `gekko-home-quality.jpg`).**
- **Row 0:** index strip (existing) plus about 8 key ETFs (SPY QQQ IWM DIA TLT GLD VIX-proxy BTC-ETF) in the
  same one-a-minute quotes call.
- **Row 1:** **Market brief**: 3–4 sentences written by AI after the close and at midday, shared by all
  members, cached, timestamped, with a refresh time. It must cite only numbers from the page.
- **Row 2, three panels:**
  - 6-month index candle chart (SPY/QQQ/IWM/DIA switch; Expand opens the R1 workspace)
  - sector/majors heatmap coloured by day change (11 sector ETFs plus majors, from `market_store` and live quotes)
  - sector rotation and leaders/laggards (from `sector_rs_daily` and `factor_rs_daily`)
- **Row 3, three panels:**
  - Top setups (by confidence, with state)
  - Smart-money feed (unusual options, insider buys from SEC, group alerts; filter chips)
  - Market news (free news feed, de-duplicated, ticker-tagged)
- Side column (track-record gauge, watchlist) folds into these rows on desktop. On phone, rows stack in
  priority order: brief → movers → setups → feed.

**Reused:** market strip and quote poller, `market_store` ETF history, `sector_rs_daily`, feed panels, news
fetcher, AI budget and `check_note` number-grounding (`analysis_collector.py` line 393).
**Dependencies:** the R1 chart component; `sector_rs_daily` permission; a small brief job in the worker.
**Tradeoff:** "show everything at once" replaces the current one-tab-at-a-time lists. Each block shows only
its top 5–8 rows with "Full →". That is the density-without-clutter rule.
**Effort:** 4–6 builder-days. **Maintenance:** low–medium (brief prompt, heatmap symbol list).
**Recurring cost:** about 2 AI calls/day (well inside the $3/day cap). Data $0.
**Acceptance:**
- At 1440 px, all six panels are visible above the fold plus one scroll, each with an "updated" time in Pacific.
- Clicking any ticker anywhere opens the R1 workspace.
- Every number in the brief matches a number on the page (an automated check rejects mismatches).
- The heatmap matches live quotes within one poll.
- The phone order is correct.

### R3: "Ideas board v1" (from existing setups)

**Deliverables.** A new `/ideas` page of idea cards built from existing setups. Each card shows:
- setup type and direction
- mini candle chart with levels
- entry/stop/targets with per-target R:R and $10k-position sizing
- a **state badge**: Waiting / Active / Stop reached / Target reached / Expired (computed from daily bars
  and live quotes, with the fill rule written out)
- publish time
- dated evidence list (alerts, analyst calls, options, insiders)
- risks
- "Open on chart"

Filters: direction, sector, state, sort by confidence or recency. Published plans are never rewritten;
a new plan is a new version.

**Reused:** `setup_levels`, `publication.py` versioning, R1 chart and marker endpoint, `ticker_sector_cache`.
**Not included:** historical win rates (they need the Phase 2 simulator). Live outcomes appear only via the
track record and its ≥20-sample rule.
**Effort:** 4–6 builder-days. **Recurring cost:** $0.
**Acceptance:**
- Every active setup appears exactly once.
- State badges match a hand check on 5 cards, including one stop-reached.
- Card → chart shows the identical plan.
- Arithmetic matches on all cards (the audit's 62-card method: R:R within 0.01, dollars within $1).

### R4 (optional within Phase 1): "Smart Money v1"

Pages from tables we already collect, each with a "how this is measured" note and freshness stamp:
- **Options** (`options_flow`: contract, expiry, premium, volume/open interest, inferred side; filters)
- **Short activity** (FINRA daily off-exchange short-volume ratio vs its own 30-day average; biweekly short interest)
- **Planned insider sales** (Form 144)
- **Analyst and group calls**

Each row links to the chart workspace with the matching marker. **Effort:** 3–4 builder-days.
**Dependencies:** read permissions for three more bot tables. **Cost:** $0.
**Acceptance:**
- Every page loads with an explainer and freshness.
- Filters work.
- Row → chart shows the matching marker on the right date.

**Phase 1 total:** about 17–25 builder-days, plus review. One small release ships at a time.

---

## 5. Phase 2: modest new calculations and pipelines

**User benefit.** Gekko-style "the chart tells a story": trend-coloured candles, technical signal markers,
a timing score with zones, market-wide heatmaps and screening, and historical context on ideas, all with
documented rules.

| Item | What it is | Inputs | Approach / tradeoff | Effort |
|---|---|---|---|---|
| **2a. Central daily price store** | Nightly job saves daily bars for a universe: watchlists, recent alert/setup tickers, S&P 500, sector/theme ETFs (~600 symbols) | Schwab `/pricehistory`; universe list from a free S&P 500 constituent source [As: licence fine for internal use] | 600 calls at 15/min ≈ 40 min at night, outside market hours. Storage under 100 MB. **Foundation for 2b–2f.** Tradeoff: adds a job to monitor | 4–6 days |
| **2b. Trend-coloured candles** ("Trend" toggle) | 5 colour bands: strong up, mostly up, mixed, mostly down, strong down | Daily bars | Documented rule (for example: close vs 20/50-day averages, the averages' slopes, and a trend-strength reading), computed only from bars up to that day so colours never change after the fact. Independent of Gekko's TrendCandles | 2–3 days |
| **2c. Technical markers** | Candle patterns (engulfing, hammer, kicker, morning/evening star), volume thrust, exhaustion (N new highs/lows in a row) | Daily bars | Each rule published, with its **confirmation bar** (the marker appears on the bar where it became knowable). Grouped as one "price-pattern family" | 3–5 days |
| **2d. Market Edge timing score v0** (name: D3) | 0–100 positioning/timing composite with zones, component breakdown and version number | Price stretch vs its average (in typical-daily-move units), short-term momentum (inverted), relative volume, FINRA off-exchange short-sale ratio vs its own history | Transparent weights, published. Shown on chart (sub-pane), Ideas, heatmap colouring and Screener. A forward-return-by-zone table from our own data, with sample counts, labelled **"experimental, not validated"**. The FINRA history only starts 2026-05-11, so the version with that component has short history; the price-only components go back years | 5–8 days |
| **2e. Wider Screener and heatmaps** | Screen the 2a universe with technical, score and event filters; S&P 500 heatmap; named watchlists and **account-saved screens** (stop using browser storage) | 2a, 2d | Reuses the existing screener UI (filters, columns, explanations). Moves saved screens to the database | 5–7 days |
| **2f. Ideas historical context** | Simple, published simulator: daily bars, stated fill rules, "stop checked first if both hit the same day", gaps, costs; trade list shown | 2a | Same plan record as the card. Sample count beside every rate. **No optimizer** (the audit showed optimizing for best past profit picks fragile settings) | 5–7 days |
| **2g. Central insider feed** | Daily SEC Form 4 ingestion for the universe (open-market buys/sells, owner role) | Free EDGAR daily index | Reuses the existing Form 4 classifier. Feeds Smart Money and chart markers market-wide, not just per report | 3–5 days |
| **2h. Seasonality panel** | Average 5/10/20/30-day forward return by calendar date, with the number of years up | 10–20 years of daily bars (one Schwab call) | Show the sample (years) prominently. Note it is split-adjusted, not dividend-adjusted | 1–2 days |
| **2i. Plan quality rule** (only if D5 = change rules) | Treat T1 under 1R as a partial exit, or skip setups whose best target is under 1.5R | `trade_map` | Changes what setups members see, so it needs owner approval and before/after counts | 2–3 days |

**Order inside Phase 2:** 2a → (2b, 2c, 2h in parallel) → 2d → 2e → 2f → 2g. Each ships alone:
- 2b + 2c together = "signal chart" release
- 2d = "timing score" release
- 2e = "market-wide discovery" release

**Maintenance:** medium (a nightly job with retry, freshness alert to #errors, universe refresh quarterly).
**Recurring cost:** $0 data, about 0 AI. Disk under 1 GB.
**Acceptance (per release):**
- Each new marker or colour has a one-paragraph rule page linked from its tooltip.
- A replay check: compute signals on data cut at date X, then on full data; markers up to X are identical
  (no changing history).
- Score components add up to the shown score.
- Screener results match a manual filter on 3 tickers.
- The simulator's trade list reproduces by hand for one ticker.
- Freshness: the nightly job failing raises one #errors alert and the UI shows "data as of" in Pacific.

---

## 6. Phase 3: later (hard models, big history, or not possible free)

| Item | Why deferred |
|---|---|
| Validated score / optimizer | Needs walk-forward testing and longer point-in-time history. The project's own research found no edge above ~+11 bps for many methods. Start only after 2d has accumulated live outcomes |
| 13F fund pages (Billionaires/Trailblazers style) | Free from SEC, but heavy normalization (CUSIP mapping, amendments, share classes). Medium–high effort, quarterly data |
| Fundamentals (statements, segments) and fair value | SEC company facts are free, but normalization and a trustworthy valuation model are large |
| Buyback programs | Needs program identity and amendment handling (the GEO double-count trap in the audit) |
| Congress trades | Our table is stale; free sources are unreliable. Needs a new pipeline and a demand check |
| Price/score alerts per member | Durable alert service with delivery history; useful but operational. Could move earlier if members ask |
| Full IV surfaces, broad historical options flow | Not possible free at the needed breadth. Databento credit is research-only |
| Analyst ratings and rank history, consensus estimates, website traffic | **Not possible free** (Finnhub free tier returns 403; no free traffic source). Omit unless D2 changes |
| Prediction markets, referrals, public SEO pages | Low priority for an invitation-only site |

---

## 7. Recommended first release and what to defer

**Ship R1 "Chart workspace" first.** It is the screen the owner likes most and needs no new data (OHLCV is
already fetched). It fixes the biggest visible gap (line chart → candles + volume + markers) and creates the
component that R2, R3 and R4 reuse. A member can experience it end to end: open an alert → see the candle
chart with the plan and dated evidence markers → size the trade → watchlist it.

**Before R1 (Phase 0, about 1 day):**
- commit the deployed-but-uncommitted work and sync `master`
- settle line endings
- agree who builds (D6)
- run the half-day chart-library trial
- record the browser-test baseline so new failures are visible

**Deferred, and why:**
- the timing score until trend and pattern rules exist (2d builds on 2a–2c)
- the simulator until the price store exists
- anything needing paid data (standing rule)
- 13F, fundamentals and buybacks until Phases 1–2 prove the workflow
- member alerts until after Ideas

---

## 8. Assumptions to check (with the check)

1. Lightweight Charts runs cleanly in our Next 16 / React 19 build with the strict Content Security Policy. *Half-day trial.*
2. A 5Y daily request is one Schwab call of similar speed. *Time one NVDA call.*
3. The extra quote symbols for R2 fit in the existing 100-symbol call without pushing out watched tickers. *Count current usage.*
4. `options_flow` rows are reliable enough to show (bot edits pending in `options.py`). *Read the diff and spot-check 10 rows against Schwab.*
5. The FINRA short-volume ingestion is daily and complete (newest 2026-10-08 [V]). *Check for gaps across the 5 months.*
6. A free S&P 500 constituent list is usable internally. *Pick a source and record its terms.*
7. Night-time Schwab pulls for ~600 symbols stay within the 15/min share without slowing the bot. *Dry-run 50 symbols.*

## 9. Decisions for the owner

- **D1 Schwab display terms.** Members already see Schwab numbers. Expanding that (heatmaps, market-wide
  screener) raises the unresolved terms question. Accept the risk, check the terms first, or switch display
  prices to a free source where possible?
- **D2 Paid data.** Keep the standing free-only rule (Phase 3 paid items stay "not possible free")?
- **D3 Score name and style.** Our own name (not "GekkoIndex"). Contrarian like Gekko (high = beaten down), or a plain trend-following score?
- **D4 Chart library attribution.** Lightweight Charts asks for a small TradingView link. Acceptable?
- **D5 Weak first targets.** Warning only (R1), or also change setup rules (2i)?
- **D6 Builder.** Codex on Windows, Claude on the server, or split by release? (Same files must not be edited by both at once.)
- **D7 R4 timing.** Ship Smart Money v1 in Phase 1, or after Phase 2's insider feed?

## 10. Questions for the Codex review

Please review product design and implementation strategy, not code bugs:
1. Does the layout deliver dense, informative, uncluttered Home and Charts screens? What would you cut or add?
2. Are existing-data wins correctly first? Is R1 the right first release, and is it small enough?
3. Do architecture, dependencies and sequencing support small complete releases (especially the R1 → R2/R3 component reuse and 2a as the foundation)?
4. Any unnecessary complexity, duplication, or avoidable paid-data cost?
5. Are chart signals and research outputs understandable and traceable (known-at times, families, labels)?
6. Do the acceptance criteria prove a cohesive user experience, not just working parts?
7. What gaps, weak assumptions or better alternatives should change the plan?
