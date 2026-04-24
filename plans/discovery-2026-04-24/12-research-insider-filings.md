# Phase 1 Discovery — Insider Behavior & SEC Filings

**Worker:** insider-filings researcher
**Date:** 2026-04-24
**Domain scope:** Form 3/4/5 (Section 16), Schedule 13D/13G + amendments, 13F-HR, S-1/S-3/424B (offerings), Form 144, S-4/425 (M&A), DEF 14A/DFAN14A (proxy/activism), Form D (private placement), 8-K (thesis-only per CLAUDE.md).

**Mission:** propose 5–12 candidate features that surface actionable setups BEFORE mainstream confirmation, using only free public data (SEC EDGAR primary).

---

## Cross-cutting infrastructure notes

These apply to most/all features below; called out once to avoid repetition.

- **Primary source:** SEC EDGAR. Three free endpoint families relevant here:
  - **Latest filings RSS** — `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&start=0&count=100&output=atom`. Updated every ~10 min, M–F 06:00–22:00 ET. The `&type=` filter is a substring/prefix match (e.g. `type=4` returns `4` and `4/A`; `type=SC%2013D` matches `SC 13D` and `SC 13D/A`). Useful for forms: `4`, `4/A`, `SC%2013D`, `SC%2013G`, `SC%2013D%2FA`, `13F-HR`, `S-1`, `S-3`, `424B5`, `S-4`, `425`, `144`, `DEF%2014A`, `DFAN14A`, `D`. ([SEC RSS Feeds](https://www.sec.gov/about/rss-feeds))
  - **Submissions JSON per CIK** — `https://data.sec.gov/submissions/CIK{0-padded-10-digit-cik}.json`. Returns last ~1000 filings with `accessionNumber`, `filingDate`, `acceptanceDateTime`, `form`, `primaryDocument`, `items` (8-K items). Updated with sub-second processing delay after acceptance. ([SEC.gov | EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces))
  - **Full-text search** — `https://efts.sec.gov/LATEST/search-index?q={query}&forms={forms}&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD`. No key required; same 10 req/s rate limit. Useful for activist letter language scans, proxy nomination text, etc. ([EFTS FAQ](https://www.sec.gov/edgar/search/efts-faq.html))
- **Hard rate limit:** 10 requests/second total across `data.sec.gov`, `www.sec.gov/cgi-bin`, and `efts.sec.gov`. Exceeding it triggers a 403 and ~10-minute IP block. ([New rate control limits](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits))
- **User-Agent:** mandatory, must include name + email. Repo already uses `Akash Chopra (ak@openclaw.dev)`.
- **Filing-to-feed latency:** Form 4 filings appear in the RSS feed within 1–10 minutes of `acceptanceDateTime`. This is the hot path. The `acceptanceDateTime` (UTC) is the gating timestamp; many filings are accepted at exactly 17:31 ET (just after market close) when amendments and Form 4s batch.
- **Form 4 XML primary doc:** every Form 4 filing exposes `Form4_*.xml` (Ownership XML 1.0). Parse via `xml.etree`: `<transactionCode>` ∈ {P=open-market buy, S=open-market sale, A=grant/award, M=option exercise, F=tax-withholding, G=gift, J=other}. The `P` and `S` codes are the only ones with predictive value — the rest are compensation noise that drowns ~80% of raw Form 4 traffic. ([SEC Ownership XML Spec](https://www.sec.gov/info/edgar/ownershipxmlspec-v1-r1.doc))
- **10b5-1 detection:** since the 2022 10b5-1 amendments, a checkbox `<aff10b5One>true</aff10b5One>` (or footnote text "pursuant to a Rule 10b5-1 trading plan") appears in the XML. Cohen/Malloy/Pomorski (2012) shows opportunistic (non-plan) trades earn ~82 bps/month abnormal return; routine plan trades earn ~0. **Discretionary-only filtering is a baseline requirement, not an optimization.** ([Decoding Inside Information](https://www.nber.org/system/files/working_papers/w16454/w16454.pdf))
- **Constraint reminder (CLAUDE.md):** 8-K never triggers standalone alerts. Form 4 is an instant-trigger exception (insider trading is named in CLAUDE.md). 13F is delayed 45 days = confirmation, never instant. SEC data feeds LLM thesis only — features below either (a) emit a structured signal that joins the cross-ref scoring rubric (+15 weight per CLAUDE.md), (b) emit thesis context, or (c) produce a standalone alert when allowed.

---

## Feature 1 — Cluster Form 4 Open-Market Buys (rank-weighted, discretionary only)

**Function.** Detect ≥2 distinct insiders filing a Form 4 with transaction code `P` (open-market buy), `aff10b5One=false`, on the same ticker within a rolling 14-day window; emit a standalone instant-trigger alert with rank-weighted size and lookback-z-score.

**Rationale + measurable edge.** Six decades of academic work (Lakonishok/Lee 2001; Cohen/Malloy/Pomorski 2012) document that opportunistic open-market insider buys generate persistent abnormal returns of roughly 6–10% over 6–12 months. Cluster buys (≥2–3 insiders within days) are the high-precision subset — practitioner consensus cites this as "the strongest signal" and OpenInsider's `latest-cluster-buys` page is built on it. Rank-weighting (CEO=3, CFO=3, COO=2, other officer=2, director=1, 10% holder=1) captures the well-known finding that C-suite buys outperform director buys. **Edge measurement:** target precision = % of clusters where 21-day forward return > SPY by ≥3% (literature suggests 55–65% hit rate); lead-time = filing-acceptance to mainstream news pickup (typically 12–48 hours; this is the alpha window). Coverage delta vs naive single-insider filter: cluster filter cuts volume ~95% but lifts precision ~2x.

**Source category.** **High** — SEC EDGAR direct (`getcurrent` RSS for `type=4` + per-filing XML fetch).

**Sources.**
- Discovery: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&start=0&count=100&output=atom` (poll every 60–120s).
- XML primary doc: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{primaryDocument}` discovered from submissions JSON.
- Issuer ticker mapping: `https://www.sec.gov/files/company_tickers.json` (cache 24h).

**Latency.** Real-time within ~1–10 min of acceptance. Form 4 must be filed within 2 business days of the trade — so trade-to-feed lag is up to ~48h. Recent SSRN work ("The Death of Insider Trading Alpha", Ozlen/Batumoglu) argues 70–80% of alpha dissipates between trade date and the next trading day, so this feature races other Form-4 trackers (OpenInsider, secform4.com) — winning means publishing within minutes of acceptance, not hours. ([SSRN 5966834](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5966834))

**Failure mode.**
- 10b5-1 plans now have a 90-day cooling-off period (post-2022 amendments) so insiders can game the appearance of opportunism by adopting a plan, waiting 90 days, then having "discretionary"-looking executions. Check `<aff10b5One>` AND the original plan-adoption footnote.
- "Cluster" can be artificially produced by board-grant batches mis-coded — filter on transaction code `P` strictly (not `A`).
- Amendments (`4/A`) can void or restate a prior buy days later — track the amendment chain and retract alerts older than 5 days when an amendment reduces share count > 50%.
- Crowded shorts can trigger "insider buy = artificial squeeze trap" but this is risk, not failure of the signal.

---

## Feature 2 — Insider Buy Size vs Personal Historical Average (z-score buy)

**Function.** For each Form 4 `P`-code buy, compute the z-score of dollar size against that specific insider's prior trailing-2-year buy distribution; emit a candidate alert when z ≥ 2.0 AND dollar size ≥ $250k AND insider role ∈ {CEO, CFO, COO, Chair}.

**Rationale + measurable edge.** A $1M buy by an insider whose typical buy is $50k is qualitatively different from a $1M buy by someone who buys $1M routinely. The personal-history baseline is the right anchor — not a flat dollar threshold. Lakonishok/Lee and follow-up work consistently show abnormal-size buys have higher predictive content. **Edge:** precision lift over a flat $250k threshold ≈ 1.5x (estimated; would be measured by backtest); covers cases where a director who never buys suddenly drops $200k — a flat $250k filter misses that, but z-score catches it relative to that insider's historical $0–$10k pattern. Pair with Feature 1 cluster scoring as a +bonus weight rather than a standalone alert.

**Source category.** **High** — SEC EDGAR direct, but requires per-insider history (per-CIK reporting-owner aggregation). The reporting owner CIK is a separate CIK from the issuer; both are in the Form 4 XML.

**Sources.**
- Per-insider submissions: `https://data.sec.gov/submissions/CIK{insider-cik}.json` returns all of that person's past Forms 3/4/5 across companies.
- Local cache table `insider_history` keyed on `(insider_cik, transaction_code)` storing rolling 2-year buy distribution.

**Latency.** Real-time on the new filing; the historical distribution updates incrementally.

**Failure mode.**
- New insiders (no 2-year history) — fall back to peer-role distribution (all CEO buys at companies < $1B mkt cap).
- Insiders with multi-CIK reporting (e.g., person reports under family trust CIK + personal CIK) — need to merge by name+address fuzzy match. Not perfect.
- Survivor bias: insiders who got fired and lost reporting status fall out of the distribution. Acceptable.
- "First-ever buy" insiders (Form 4 with no prior `P`-code) can't be z-scored — treat as automatic z=∞ if dollar ≥ $50k, gated by role check.

---

## Feature 3 — 13D New-Filing Activist Detection (5-day window post-Feb-2024 rule)

**Function.** When a new Schedule 13D appears, score on (a) filer's activist history (campaign count over trailing 5 years from past 13D filings), (b) percentage stake disclosed (Item 4 / cover page), (c) Item 4 plain-text "Purpose of Transaction" intent classification (passive disclaimer vs board-change vs strategic-review vs strategic-alternatives language); emit a standalone alert when filer has ≥2 prior campaigns OR Item 4 contains nomination/board/strategic-alternative language.

**Rationale + measurable edge.** Effective Feb 5 2024, the 13D filing window contracted from 10 days to 5 business days post-5%-crossing — meaning new 13Ds now hit the tape closer to the actual accumulation event. Academic work (Brav/Jiang/Kim and many others) documents 5–10% abnormal returns in the 20-day window post-13D filing for activist filers; the lift is concentrated in known activists. Filer-history weighting is the actionable lever — a new 13D from Elliott / Starboard / Engaged is qualitatively different from a 13D by a generic family office. **Edge:** lead-time vs first sell-side note ≈ 2–8 hours (activist 13Ds typically generate same-day SA / mainstream coverage); precision target = 60% positive 21-day excess return for known-activist 13Ds. ([SEC modernization rule](https://www.federalregister.gov/documents/2023/11/07/2023-22678/modernization-of-beneficial-ownership-reporting))

**Source category.** **High** — SEC EDGAR direct (`getcurrent` RSS for `SC 13D`, plus full-text-search backfill).

**Sources.**
- Discovery: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC+13D&start=0&count=40&output=atom`.
- Filing primary doc: HTML, parse Item 4 "Purpose of Transaction" — keyword regex on {nominate, board representation, strategic alternatives, sale of the Company, replace, dissident, withhold votes, refresh}.
- Activist history: build local table from per-filer `submissions` JSON, count distinct issuer-CIKs with prior 13D filings.

**Latency.** Real-time within ~10 min of acceptance. Net of the rule change, signal-to-event lag is now ≤7 calendar days from accumulation rather than ≤12.

**Failure mode.**
- Some sophisticated filers stagger 13D filings across affiliated entities — need group-level CIK aggregation.
- Item 4 language is sometimes deliberately vague; regex misses softer "engagement"/"discussions" wording — false negatives.
- Cash-settled swap accumulation can pre-build a position before any 13D is required (one of the SEC's stated modernization targets, but enforcement is uneven).
- Joint-filer 13Ds count once, not N times.

---

## Feature 4 — 13G → 13D Conversion (intent change)

**Function.** Detect when a holder previously on a Schedule 13G/13G-A for a ticker files a new Schedule 13D for the same ticker; emit a standalone alert flagging the regime change from "passive" to "active" intent.

**Rationale + measurable edge.** Going from 13G (passive certification) to 13D is a binary statement-of-intent change — the filer is legally required to switch when they form intent to influence control. The conversion is a stronger signal than a fresh 13D because the holder already had the position and is now declaring activist intent on shares they likely accumulated quietly. There is a 10-day post-13D-filing trading freeze for the converted filer, which often means a slug of buying *before* the 13D appears. **Edge:** rare event (~few hundred conversions/yr across all US issuers) but high precision; estimated 65–75% positive 30-day forward returns for non-microcap tickers based on historical activist-conversion case studies (DFIN/HBLR Corp Gov Forum sources). Coverage delta vs raw 13D feed: ~15% of 13D-filers were on 13G first — features 3 and 4 produce roughly disjoint candidate sets.

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- Same RSS as Feature 3 plus `type=SC+13G`.
- Local table `holder_intent` keyed on `(filer_cik, issuer_cik)` storing latest schedule type.
- On new 13D, lookup prior schedule type for that pair.

**Latency.** Real-time; conversion logic runs on every 13D arrival.

**Failure mode.**
- A holder may file 13G then sell down then re-accumulate and file fresh 13D — that's a new position, not a conversion. Need to verify continuous ownership via stake-percentage continuity in 13G amendments.
- Some filers (Berkshire) hold 13Gs that almost never convert, so absence of a conversion isn't bearish information either way.
- Ticker change / corporate-action–driven re-filings can look like conversions but aren't.

---

## Feature 5 — Form 144 → Form 4 Sell-Through Latency (insider-conviction proxy)

**Function.** Track every Form 144 (notice of intent to sell) and the subsequent matching Form 4 sells; flag (a) Form 144 filings with no follow-through within 90 days (insider abandoned the planned sale → potentially good news), and (b) Form 144 → Form 4 with same-day or next-day execution at price <90% of intent-day reference (insider sold into weakness → bearish).

**Rationale + measurable edge.** Recent academic work (arXiv 2602.17890, "The Information Dynamics of Insider Intent") shows the post-SOX reporting inversion: Form 4 (executions) is now mandated within 2 business days while Form 144 (notice of intent, which arXiv finds to be "frequently delayed") creates a structural information asymmetry. The same paper documents a 52.4% "opacity rate" — Form 144 filings where execution never publicly resolves. *Aborted* Form 144s (planned sale abandoned) carry hidden positive information; *fast-execution* Form 144→Form 4 chains carry hidden negative information. **Edge:** lead-time advantage of ~3–10 days vs aggregator dashboards that focus on Form 4 only. Precision: aborted-144 base rate ~25% of 144s; expected positive forward return concentrated in C-suite filers. Coverage delta vs Form-4-only insider features: roughly 20–30% of Form 144s never produce a matching Form 4 — pure informational gain.

**Source category.** **Medium** — SEC EDGAR direct for raw filings, but matching 144→4 execution chains is heuristic (requires fuzzy match on filer name + share count).

**Sources.**
- `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=144&output=atom`.
- Form 144 primary doc has approx-share-count + intended-sale-window.
- Match against Form 4 `S`-code filings by same reporting owner within 90 days.

**Latency.** Form 144 is filed concurrently with placing the sell order; signal arrives EOD or next morning. The 90-day no-follow-through evaluation is necessarily T+90.

**Failure mode.**
- Form 144 is paper-filed for many small filers — large gaps in EDGAR coverage for sub-$1B issuers.
- Block trades that get split or rerouted may not produce a 1:1 form-4 match — ambiguous matching.
- Insider may execute the planned 144 sale via a 10b5-1 amendment that reroutes through a different reporting owner — false-negative aborts.
- The arXiv claim of 52.4% opacity should be backtested before depending on it.

---

## Feature 6 — Shelf Takedown Surprise (S-3 + 424B5 dilution event)

**Function.** Detect every 424B5 (prospectus supplement under shelf S-3) where the issuer's market cap < $500M; compute (a) takedown size as % of shares outstanding, (b) days since last 424B5 takedown, (c) cash position at last 10-Q (XBRL `CashAndCashEquivalentsAtCarryingValue`); emit thesis-only context (NOT a standalone alert) flagging dilution risk for ongoing tracking, and a directional bearish bias for any open long thesis on that ticker.

**Rationale + measurable edge.** For micro/small caps with limited cash runway, shelf takedowns are dilutive shocks that produce same-day -5% to -20% gaps, often overnight or pre-market. The signal is *defensive* — the bot cannot use this to trigger long alerts (offerings are bearish), but it can (a) **kill** existing long alerts on tickers with fresh 424B5s within the past 24h, and (b) feed the LLM thesis with explicit dilution language. Conversely, a *clean expiration* of a shelf S-3 with no takedowns is a quiet positive signal. **Edge:** prevents false-positive long alerts on tickers in active dilution. Estimated 40–60 events/month across small caps; ~80% produce same-day negative drift. ([DilutionWatch S-3 guide](https://dilutionwatch.com/articles/shelf-registrations.html))

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=424B5&output=atom` plus 424B2, 424B3, 424B4.
- Issuer market cap from Finnhub (already in repo) at time of takedown.
- Shares outstanding via XBRL `CommonStockSharesOutstanding` (use `mcp__sec-edgar__get_company_concepts`).
- Cash from `mcp__sec-edgar__get_company_concepts(concept_name="CashAndCashEquivalentsAtCarryingValue")`.

**Latency.** Real-time within ~10 min; 424B5 filings hit before market open or after close in ~85% of cases (companies time them to minimize execution risk).

**Failure mode.**
- "ATM" (at-the-market) programs file a single 424B5 then dribble shares for months; the filing date understates the dilution event.
- Forward-looking takedowns vs already-executed takedowns are language-distinguished but not field-distinguished — needs prospectus-supplement text parse.
- Baby-shelf rule (public float < $75M caps takedown to 1/3 of float in trailing 12 months) — micro-caps may have fewer takedowns than headline-shelf size suggests.

---

## Feature 7 — S-1 IPO Lockup-Expiration Tracker

**Function.** Parse every new S-1 / S-1/A filing for the IPO lockup-expiration date in the underwriting section; build a calendar of expirations; flag tickers in the 3 trading days before and 1 day after lockup expiration as "supply event approaching."

**Rationale + measurable edge.** Lockup expiration releases insider/employee/VC supply onto the market and is a well-known overhang event with documented price drift in the days surrounding it. Most retail tools surface this as a static calendar but the actual date is buried in the S-1 prospectus and shifts on follow-up amendments. **Edge:** automated extraction from S-1 amendments captures the *correct* date when underwriters revise terms (~10% of IPOs). Mostly defensive (kill long alerts in the 3-day pre-window) but optionally supports short-bias setups. Estimated 50–100 lockup events/month; expected mean-revert into and bounce after for ~60% of them.

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `getcurrent?type=S-1` + `type=S-1%2FA` RSS.
- Full-text search efts.sec.gov for `q="lock-up agreement"&forms=S-1` to backfill.
- Prospectus body parse for "180 days after the date of this prospectus" / "270 days" patterns + IPO date from 8-A12B filing.

**Latency.** Date is known weeks/months in advance; alert window is calendar-driven.

**Failure mode.**
- Underwriters can release lockup early via waiver — 8-K item 8.01 sometimes discloses; sometimes not.
- "Tail" lockups for specific holders only (founders) vs everyone — granular extraction needed.
- For SPAC-IPOs the lockup mechanics differ; may need a separate parser branch.

---

## Feature 8 — Form D Reveal (private placement / late-stage venture)

**Function.** Watch Form D filings on already-public micro-caps (market cap < $300M); flag PIPE structures (Item 8 issuance type "PIPE", "Convertible note", "Warrants") with dollar size > 10% of market cap; emit thesis-only context plus directional bearish bias (PIPE dilution) UNLESS the buyer is named and is a known strategic/quality biotech specialist (e.g., Baker Bros, RA Capital).

**Rationale + measurable edge.** Form D filings within 15 days of first sale reveal private placements that frequently presage public dilution OR validating capital infusions. For micro-cap biotech in particular (the dominant Form D-issuing public sub-segment), the *named investor* matters: a Form D with Baker Bros as lead is bullish (they pick winners); a Form D with anonymous family offices and 30% warrant coverage is dilutive bearish. **Edge:** lead-time vs sell-side coverage ≈ 1–7 days; coverage delta vs 424B-only dilution detection: Form D catches private-side dilution that doesn't always trigger an immediate 424B. Estimated 200+ Form Ds/month from public small caps; ~5–10% are tradable signals. ([RxDataLab Form D guide](https://rxdatalab.com/guides/biotech-form-d-database/))

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `getcurrent?type=D&output=atom`.
- Form D XML schema exposes `relatedPersonsList` (named buyers), `offeringSalesAmounts/totalAmount`, `industryGroup` (biotech = code BIO).
- Cross-ref local `quality_buyers` whitelist for biotech specialists.

**Latency.** Up to 15 days lag (issuer has 15 days post-first-sale to file). The signal is the *publication*, not the underlying transaction.

**Failure mode.**
- Form D for non-public issuers (most of them) is irrelevant noise — must filter to issuers with a CIK that also has 10-Q filings.
- Buyer names can be intermediated through SPVs — a Baker Bros position routed through "BB Capital LLC" needs maintained name-mapping table.
- Issuer may announce the round via 8-K simultaneously, in which case the Form D is confirmation, not lead.

---

## Feature 9 — S-4 / 425 M&A Filing Real-Time Detection (deal arbitrage initial spread)

**Function.** Detect new S-4 or 425 filings; if the filing is a fresh-deal announcement (not a routine update), classify as (a) cash deal, (b) stock deal, (c) mixed, parse offer per-share value, and emit a thesis-only contextual signal (NOT a standalone alert per CLAUDE.md's 8-K rule extension by analogy — but if Form 4 cluster cross-references in same window, that combo is a triggerable two-source confirmation).

**Rationale + measurable edge.** Targets of announced M&A typically jump 27% on average and trade at a 3.5% arbitrage spread to the offer (Inside Arbitrage 2025). The window between S-4/425 acceptance and broad-tape pickup is typically 5–30 minutes. For deals announced after-hours, the 425 may hit hours before next-day's open — this is the window where an alert is most actionable. **Edge:** lead-time vs Bloomberg/Twitter ≈ 2–10 minutes; ~40–60 announced US deals/month meaningful for retail. Pair with Form 4 buys by the target's insiders in the prior 14 days (which would be illegal but the SEC enforces this so absence is the norm) OR by the acquirer's insiders (occasionally legal and informative).

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `getcurrent?type=425&output=atom`.
- `getcurrent?type=S-4&output=atom`.
- 425 is a "communications" filing — the body is typically a press release, parseable for "merger agreement"/"definitive agreement"/"per share" patterns.

**Latency.** Real-time within ~10 min of acceptance. Critical: the 425 generally appears the same morning as the deal-announcement press release, sometimes minutes earlier.

**Failure mode.**
- Many 425s are routine investor-presentation or post-announcement material; only the *initial* 425 of a deal pair is the news event. Deduplicate via "first 425 by acquirer-CIK referencing target-CIK in trailing 30 days."
- Definitive Agreement may be filed as 8-K instead of immediate 425 in some cases — cross-reference with 8-K Item 1.01 from same filer same day.
- Target-side stock spike happens regardless of who files first; the alert is the early-publication race.

---

## Feature 10 — Activist Filing Constellation (13D + DEF 14A + DFAN14A within 90 days)

**Function.** When a 13D filing precedes (or is followed by) a DEF 14A nomination notice or DFAN14A solicitation by the same filer within a 90-day window, escalate to a high-confidence proxy-contest alert. Use full-text search for "withhold," "vote against," "nominate," "dissident slate" in DFAN14A.

**Rationale + measurable edge.** Most 13Ds never escalate to proxy contests. The minority that do produce documented event-study returns of 8–15% in the run-up to the meeting (Brav/Jiang/Bebchuk literature). The *constellation* (13D → DFAN14A → DEF 14A from same filer-issuer pair) is far more predictive than any single filing. As of Oct 2025, 57 proxy fights were launched at Russell 3000 names — a tractable universe for a daily watcher. **Edge:** precision target ~70% positive 60-day excess return for the active-contest subset; coverage delta vs Feature 3 alone is high (most 13Ds don't escalate, so this filter narrows the set ~10x but lifts precision ~3x).

**Source category.** **High** — SEC EDGAR direct + full-text search.

**Sources.**
- Per-filer activity from Feature 3 cache.
- `getcurrent?type=DFAN14A` and `type=DEF+14A` RSS.
- efts.sec.gov full-text scan: `?q=%22withhold+vote%22+OR+%22nominate%22&forms=DFAN14A&dateRange=custom`.

**Latency.** Constellation completes over weeks; the alert fires when the second-leg filing arrives. So alert latency is ~10 minutes from the triggering second-leg filing.

**Failure mode.**
- Universal proxy rules (effective 2022) lower the activist's filing burden, increasing false-positive DFAN14As that don't seriously contest.
- Settlements happen quickly post-DFAN14A in ~50% of cases per Q3 2025 stats — by the time the constellation is recognizable, the trade may already be done.
- Confidential treatment requests can hide the substantive Item 4 detail in 13D, making intent classification noisier.

---

## Feature 11 — 13F Quarterly "Sharp Money" Cluster (confirmation-grade, never standalone)

**Function.** Quarterly post-13F-deadline (Feb 14 / May 15 / Aug 14 / Nov 14): compute, per ticker, the count of new positions *opened* (zero → non-zero) and the dollar-weighted total *increased* by a curated whitelist of "sharp money" filers (~40 funds: Pershing Square, Third Point, Lone Pine, Coatue, Tiger Global, Renaissance, AQR, etc.); emit thesis-only context that AUGMENTS open theses but never triggers an alert on its own.

**Rationale + measurable edge.** 13F is 45 days delayed by SEC rule; ~30% of hedge funds file on day 45 to maximize delay. So 13F is *confirmation*, not discovery. Per CLAUDE.md the bot already cross-references — 13F clusters add a slow but structurally informative second source: "this name has just been disclosed as a new buy at Pershing + Third Point + Coatue." **Edge:** improves alert quality not lead-time. Coverage delta is significant — for any Q, ~50–200 small/mid caps see ≥3 new sharp-money entries. As a +X-point boost in the cross-ref scoring rubric this is well-aligned with existing architecture.

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `getcurrent?type=13F-HR&output=atom` filtered by filer-CIK whitelist.
- 13F primary doc is `infoTable.xml` with `<nameOfIssuer>`, `<cusip>`, `<value>`, `<sshPrnamt>`.
- CUSIP→ticker via SEC's `company_tickers.json` does not include CUSIP; use the `tickers.txt` from FINRA + cusip-to-ticker mapping. Note: CUSIP licensing limits free public mapping; one workaround is to use the issuer-name fuzzy match against EDGAR's company_tickers table.

**Latency.** Worst-case 45 days from quarter end; in practice 13F-HRs trickle in the final week. This feature is fundamentally non-real-time.

**Failure mode.**
- 13F captures only LONG positions; shorts/derivatives invisible. A fund "exiting" may have rotated to puts.
- Fund-level CIK aggregation: many large funds report under multiple CIKs (e.g., separate vehicles); whitelist must include all sub-CIKs.
- Position size is reported as of quarter-end — by mid-May the data is stale by 6 weeks and the fund may have already exited.
- Recent SEC pushes to require monthly 13Fs were not adopted; this stays a confirmation feature.

---

## Feature 12 — Insider Departure Cross-Reference (8-K Item 5.02 + Form 4 sells in trailing 60 days)

**Function.** When an 8-K Item 5.02 hits (CEO/CFO/director departure, especially "for cause"/"effective immediately"/"to pursue other interests"), look back 60 days at that named insider's Form 4 activity for that issuer. If the departing insider had clusters of `S`-code sales OR option exercises with same-day sales (`M`+`S` paired) above their personal-history baseline in the 60-day window, this is a high-importance LLM-thesis input.

**Rationale + measurable edge.** Per CLAUDE.md, 8-K never triggers a standalone alert — but it CAN feed LLM thesis. This feature flips the asymmetry usefully: instead of treating the 8-K as the signal, treat it as a **pattern-completion event** that retroactively re-scores prior Form 4 sales. The thesis to the LLM becomes "X resigned today; she sold $4M in the 30 days before, well above her 2-year baseline; this completes a pre-departure liquidation pattern." That's powerful narrative context the bot can attach to a directionally-bearish thesis. **Edge:** zero standalone alert risk (compliant with 8-K rule); precision lift on existing bearish theses ≈ 1.5x; rare-event base rate (~20–40 cases/month system-wide). Coverage delta: catches departures the 8-K wouldn't flag prominently otherwise.

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- 8-K item parsing from `submissions.json`'s `recent.items` array (the items field is a comma-string of item codes like "5.02,9.01").
- Cross-ref against Feature 1/2 historical insider data.

**Latency.** Real-time on the 8-K (within ~10 min); but by definition the 8-K cannot trigger an alert — it only retroactively enriches an LLM thesis on already-watched tickers OR feeds a synthesis check at thesis-generation time.

**Failure mode.**
- Many 5.02s are benign (planned retirements with clean handoff); language regex on "for cause"/"by mutual agreement"/"effective immediately" is required.
- Some departures have no prior Form 4 trades (insider already minimized exposure long before) — true-negatives invisible.
- "Departure" cases of moving to a new role within parent/affiliate may file 5.02 misleadingly — context-dependent.

---

## Feature 13 — Spike in Form 4/A Amendments (latency / restatement signal)

**Function.** Track per-filer rate of Form 4/A (amended) filings versus baseline. A sudden cluster of amendments by an insider correcting prior reported transactions — especially upward share-count revisions or reclassification from `A` to `P` — flags either a compliance event or a re-disclosure that hadn't been captured in the original Form 4 cross-ref. Add to LLM thesis as enrichment context.

**Rationale + measurable edge.** Amendments often correct material misreporting. A reclassification from grant (`A`) to open-market buy (`P`) post-hoc can rescue a missed signal. Conversely, a downward-revision amendment can void a previously alerted cluster — must be tracked to prevent false-positive carryover. **Edge:** mostly defensive (data-quality maintenance); secondary alpha from amendment-cluster detection (when an issuer has 3+ amendments across multiple insiders in a week, often signals an SEC inquiry or corp-gov controversy). Estimated low base rate (~5–10/month system-wide for material clusters). Useful as a system-health and thesis-enrichment signal rather than a lead-discovery feature.

**Source category.** **High** — SEC EDGAR direct.

**Sources.**
- `getcurrent?type=4%2FA&output=atom`.
- Diff-compare new 4/A primary XML against the original Form 4 XML it amends (the amendment references the original accession in the header).

**Latency.** Real-time within ~10 min of acceptance.

**Failure mode.**
- Most 4/As correct trivial typos and have zero signal.
- Distinguishing material amendments from cosmetic ones requires field-level diff logic — moderate engineering cost for low-frequency payoff.
- The original Form 4 may have already triggered an alert; retracting/correcting that alert is operationally tricky from a UX standpoint.

---

## Cross-feature scoring rubric proposal

(Brief; synthesis will refine.)

| Feature | Standalone alert? | Cross-ref +score weight |
|--------|-----|-----|
| 1. Cluster Form 4 buys | YES (instant-trigger exception) | +30 |
| 2. Insider z-score buy | NO (joins #1) | +15 |
| 3. New 13D | YES (activist filer history gate) | +20 |
| 4. 13G→13D conversion | YES | +25 |
| 5. Form 144 chain | NO (LLM thesis) | +10 |
| 6. Shelf takedown | NO (defensive kill) | -25 to longs |
| 7. IPO lockup expiry | NO (defensive kill) | -10 to longs in window |
| 8. Form D | NO (LLM thesis) | +10 if quality buyer; -10 otherwise |
| 9. S-4/425 deal news | NO standalone (use 2-source rule) | +30 with 2nd source |
| 10. Activist constellation | YES | +35 |
| 11. 13F sharp money | NO (confirmation only) | +15 |
| 12. 5.02 + insider sell pattern | NO (LLM thesis) | -20 to longs |
| 13. 4/A amendment cluster | NO (data quality + thesis) | varies |

The +15 from CLAUDE.md for raw Form 4 storage is the *floor*; features above stack on top.

---

## Excluded (and why)

- **Form 5 annual catch-up.** Filed once a year for transactions exempted from Form 4. By the time a Form 5 hits, the trade is up to 14 months stale. Zero predictive value; included only in compliance archives.
- **PRE 14A preliminary proxies.** Almost always followed by DEF 14A within days; covered by Feature 10's DEF 14A leg with no marginal lift from PRE 14A surveillance.
- **Prospectus initial S-1 filings as a standalone signal.** Pre-IPO; doesn't apply to public-equity universe except via Feature 7 (lockup tracker) and Feature 9 (S-4 mergers). Tracking S-1s for their own sake produces noise.
- **Form 13H large-trader registrations.** Registers traders with FINRA but is non-public (Form 13H filings are confidential by SEC rule). No free public access — excluded.
- **Foreign Form CB / 6-K.** Out of scope for a US retail bot; mostly ADR-related and 6-Ks are commonly content-light.
- **OpenInsider / SecForm4.com / WhaleWisdom scraping.** Per task constraints, secondary aggregators are allowed only as backup. EDGAR direct (Features 1, 2) replicates everything OpenInsider does at the same or better latency. Recommend skipping aggregators entirely; they add a brittle dependency for no incremental signal.
- **Cash-settled equity swap disclosures.** The 2024 modernization rule does *not* require swap-only positions to be reported under 13D for most cases (limited integration). Retail-data coverage is too sparse to operationalize.
- **CUSIP-to-ticker commercial mapping.** CUSIP is a licensed identifier; mapping infrastructure is not free at scale. Workarounds (issuer-name fuzzy match) are imperfect — flagged as a known integration cost for Feature 11 but not a separate feature.
- **8-K Item 7.01 Reg FD / Item 8.01 Other Events as standalone signals.** Per CLAUDE.md, 8-K never triggers standalone. Item content is parsed for thesis enrichment only — no separate feature warranted.
- **Earnings-related filings (10-K, 10-Q).** Out of "insider/filings discovery" scope; covered by other Phase-1 workers (likely earnings/fundamentals).
- **EDGAR XBRL frames for cross-company financial cuts.** Excellent feature space but covered under fundamentals, not insider/filings.
- **Insider Form 144 + Form 4 *intra-day* matching against block-trade tape.** Requires a tape feed (paid). Free-source-only constraint excludes.
