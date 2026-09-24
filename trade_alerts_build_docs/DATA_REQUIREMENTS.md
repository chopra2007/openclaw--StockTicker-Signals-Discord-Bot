# DATA_REQUIREMENTS.md

## 1. Purpose

Canonical specification for market, options, reference, catalyst, and research data required by the system.

It defines required fields/resolution, live vs historical needs, confirmed/provisional access, proxies, degraded behavior, blockers, live collection, and paid-data decision rules.

## 2. Status Vocabulary

- `CONFIRMED`
- `PROVISIONAL`
- `NEEDS VALIDATION`
- `BLOCKED BY DATA`

Feasibility classes:
- A: readily available
- B: available with limitations/proxy/uncertain history
- C: additional infrastructure/paid/difficult history
- D: unavailable/impractical/not justified

## 3. Known Project Data Context

### Schwab API
Historical account access and real responses are `CONFIRMED` through saved
collector files dated 2026-08-31 through 2026-09-10 Pacific. Current entitlement
and token health are `NEEDS VALIDATION`: the last dated collection, 2026-09-11,
stopped with no option files and no stock bars. This offline audit did not read a
credential, call the provider or infer the cause.

Field-level implementation requires audit:
- auth
- historical price
- L1 streaming
- charts
- options chains
- Greeks/OI/volume
- time-and-sales
- depth/book
- rate/subscription limits

### Existing repository
`CONFIRMED`:
- Openclaw/server
- Discord
- stock/options analytics
- unusual-options feature

Source implementation has been inspected; the capability register in §31 and PREBUILD_REVIEW separates code support from current provider access and historical coverage.

### Cost preference
1. existing connected data
2. existing broker data
3. free authoritative/public
4. free proxies
5. paid only when evidence justifies

## 4. Canonical Data Quality

Every important live object should distinguish:
- VALID
- STALE
- UNAVAILABLE
- DEGRADED_PROXY
- INVALID

Never use numeric zero to mean unavailable if zero is a valid value.

## 5. Timestamps

Where feasible preserve:
- source_timestamp
- received_timestamp
- normalized_timestamp
- feature_timestamp
- evaluation_timestamp
- alert_timestamp

Catalysts must distinguish event time from receive time.

## 6. Core Equity/ETF Data

### Daily OHLCV
Fields: symbol, date, O/H/L/C, volume, corporate-action metadata where possible.

Need >=20 completed sessions for ATR/liquidity warm-up; more preferred.

Status: `PROVISIONAL`, feasibility A.

### 1m OHLCV
Need timestamp, O/H/L/C/V, premarket where possible, regular session.

Status: `PROVISIONAL`, feasibility A/B.

Required by all eight strategies.

### Premarket OHLCV
Derived:
- PM high/low
- PM volume/dollar volume
- PM RVOL
- PM range

Status: `PROVISIONAL`, A/B.

Important for #1/#6/#7.

## 7. Live L1 Quotes

Fields:
- bid/ask
- sizes
- last
- last size
- timestamp

Derived:
- mid
- spread
- spread %
- spread bps
- quote age

Live status: `PROVISIONAL` via Schwab, A/B.

Historical L1/NBBO: C unless existing source discovered.

All actionable strategies benefit.

## 8. Time-and-Sales

Ideal:
- timestamp
- price
- size
- venue/condition where available

Derived:
- trade count
- intensity
- acceleration
- sub-minute acceptance

Live: `PROVISIONAL`, B. Historical: C.

Optional enhancement, not core blocker.

Approved fallback:
- projected current 1m volume ratio
- L1/bar acceptance

## 9. Level 2 / Depth

Potential:
- multi-level bids/asks
- sizes
- venues
- timestamps

Role:
- optional modifier
- human confirmation
- future ablation

Not a core dependency.

Live: B/C provisional. Historical: C/D / blocked.

Do not delay core project for L2.

## 10. Order Flow / Delta

True order-flow imbalance requires trade classification/depth.

Status: `BLOCKED BY DATA / OPTIONAL`, C.

Not mandatory for any core strategy.

## 11. Options Data

### Chain metadata
Need underlying, contract symbol, call/put, expiry, strike, DTE.

Project/provider-level access confirmed; field implementation provisional.

### Bid/ask
Need bid/ask/timestamp, mid/spread.

Live A/B provisional. Historical C.

### Volume / OI / IV / Greeks
- volume: A/B provisional
- OI: A/B current; B/C historical point-in-time
- IV: A/B live; C historical
- Greeks: A/B live; C historical

### Historical OPRA-quality data
`BLOCKED BY DATA` unless audit finds an existing source.

Do not block underlying validation.

Always separate underlying edge from option execution validation.

## 12. SPY / QQQ / Sector

Need ordinary 1m/L1/VWAP/ATR/session returns for SPY/QQQ.

Sector ETF baseline:
- XLK
- XLF
- XLY
- XLC
- XLI
- XLV
- XLP
- XLE
- XLU
- XLRE
- XLB

Need symbol→sector mapping.

Status: provisional; feasibility A/B.

## 13. VIX

Spot VIX useful modifier. A/B provisional.

VIX term structure optional, B/C; do not add futures infrastructure solely for it.

## 14. Market Breadth

### Full constituent breadth
Desired for SPY/QQQ:
- return from open
- above/below VWAP
- short-window return
- volume/up-volume proxy
- valid quote

Derived:
- advance ratio
- above-VWAP ratio
- positive-return ratio
- volume breadth

Current status: `BLOCKED BY DATA` until streaming/history/membership verified.

### Point-in-time membership
Required for unbiased historical full breadth. Currently blocked.

### Sector breadth proxy
Approved initial fallback:
- 11 sector ETFs
- optionally major constituents

Every #5 alert stores `breadth_mode`:
- SECTOR_PROXY
- FULL_CONSTITUENT
- HYBRID

## 15. Catalyst / News

### Minimum schema
- symbol
- event_timestamp
- received_timestamp
- source
- headline
- event_type
- structured fields
- classification
- confidence

### Low-latency feed
Critical for faithful #7.

Current status: `BLOCKED BY DATA`.

Free/public sources may help context but require latency/completeness validation.

Fallback:
- #1/#6 may use abnormal price/volume + `UNKNOWN` if playbook permits
- #7 remains SHADOW_DEGRADED / DISABLED / BLOCKED without reliable catalyst feed

## 16. Earnings / Macro / Halts

### Earnings
Calendar likely provisional. Real-time structured surprise/guidance: blocked/needs validation.

### Macro calendar
Need CPI/FOMC/NFP/major scheduled events; A/B provisional.

### Halts
Strongly preferred for single-stock strategies. Live A/B provisional.

Known halt → suppress actionable alerts.

## 17. Corporate Actions / Historical Universe

Need splits, reverse splits, symbol changes, mergers, delistings for historical integrity.

Survivorship limitations must be documented when delisted/inactive symbols unavailable.

## 18. Volume Profile

### True trade-level
Ideal for #8; historical status `BLOCKED BY DATA`, C.

### 1m approximate profile
Approved fallback, feasibility A.

Current frozen research inputs and separation rules are in §56 under
`M03I_VP_ACCEPT_LVN_V1`.

Every profile stores:
- TRUE_TRADE_PROFILE
- BAR_APPROX_PROFILE

Never pool without segmentation.

## 19. Auction Imbalance / Direct Depth

Optional only.

Not initially justified. Do not block core strategies.

## 20. Candidate External Providers

### Schwab
Primary existing provider; field-level audit required.

### Existing repository sources
First reuse priority.

### Other market-data providers
May be evaluated only if a specific gap is demonstrated.

Examples such as Alpaca, Databento, or direct exchange feeds are candidates, not approvals.

No paid provider is automatically authorized.

## 21. Strategy Data Matrix

| Data | #1 | #2 | #3 | #4 | #5 | #6 | #7 | #8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1m OHLCV | M | M | M | M | M | M | M | M |
| Daily OHLCV | M | M | M | M | M | M | M | M |
| Premarket | M | O | O | O | O | M | M | O |
| L1 | M | M | M | M | M | M | M | M |
| VWAP/ATR | M | M | M | M | M | M | M | M |
| RVOL | M | M | M | M | O | O | M | M |
| SPY/QQQ | O | M | O | M | M | M | O | O |
| Sector | O | M | O | M | P/M | M | O | O |
| Tape | O | O | O | O | O | O | O | O |
| L2 | O | O | O | O | O | O | O | O |
| Options | O* | O* | O* | O* | O* | O* | O* | O* |
| Catalyst | O/P | O | O | O | O | O/P | B | O |
| Full breadth | — | — | — | — | B/P | — | — | — |
| True trade profile | — | — | — | — | — | — | — | B/P |

\* mandatory only for option recommendation, not underlying validation.

## 22. Minimum Faithful Strategy Data

### #1
1m, premarket, daily, L1, VWAP, ATR, RVOL, OR. Implementable with expected current data pending audit.

### #2
1m, L1, VWAP, ATR, RVOL, benchmark/sector. Implementable pending audit.

### #3
1m, L1, OR, VWAP, ATR. Sub-minute acceptance may degrade to proxy.

### #4
1m, L1, VWAP, ATR, RVOL, benchmark. AVWAP optional.

### #5
Opening drive implementable. Full breadth blocked; proxy mode allowed.

### #6
Price structure implementable. Catalyst quality degraded/unknown without news.

### #7
Price structure implementable, faithful catalyst strategy blocked until data source exists.

### #8
Approx profile implementable; true trade profile blocked.

## 23. Live Collection

Always during strategy window:
- 1m OHLCV
- live L1
- SPY/QQQ
- sector ETFs
- strategy features
- state transitions
- suppressions

Premarket:
- PM high/low/range/volume/dollar volume/RVOL/gap context

Candidate-centered high-resolution capture is approved as a provisional design:
- broad universe 1m + L1
- WATCHING/SETUP_FORMING symbols can receive higher-frequency capture

For actionable alerts persist option snapshots where enabled.

For #5 persist breadth mode/components/coverage.

For catalyst events persist source/headline/event/received/classification.

## 24. Historical Priority

Tier 1:
- daily
- 1m
- premarket
- SPY/QQQ
- sector ETFs

Tier 2:
- L1/alert-centered quotes
- options snapshots
- halts
- macro calendar

Tier 3:
- catalyst timestamps
- full breadth
- point-in-time constituents

Tier 4:
- ticks
- historical NBBO
- OPRA
- depth
- true volume-at-price

Acquire Tier 4 only if evidence justifies.

## 25. Alert Reconstruction

For every actionable alert preserve enough to answer:

> What did the system know at the time?

At minimum:
- quote
- recent bars/references
- important features
- market context
- state
- trigger/stop/targets
- confidence factors
- data modes
- option snapshot
- catalyst/breadth/profile snapshot where relevant

## 26. Data Health

Per provider track:
- last event
- age
- disconnect/reconnect
- missing bars
- invalid records
- subscription/rate-limit errors

Options:
- chain completeness
- missing bid/ask/Greeks

Breadth:
- expected count
- valid count
- coverage ratio

Mandatory stale data suppresses actionable alerts.

## 27. Historical Limitations

Same 1m bar stop+target:
- UNKNOWN
- conservative stop-first
- or higher-resolution resolution

No historical spread:
- use conservative sensitivity model
- label `NO HISTORICAL NBBO`

No historical option data:
- validate underlying only
- do not claim historical option returns

## 28. Paid-Data Decision Framework

Before recommending paid data answer:
- which strategy requires it?
- exact missing field/history?
- existing proxy?
- proxy weakness?
- evidence strategy is promising?
- specific hypothesis answered?
- historical data needed?
- live-only enough?
- operational burden?
- BUY / CONSIDER / NOT JUSTIFIED?

Initially not justified:
- full historical L2
- direct exchange depth
- large-scale OPRA
- premium NYSE TICK
- institutional auction history
- large true profile dataset

Potentially valuable later:
- reliable real-time catalyst feed
- full breadth history
- historical NBBO/OPRA
- trade-level history

## 29. Blocker Summary

| Data | Status | Impact | Current Action |
|---|---|---|---|
| Low-latency catalyst | BLOCKED | #7 | disable/degraded shadow |
| Catalyst received-time history | BLOCKED | #7/#1/#6 research | no faithful historical claim |
| Full point-in-time breadth | BLOCKED | #5 | sector proxy |
| Point-in-time membership | BLOCKED | #5 | proxy / bias label |
| Historical L2 | BLOCKED | optional | deprioritize |
| Historical NBBO | BLOCKED unless found | execution | conservative model |
| Historical OPRA | BLOCKED unless found | options | separate underlying |
| True volume-at-price | BLOCKED | #8 | 1m approximation |
| NYSE TICK | BLOCKED | optional | omit |
| Borrow data | PARTIAL / NEEDS VALIDATION | executable short-stock research | reuse mapped current shortability/borrow fields; historical availability and fees remain unverified |

## 30. Definition of Done

Data layer sufficient for #1–#4 when:
- daily OHLCV
- 1m regular session
- premarket status known
- live L1
- SPY/QQQ
- sector ETFs
- options chain
- option bid/ask status known
- timestamps normalized
- stale detection
- replayable history
- data-quality states
- source metadata

No strategy may silently assume `UNKNOWN = AVAILABLE`.

## 31. Repository capability register — 2026-09-05 Pacific

Evidence levels here are independent of approval: `CODE` means the mapping exists; `TEST SOURCE` means relevant tests were inspected; fresh offline results are recorded in PREBUILD_REVIEW. None proves current entitlement, live coverage, or latency.

| Required data | Existing source and exact limit | Required extension / validation |
|---|---|---|
| Daily and one-minute bars, extended hours | `consensus_engine/scanners/schwab_client.py:get_price_history` maps requested intervals and extended hours into OHLCV. | Preserve adapter reuse; verify returned session coverage, bar start/end and publication semantics, revisions, adjustment basis, minute warm-up and historical depth. A request parameter is not proof the requested history is returned. |
| Stock bid/ask, trade/quote time, halt and borrow fields | `schwab_client.py:_map_quote`, `get_quotes` expose these fields. The legacy `c` field prefers the regular-session last price. | Add a compatible canonical mapping with session-specific last-price semantics and explicit delayed status. Preserve separate quote/trade timestamps and missingness; do not reinterpret the old field for existing callers. Current and historical short availability are separate evidence questions. |
| Option contracts and quotes | `schwab_client.py:_chain_map_to_df`, `get_option_chain` preserve exact contracts, expiry, bid/ask, provider quote time, sizes, OI, IV, Greeks, multiplier, non-standard status and delayed-chain flag. | Reuse mapping. Reject stale/crossed/missing mandatory quotes, retain OI as-of date, and test contract completeness, underlying time alignment, non-standard deliverables and expiry policy. |
| Forward snapshots | `scripts/full_chain_collector.py:capture_stock_poll`, `capture_option_poll`, `verify_day`; `config/full_chain_collector.yaml`. The configured trade universe has 20 stocks; stock context has SPY/QQQ/XLK/SMH. Options use four nearest expirations and a 15% strike band. | This is bounded collection, not all-market coverage, all 11 sectors, a guaranteed 0–7-day chain, or ten-second acceptance history. Reuse capture and storage where suitable; inspect dated files and per-symbol coverage before using them. |
| Streaming / tape / depth | No live broker probe was permitted. Existing request adapters and a stream-capable dependency alone do not establish these feeds. | M0.2 must record official field definitions, actual subscription/access evidence, cadence, coverage and limits; affected faithful modes remain unverified. |
| Catalyst / macro / halts | Existing readers provide context, calendars and halt checks; a news reader does not prove a complete low-latency catalyst feed with original receive history. | Preserve #7 faithful-mode blocker. Test publication, receive, revision and classification availability separately; map macro/halt missing-data policy before actionable use. |
| Approximate volume profile and sector mapping | `alerts/all_command/levels.py:extract_volume_profile_levels` contains a descriptive candle-based profile; `analysis/wolf_scope.py:stock_sector_etf` maps current sectors. | Reuse suitable arithmetic/mapping behind contracts; existing profile parameters are not approved #8 rules, and current sectors are not historical membership. |
| Full breadth / true volume profile / historical option execution | No complete project-ready dataset was established by this review. | Retain full-mode blockers, approved labeled proxy modes, and separate historical-options validation. Do not promote an old blocker into a global claim that no data exists. |

Section 44 is the current M0.2 audit. It adds later saved output and current
machine limits without erasing this earlier source inspection.

## 32. Time, fidelity and coverage contract

Each normalized record carries source identity, instrument identity, source time, receive/available time, session, sequence where present, quality and revision. Bars also carry start, end, final/provisional state, price/volume convention, and adjustment basis. Feature evaluation uses only records available by the evaluation time. Later corrections are new revisions, never silent changes to alert-time facts.

Quotes have distinct bid/ask and last-trade ages. Re-reading a cache does not refresh provider time. Delayed, stale, crossed, missing or mismatched-session data cannot satisfy a mandatory live gate. Batch stock requests followed by sequential option calls are not simultaneous; persist individual times and test the permitted skew. Numerical age/skew/coverage budgets are explicit M0.2/M0.3 contracts, not guessed here.

Record source-specific bar semantics. For example, Databento documents start-stamped bars and omits intervals with no trades. Its daily aggregates use calendar-day boundaries rather than guaranteeing the required regular-session daily bar. Therefore adapter tests must distinguish missing data from a known no-trade interval and must not expose a final bar at its start time. These are provider-specific facts, not assumed Schwab behavior. [Official bar documentation](https://databento.com/docs/schemas-and-data-formats/ohlcv).

For every universe and provider, retain coverage by symbol/session, expected and observed intervals, gaps, duplicates, corporate actions, delistings, data mode and original availability. For same-time RVOL use only prior completed reference sessions under the approved definition. Do not patch a missing numerator or denominator with zero. Restricted venue data is not automatically consolidated volume; comparison windows must use a compatible coverage basis.

## 33. Provider capacity and reopening gates

Before live collection or shadow, M0.2 records a shared request/subscription budget for existing commands, background scans, research collectors and the new runtime, plus queue, timeout, retention, disk and memory budgets. Reuse authentication and shared request control; a per-process limiter is not a cross-process account budget. Give interactive requests and actionable freshness explicit priorities. If a budget cannot support a required mode, retain the mode as blocked and document the capacity remedy.

The public Schwab documentation page returned navigation without field-level content during this review. Account entitlements, numeric limits, subscription behavior, streaming/tape/depth support and history depth remain `NEEDS VALIDATION`; no community assertion substitutes for official/account evidence. [Official developer documentation](https://developer.schwab.com/products/trader-api--individual/details/documentation/Market%20Data).

Each blocker requires: affected playbooks/mode, exact missing fields and dates, evidence, existing/free route, any paid alternative with unverified cost explicitly marked, fidelity difference, decision owner, next milestone and measurable reopening test. Existing proxy approval permits only that labeled mode; it never approves an unspecified proxy calculation or a new purchase.


## 34. Approved M0.3A research inputs and testing allowance

D-090, approved by the owner on 2026-09-05 Pacific, incorporates [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md) version `M03A_ORB5_V1` §§2–5 within this document's data authority. F-01/F-02/F-03 and B-02 specify the exact shared windows, named VWAP estimate and projected-quote research inputs. Formula approval is distinct from verified source coverage, trade-condition rules and complete data access; those evidence gates remain open.

The approved windows require consecutive scheduled sessions/intervals, separate event/availability times, compatible price/volume adjustments, and complete source/venue coverage. Never substitute older references for a missing required session, silently mix providers, or combine adjusted prices with incompatible raw volume. Keep a just-ended bar awaiting finality distinct from confirmed coverage loss. One-minute final bars cannot recreate ten-second acceptance or current-minute projections.

M0.2 still owns proof of the histories, premarket, tape conditions/corrections, valid price increments, corporate actions and executable quote coverage. Existing/free data is the first route. The owner separately authorized up to **$25 total Databento credit usage for testing** under D-091. Use the cumulative ledger in DECISIONS §31; the allowance does not reset per test, agent or session. That historical cap is superseded for current Databento build API usage by the saved authority in §48. This recording change made no provider request and used $0 of that allowance. No data fidelity or completeness claim follows from the spending permission.

## 35. M0.3B proposed data contracts and first-build limit

[M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md) §§2–3 defines proposed bar-profile/swing/AVWAP, catalyst/macro, full-chain, quote/Greek timing and same-day membership requirements. They remain proposed until adoption; writing fields does not prove source coverage. Full and approximate modes remain distinct. The minimum shared bar-profile producer, if adopted, belongs before Strategy #1 at M3.5/M4.3; Strategy #8/M13 still owns its full strategy and full-fidelity completion.

Existing local one-minute file metadata supplies a possible research source, not proof of ten-second triggers, consolidated volume, point-in-time membership, executable quotes or current provider access. M0.2 must measure those facts before the dependent mode. FIRST_BUILD_SESSION's M0.4 uses synthetic records only, so no Databento request or new access is needed. At that preparation, D-091's cumulative ledger was the spending authority and the preparation used $0; current authority is in §48.

## 36. M2.1 offline normalization and remaining source evidence

M2.1's bounded contract is CODING_STANDARDS §58, with tested evidence in
[M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md). Raw Schwab-shaped response pieces
are mapped into the existing canonical bar, quote and option records before
legacy conversions can lose missingness or timestamp precision. This is a local
mapping contract; §31's provider access and coverage evidence levels do not change.

Preserve original source, receipt, availability and normalization times. Keep
quote and last-trade times separate; a newer trade does not refresh the bid/ask.
Options retain each contract's own times and enclosing chain delay context.
Unknown OI publication time, size/Greek units, adjustment basis and bar finality
remain explicit. A supplied status or synthetic response cannot prove freshness,
correct session, chain completeness, simultaneous stock/option capture or current
provider entitlement. No source fallback occurs inside these pure functions.

The raw candle timestamp is a source fact, not proof of an interval boundary.
M2.2 must establish start/end/publication conventions, requested versus observed
daily/minute/premarket/session coverage, missing intervals, corrections and
adjustment compatibility. Incomplete candles are rejected rather than fabricated
as zero-volume/no-trade intervals. Streaming shapes, transport, reconnects and
dynamic staleness remain M2.3. M0.2 still owns actual source/units/capacity evidence;
M14.2 owns full option quote and underlying-alignment policy. All existing
full-data blockers, approved proxies and D-091's cumulative ledger remain intact.

## 37. M2.2 historical coverage implementation and unchanged data gates

[M2_2_VERIFICATION.md](./M2_2_VERIFICATION.md) records an offline request/coverage
interface. Section 11 records fresh supervisor proof for the §10 repair: 424 tests
passed in each of two protected runs. Section 9 remains historical. Unknown evidence-reference
labels cannot establish complete coverage. This does not upgrade §31's source evidence. Requested
daily/minute/premarket/regular intervals are separate from observed records. Availability, finality, revisions, source timestamps, adjustment,
price/volume units, venue coverage and session convention remain explicit. Missing
observations are unknown; only separately certified no-trade records have zero
volume with no invented prices. Calendar-day daily data cannot silently become a
regular-session daily bar. Mixed adjustments, sources or data modes cannot imply
complete compatible coverage. The new raw-response path has no automatic fallback.

M0.2 still needs a separately authorized supervised source check: dated raw
responses and per-symbol/session coverage for daily, one-minute, premarket and
regular hours; exact interval/publication/finality and correction conventions;
price/share adjustment and venue basis; history depth, corporate actions,
renames/delistings and original availability. Neither old local file counts nor
synthetic test inputs close those gates. Existing Schwab/local/free evidence is
the first route. No purchase is needed for this software contract; any remaining
data purchase must name fields/dates/fidelity and a verified cost under the
existing cumulative D-091 ledger before a separately authorized supervised step.
This unattended attempt read no credential and made no paid or live request.


## 38. M2.3 offline event handling and unchanged live-data gates

The offline Quote event prerequisite is implemented under CODING_STANDARDS §60;
fresh protected execution of the review repair is pending in
[M2_3_VERIFICATION.md](./M2_3_VERIFICATION.md) §11. Sections 8/10's earlier results
are historical. Missing, wrong-session or same-session pre-recovery source time
cannot leave an earlier healthy quote usable when quote/trade timestamps repeat.
A source time after original availability remains visibly invalid even after the
clock catches up. Cache repeats cannot heal retained rejected data. Quote and last-trade ages use their own original timestamps. Duplicate cache
reads do not renew source time or fill observation gaps. Missing/delayed/invalid
inputs and lost continuity block forwarding. Reconnect needs separately supplied
coverage/warm-up evidence for the current recovery epoch and a fresh snapshot.
All test limits and evidence labels are explicitly synthetic; no live age, cadence,
subscription or coverage policy has been chosen.

The §31 provider evidence level is unchanged. Full M2.3 still needs official raw
stream field and partial-update semantics, current entitlement/subscriptions,
authentication refresh/resubscription proof, measured source/quote/trade timing,
missed-input recovery/warm-up and shared request/queue/storage/capacity budgets.
REST fixtures prove none of those facts. A supplied continuity label is not an
external source audit. M2_3_VERIFICATION §7 saves the exact supervised reopening
test. Existing local/source evidence comes first; purchases remain separately
supervised under the cumulative D-091 ledger. This session uses $0.

M2.4's proposed next offline supplied-reference contract can preserve explicit
missing SPY/QQQ/sector/VIX inputs. It cannot certify current reference coverage,
point-in-time sector membership or full breadth. Existing current sector mappings
are reusable identity facts only. All data-dependent modes retain their owners.


## 39. M2.4 offline references and required source gate

[M2_4_VERIFICATION.md](./M2_4_VERIFICATION.md) records the supplied-reference
implementation awaiting protected tests. It expects SPY, QQQ and all 11 sector
ETFs independently. Current quotes, requested bar coverage, modes, times and
missingness are separate per symbol. Quote/history counts are explicitly
SUPPLIED_RECORDS_ONLY. No current provider evidence level in §31 is upgraded.

The existing stock lookup is current context only. It has 10 distinct values,
including broad-market references; it is not a complete 11-sector feed or dated
membership. Unknown stocks remain unknown. VIX is explicitly unavailable: current
canonical record types and event handling lack a supported index input contract.
A text alias or a broker symbol spelling alone cannot supply VIX semantics.

Required M2.4 source completion is **BLOCKED BY DATA / supervised access**. Section 7
of that evidence record names the exact inputs and reopening test: dated per-symbol
SPY/QQQ/all-sector L1 and minute/history coverage, source/time/delay/finality and
adjustment evidence, supported official spot-VIX identity/type/field/session
semantics, historical sector membership where required, and shared capacity under
M0.2/M2.3. Use existing local/Schwab/free evidence first in a separately authorized
supervised step. Missing data blocks its dependent mode; synthetic cases do not
close that gate or full breadth. No purchase is needed for this offline interface.
Any later purchase requires named fields/dates/fidelity and verified bounded cost
under the cumulative D-091 ledger. Usage and reservations remain $0.

ROADMAP §31 and M2.3 §12 supersede §38's pending-repair status; M2.3's offline
proof was finalized. Its full live branch stays blocked. M2.4 is now the assigned
offline work. Proposed next independent software work is M3.1 after its protected
proof/review, with full trade VWAP and all source evidence gates retained.

## 40. M3.2 participation inputs and unchanged source gates

[M3_2_VERIFICATION.md](./M3_2_VERIFICATION.md) records three supplied-Bar
participation calculations awaiting protected execution. They require compatible
share units and source/venue/adjustment basis, exact calendar reference sessions,
original availability and finality. Synthetic records do not change any current
provider evidence level in §31. General same-time/cumulative RVOL still needs
its own adopted definition; D-090's two fixed-window ratios do not define it.

The approved tape-intensity and projected-minute formulas retain their input
gates: complete eligible trade shares/conditions/cancels/corrections and matching
20-session intervals; or a verified minute-start counter, reset/correction
semantics and complete intraminute share coverage. Final minute Bars supply
neither path. Actual current and 20-prior-session opening/premarket/daily
coverage also remains unverified. Required reopening proof and the existing-source-
first supervised route are M3_2_VERIFICATION §5. No purchase is needed for the
offline calculations; D-091 remains $0 used and $0 reserved.

## 41. M3.6 opening-range inputs and unchanged source gate

[M3_6_VERIFICATION.md](./M3_6_VERIFICATION.md) §12 records completed offline
implementation and protected proof for the supplied-Bar five-minute opening range.
Both supervisor runs passed 665 tests, including all 28 M3.6 cases. This completes
the offline proof only; the actual-source gate below remains blocked. The
calculation needs exactly the five regular-session one-minute intervals starting at the scheduled
open, with original availability, finality, revision, missing/no-trade, source,
mode, price/share units, adjustment and eligible-venue basis preserved. Synthetic
records do not change §31's provider evidence level. The original history request
must cover all five intervals; archived opening Bars outside a truncated or
disjoint request cannot establish complete requested coverage.

Required source completion remains **BLOCKED BY DATA / supervised access** under
M0.2/M2.2. Reopening requires dated per-symbol raw and normalized opening minutes,
including late publication, missing/no-trade handling, correction/cancel behavior,
price/share adjustment and venue eligibility, and proof that the five scheduled
intervals are complete on normal, clock-change and shortened sessions. Run those
actual records through the same feature path and retain per-interval coverage.
Use existing local/Schwab/free evidence first. No purchase is needed for the
offline calculation; D-091 remains $0 used and $0 reserved.

## 42. M4.3 supplied geometry and unchanged full-source gate

[M4_3_VERIFICATION.md](./M4_3_VERIFICATION.md) records offline risk/target
calculations with completed protected offline proof. Their inputs are canonical features
with original identity, availability, units, definition and references; a supplied
price-basis label identifies compatible source/venue/adjustment assumptions.
A complete supplied anchor-path or catalog-coverage label proves no actual feed.
No provider evidence level in §31 changes.

Full required M4.3 remains blocked by unadopted full structural producer/
applicability/priority rules and actual input evidence: the final anchor minute
and complete crossing-to-trigger path, trade eligibility/cancels/corrections,
valid increments, compatible PM/prior/OR/ATR/AVWAP/profile/other-structure levels,
and per-family original availability/coverage. Soft invalidation and runner
behavior still need applicable adopted definitions. Missing a family cannot mean
no obstacle exists. M0.3B remains proposed; no ATR multiple or profile/AVWAP rule
is inferred from the supplied selector.

Exact owners and reopening evidence are in M4_3_VERIFICATION §4. Reopen with
adopted definitions plus separately supervised dated source/path/family proof
through the same calculations, using existing local/Schwab/free evidence first.
No purchase is needed for this offline work. Any later purchase needs named
fields/dates/fidelity and verified bounded cost under D-091 in a separately
authorized step. This unattended lane makes no charged or live request; usage
and reservations remain $0. Passing synthetic cases cannot close the source gate.

## 43. M4.4 supplied score inputs and unchanged source gates

[M4_4_VERIFICATION.md](./M4_4_VERIFICATION.md) records the offline supplied
confidence composition with completed protected proof. Canonical feature snapshots
retain original source, identity, definition, mode, availability and ancestor
references. Declared scores/contributions must describe the current evaluation;
old calculations and missing factors cannot become favorable current data.
These supplied score records do not change §31's provider evidence levels.

Full confidence production still needs adopted factor transformations, roster,
missing-factor and freshness rules, plus actual compatible point-in-time source
and correction/coverage evidence. Exact owners and reopening proof are
M4_4_VERIFICATION §4. Synthetic input IDs are not proof that raw records exist;
M5 retains durable input/candidate linking. Current sector maps, unknown catalysts
or unavailable market context cannot silently become complete confidence factors.

Use existing local/Schwab/free evidence first in a separately authorized supervised
step after dependent definitions are settled. Any purchase needs named missing
fields/dates/fidelity and verified bounded cost under D-091. This offline slice
requires no purchase; usage/reservations remain $0 and no live access occurs.

## 44. M0.2 current capability audit — 2026-09-13 Pacific

This is the bounded offline result from source code, offline test files, saved
provider output and local file metadata. It makes no live request and does not
turn on any trade-alert path. Four evidence levels stay separate:

- **Code:** a reader, mapper or collector exists.
- **Offline tests:** stored or made-up inputs exercise that code. They do not
  prove a current outside feed.
- **Observed output:** a dated local file contains fields returned during an
  earlier collection.
- **Current access and coverage:** whether the account can obtain every required
  field, symbol and interval now. A past file cannot prove this.

The machine-readable findings and preserved controller proof references are in
[M0_2_CAPABILITY_AUDIT.json](./M0_2_CAPABILITY_AUDIT.json). The first local audit
hit `PermissionError: [Errno 13] Permission denied` while reading its login file;
its alternate-user attempt returned `runuser: cannot set groups: Operation not
permitted`. These remain historical sandbox failures, not an account-access
finding. A separately assigned source task at 21:09 Pacific on 2026-09-13 made
exactly two free successful Schwab market-data GETs: a SPY quote and a restricted
SPY option chain, both HTTP 200. It made no retry, token refresh/persistence,
account/order request or purchase. This record repair made no provider call.

The chain slice contained 20 contracts (10 calls and 10 puts) over September
14–18, five expirations, with bid/ask, sizes, volume, OI, IV, five Greeks,
multiplier and quote/trade time fields. It is bounded current read-access proof,
not full-chain or full-entitlement proof. `realtime=true`, `isDelayed=false`,
underlying `delayed=false` and `isChainTruncated=false` were observed. Assuming
integer times are epoch milliseconds, the stock quote fields date to Friday
September 11 at 16:59:59.596 Pacific, and option quote fields to September 11
13:14:59.419–13:15:00.091 Pacific. Those fields remained stale on Sunday.
Extended stock fields showed Sunday times; they do not refresh the Friday quote
fields. Official time/size units, NBBO fidelity (the best bid and ask across
venues), full entitlement, continuity, historical execution and profit remain
unverified. Delay flags do not establish freshness.

Private source proof is retained under
`/root/trade-alerts-builder/repairs/codex-subscription/schwab-current-source-check/`:
`REPORT.md`, `result.json` and `verification.json`. The last verifies response
hashes, contract counts, date bounds and the two-call limit. Public records
contain no credentials or account identity.

### 44.1 Capability result

| Required data | Code and offline-test support | Dated observed output | Current access, coverage and faithful mode |
|---|---|---|---|
| One-minute OHLCV | `schwab_client.get_price_history` and the M2.1/M2.2 mapping and coverage code support one-minute requests. Offline cases cover requested regular/premarket windows, missing intervals and available-time views. | Eight `stock_bars` files from 2026-08-31 through 2026-09-10 contain 12,915–13,212 rows per day for the configured 25-name stock universe. The saved rows have timestamp, ticker and OHLCV. | `NEEDS VALIDATION`. The files prove a narrow forward sample. Separate verified ETF and selected60 minute inventories are recorded in §44.2; none proves required finality, revisions, eligible venues, split/dividend basis or all strategy symbols. The 2026-09-11 daily run saved zero bars. |
| Premarket | The history request can set extended hours, and the collector requests 04:00–17:01 Pacific. Offline tests prove only request shape and explicit missingness. | The same eight files include extended-hours rows for all 25 configured names. Against the 150 scheduled minutes from 04:00 through 06:29 Pacific, only one name has all 150 minutes on every saved date. Observed name/date counts range from 0 to 150. | `NEEDS VALIDATION`. The saved gaps are explicit; a source-backed no-trade/correction rule and complete per-symbol coverage report are still required. Missing premarket keeps the affected #1, #6 and #7 mode blocked. |
| L1 bid/ask | `_map_quote`, `get_quote` and `get_quotes` map bid, ask, sizes, quote time, trade time, last, session OHLCV, halt and borrow fields. Quote-event tests cover distinct ages, stale data and continuity with made-up input. | Nine `stock_quotes` files cover 2026-08-31 through 2026-09-11. Eight full days have 19,475–19,500 rows; 2026-09-11 has 4,600. Three dated proof files passed all stock spread and session-minute checks: 2026-08-31, 2026-09-09 and 2026-09-10. | `NEEDS VALIDATION`. There is no published provider field definition, consolidated/NBBO claim, exact size unit, delayed-state mapping, full-day quote-age distribution or continuity proof. The last saved collector day is incomplete. The separate September 13 SPY quote read succeeded, but Friday quote fields remained stale as described above. Mandatory actionable use stays blocked. |
| Time-and-sales | No trade stream or complete trade-event reader exists. A last trade and trade time inside a quote are not a tape. The M3.2 code can consume supplied eligible trades or a supplied minute counter only. | No saved trade-by-trade file was found. | `BLOCKED BY DATA` for `CRVOL_ORB5_B_TAPE_V1`, true VWAP, ten-second acceptance and true profile. The existing labeled alternative is final one-minute-bar acceptance or the approved projected-volume arm where its own counter source is proved. It is cheaper and lower load, but cannot reproduce trade conditions, cancels, corrections or sub-minute sequence. Reopen with a dated complete trade stream, official conditions/units, cancel/correction handling, measured gaps and the required prior-session windows. |
| L2/depth | No project-ready depth reader, storage shape or offline feed contract exists. | No saved depth output was found. | `BLOCKED BY DATA / OPTIONAL`. No core strategy waits for it. L1 plus bars is the free lower-fidelity alternative; it cannot show queue position or multi-level imbalance. A paid route is not justified now. Reopen only for a named ablation with official entitlement, fields, cadence, limits and dated output. |
| Options chains, quotes, volume, OI, IV and Greeks | `_chain_map_to_df`, `get_option_chain` and the forward collector preserve contract, expiry, strike, bid/ask/sizes, last, mark, volume, OI, IV, five Greeks, provider quote time, trade time, multiplier, non-standard flag, delayed flag and underlying quote. Offline tests cover mapping, configured banding, compaction and basic proof rules. | Eight compacted dates from 2026-08-31 through 2026-09-10 contain 3,151,940–3,751,024 option rows per day and 8,464–10,562 daily OI rows. On 2026-09-10, all 3,751,024 rows have bid, ask, sizes, volume and OI; at least 3,748,812 have each saved Greek; every saved delay flag is false. The 2026-08-31, 2026-09-09 and 2026-09-10 proof files passed; other proof dates show crossed quotes, an expiration-count failure or missing files. The saved collector chain files are limited to 23 names, four nearest expirations and a 15% strike band. The separate September 13 bounded read returned the 20 SPY contracts described above. | `NEEDS VALIDATION` for current quotes and `BLOCKED BY DATA` for historical execution. Bounded current access is observed, but a false delayed flag does not prove full entitlement, OPRA completeness, field units, Greek/IV calculation time, OI as-of time, corporate-action deliverables or permitted stock/option skew. The free lower-fidelity route is forward collection; it needs time and disk and cannot fill old dates. A paid historical quote source remains only a candidate with unverified cost. Reopen current use with dated raw/normalized chain parity and field/unit/skew/coverage checks; reopen historical use with licensed point-in-time intraday bid/ask history and original availability. |
| SPY, QQQ and sectors | The M2.4 supplied-record interface requires SPY, QQQ and all 11 sector ETFs separately. Current sector mapping exists. | Forward stock files include SPY, QQQ, XLK and SMH only. Separate XNYS.PILLAR and EQUS.MINI downloads now contain SPY, QQQ and all 11 sector ETFs; verified minute counts, hashes, ranges and gaps are in §44.2. `data/market_store` has unadjusted daily yfinance files for SPY, QQQ and all 11 sector ETFs through 2026-09-11; most start 2012-01-03, while XLC starts 2018-06-19 and XLRE starts 2015-10-08. | `NEEDS VALIDATION`. There is verified timestamp/identity minute inventory for all 11 sector ETFs, with incomplete opening windows; it is not qualifying live/history coverage or point-in-time stock-to-sector membership. The approved lower-fidelity alternative for #5 is `SECTOR_PROXY`, but the current four-name collector does not supply that full proxy. Reopen with per-symbol L1/minute/history coverage, source times, adjustments and dated membership. |
| VIX | A legacy regime helper can ask the general history wrapper for `^VIX`, normally through its free fallback. The canonical M2.4 reference interface explicitly refuses VIX because no supported index record/event contract exists. | No canonical VIX file was found. The files under `data/options-dx-2023` are HTML error pages despite their `.zip` names and supply no option or VIX history. | `BLOCKED BY DATA` for the canonical trade-alert input. Omit VIX or label the mode without it; a text symbol or legacy daily helper is not a faithful substitute. Reopen with official spot-VIX identity, fields, session/timestamp rules, current and historical coverage, and a canonical index contract. |
| News and earnings | The news controller races recent earnings, Finnhub company news, Google RSS, Brave and a self-hosted search source. Earnings code reads Finnhub EPS/calendar data and yfinance revenue. Offline tests use stored or made-up results. | The forward collector saved 32–35 daily event rows for its narrow universe on nine dates. These are yfinance earnings/dividend/split observations, not a news tape. No saved low-latency news output with original receive time was found. | Earnings calendar/context is `PROVISIONAL`; faithful low-latency catalyst mode is `BLOCKED BY DATA`. Existing public/search sources are a free, lower-fidelity alternative, but coverage, duplicates, revisions and receive delay are unmeasured and old pages cannot recreate original availability. Keep #7 faithful mode disabled. Reopen with a dated event manifest, publication and first-receive times, revisions, classifications, missed-event sample and measured delay. Any paid feed needs a verified price and a named improvement over that sample. |
| Halts | A Nasdaq Trader RSS reader, a separate collector reader, storage/dedup and offline fixture tests exist. | The collector has no saved halt file for the inspected dates; that may mean no tracked halt or a missed poll, so it proves neither case. | `NEEDS VALIDATION`. The free authoritative route is preferred. Reopen with dated raw feed captures, expected poll times, outage/gap handling, halt/resume field meanings and a known-event coverage check. A missing halt input suppresses an affected actionable setup. |
| Historical bars | Daily local data exists: `data/mmhl_daily` contains 540 JSON files, and `data/market_store` contains 26 daily parquet files. The M2.2 interface preserves request/observed coverage separately. | The current forward one-minute sample has eight complete dates. The configured `data/mmhl_minute` path contains no files and `config/full_chain_collector.yaml` marks minute history missing. That empty configured path is not the full inventory: the actual immutable Databento ETF and selected60 sources and their timestamp-only audits are recorded in §44.2. | `BLOCKED BY DATA` for required historical replay until the exact accessible source manifest, dates, symbols, sessions, gaps, venue basis, adjustments, corrections and original availability are published. Daily files cannot replace minute bars. Reopen by incorporating the existing read-only sources through M2.2 with explicit permitted source semantics; preserve the observed gaps and prior final-date exposure. |
| Historical options | The code can store new forward chain snapshots. No complete historical option reader/manifest is established. | Eight 2026 forward dates exist. All 16 supposed 2023 option `.zip` files inspected under `data/options-dx-2023` are HTML pages, not zip archives. | `BLOCKED BY DATA`. Underlying-only validation is the current lower-cost alternative and cannot claim option fills or returns. Forward collection can eventually support later dates but not old dates. Reopen with licensed intraday point-in-time option bid/ask, volume/OI/IV/Greek availability, contract adjustments and source-time coverage for the exact research window. |

The offline test files inspected for this table include
`test_schwab_normalization.py`, `test_historical_bars.py`,
`test_quote_events.py`, `test_reference_inputs.py`,
`test_schwab_client.py`, `test_full_chain_collector.py`,
`test_trading_halts.py`, `test_earnings_calendar.py` and
`test_news_cascade.py`. Their presence is not a fresh test result.

### 44.2 Verified minute inventory, not source qualification

The separately acquired originals remain local under
`/home/openclaw/.openclaw/research-data/databento/benchmark-sector-etfs_20260913_v1/`.
Each has SPY, QQQ, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV and XLY.
Request bounds below are Pacific, with the end excluded.

| Original file | Request range | Verified records | SHA256 |
|---|---|---|---|
| `xnys-pillar_ohlcv-1m_13-etfs.dbn.zst` | 2022-12-31 16:00 to 2026-08-21 17:00 | 4,257,208 | `7a5cfcff20c3b84d071f986f29d35e57abc74b2c96cba0de4cde97f0c9182f6c` |
| `equs-mini_ohlcv-1m_13-etfs.dbn.zst` | 2023-03-27 17:00 to 2026-08-21 17:00 | 4,483,742 | `a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3` |

Both original hashes remained unchanged after scanning instrument identity and
event timestamps only. No prices, volumes or returns were inspected. XNYS has
912 calendar sessions and 11,500 complete five-minute / 10,450 complete
fifteen-minute symbol-session windows out of 11,856 possible. EQUS has 854
sessions and 11,009 / 10,859 complete windows out of 11,102 possible. Both have
zero duplicate identity/timestamp pairs and zero wholly absent calendar sessions;
neither finding means all opening windows or premarket minutes are complete.
Missing minutes cannot be called no-trade minutes without source evidence.

Provider conditions retain four degraded XNYS dates and fifteen degraded EQUS
dates. Their full date lists and last-modified dates are copied in the JSON audit.
Do not erase those flags because timestamps exist. Keep single-venue XNYS.PILLAR
separate from component-venue EQUS.MINI; do not concatenate overlapping bars or
add volumes as if they were a complete-market feed.

The original selected60 minute files are also real existing inventory under
`/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/`.
The valid `bar-source-audit/audit-v3-summary.json` reports:

| Source | Verified rows | Identities | Calendar sessions | Complete five / fifteen-minute symbol-session windows |
|---|---|---|---|---|
| `xnys_pillar_ohlcv_1m` | 20,625,054 | 60 | 912 | 42,974 / 39,915 |
| `equs_mini_ohlcv_1m` | 19,325,105 | 59 | 854 | 43,930 / 39,967 |
| `equs_mini_brkb_ohlcv_1m` | 328,201 | 1 | 854 | 682 / 613 |

The broader audit scanned 40,278,360 identities/timestamps. All three files had
unchanged original hashes, verified counts, no duplicate pairs, no wholly absent
calendar sessions, no invalid mappings and no unmapped/ambiguous records. The
opening windows still have gaps. Ordering counters are adjacent timestamp
decreases, not a count of every row below an earlier maximum. The superseded
v1/v2 all-opening-minutes claims are invalid. The JSON audit includes the actual
file names, ranges, hashes and links to v3's per-symbol/session coverage.

Private proofs are under
`/root/trade-alerts-builder/repairs/codex-subscription/`: the ETF
`provider-cost-preflight/acquisition.json`, `acquisition-audit-summary.json`,
`acquisition-verification.json`, both coverage JSON files and
`dataset-condition-summary.json`; the original stock proof is
`bar-source-audit/audit-v3-summary.json` and `timestamp-instrument-inventory.json`.
The independent reviews accepted inventory only, not full source qualification.

Selected60 used 78 selection sessions through 2026-08-21. Previously sealed
final182 dates were profit-sealed, not demonstrably untouched. This stock-universe
bias and prior final-date exposure are separate limitations. Adding ETF history
repairs neither. No final dates were frozen and no outcomes were read in these
inventories. Originally available data, corrections, adjustments, eligible venues,
point-in-time universe/sector membership, tape, borrow, options, qualifying
historical replay and untouched final-validation evidence remain required.

## 45. Existing load and request coordination

The forward collector is configured as two one-shot scheduled tasks:

- `full-chain-stock-poll.timer`: every minute from 04:00 through 17:00 Pacific
  on weekdays. Outside the regular session it makes one batched stock-quote
  request for 25 names. During the regular session it also asks for option data
  for 23 names with six worker threads.
- `full-chain-daily.timer`: 13:20 Pacific on weekdays. It requests extended-hours
  one-minute bars for 25 names, reads event context, compacts option parts and
  writes a proof report.

The option path can make one expiration request plus one chain request for each
of 23 names, in addition to the stock-quote batch: up to 47 Schwab requests in a
regular-session minute from this collector alone. That is a code-path ceiling,
not a measured provider count. Existing engine commands and scans can also call
quotes, chains and history. Their combined peak has not been measured.

Authentication refresh is coordinated across processes with a file lock. Request
capacity is not. The 110-request-per-minute token bucket and 60-second too-many-
requests cooldown live only inside one process. Each one-shot collector process
gets a new bucket, while the engine and other jobs have separate buckets. There
is no account-wide queue, priority, expiry or shared request counter. Therefore
the present code cannot prove that interactive commands, background scans and
the new runtime fit together.

Required reopening test: run all intended consumers against one shared offline
request broker with recorded request traces. Show the configured account ceiling,
maximum queue length, request expiry, priorities, timeouts and zero calls after
expiry. Then use separately authorized current provider evidence to confirm the
recorded ceiling and subscription rules. Interactive/actionable reads must win
over research collection; stale queued research must be dropped, not served late.

## 46. Streaming and latency limits

No streaming transport is wired into the trade-alert data layer. The forward
collector polls once per minute. It cannot prove ten-second acceptance,
trade-by-trade VWAP, tape intensity, depth, reconnect recovery or no-gap
continuity. Official stream services, fields, partial-update rules, symbol limits,
subscription limits and current account entitlement remain unknown.

Existing code bounds one HTTP request at 15 seconds and one in-process rate wait
at 30 seconds. Those are failure timeouts, not market-data freshness budgets.
No approved maximum quote age, trade age, bar-publication delay, stock/option
skew, event-receive delay, queue wait or end-to-end alert latency has been selected.
Until each consumer has those values and M2.3/AT-13 proves them under load, its
mandatory live input remains unavailable. A one-minute polling mode may be used
only where the playbook explicitly permits a labeled one-minute alternative.

## 47. Retention, disk and memory limits

Current saved owner authority permits 175 GB (175000000000 bytes) of Google
Drive build storage. Normal archive admission stops at 165 GB
(165000000000 bytes), leaving 10 GB reserved. Earlier 10 GB and 100 GB caps are
historical. The ETF originals
remain local; the private restore index is
`/root/trade-alerts-builder/archives/etf-source-backup/etf-source-backup-index.json`.
Its backup status verifies remote sizes and local hashes, not remote hashes.
`pending-storage-accounting-delta.json` in that folder retains the pending shared
accounting merge; this repair does not change that ledger. Old temporary test
working copies have a separate verified offload index under
`/root/trade-alerts-builder/archives/uncompressed-offload-20260913/index.json`.
Original reports, published proof, current test folders and market data stay
local. A storage allowance or archive is not a measured retention/memory budget.

Local metadata checked at 20:53 Pacific on 2026-09-13 shows:

- `/home/openclaw/.openclaw/research-data/todo-109` uses 1.8 GB across 3,186
  files after eight complete option-chain dates and one partial date;
- option minute parts use 1.1 GB and compacted option-chain files use 662 MB,
  so both forms are retained;
- the filesystem is 91% used, with 6.8 GB available. This is more headroom than
  the earlier same-day reading, but no safe reserve has been selected and the
  reason for the change is outside this audit;
- the collector has no pruning rule for quote, bar, option-part, compacted-chain,
  OI, event or proof files. The separate daily database snapshot has a 750-day
  pruning setting, but that does not cover these parquet files;
- compaction reads every minute option file for a day into memory at once. No
  measured peak-memory limit or bounded-load proof exists.

No safe retention, free-space reserve, per-day growth, peak-memory or compaction
time budget has been approved. Current free space is about 3.8 times the whole
saved sample, but the collector's daily growth and peak memory are not measured,
so it cannot be treated as shadow-ready. The free
alternative is to keep only an approved minimum set and remove duplicate minute
parts after verified compaction, but retention and deletion are behavior choices
that need a separately reviewed storage milestone. Reopen with a chosen retention
period and reserve, measured daily growth and peak memory, atomic compaction,
hash-verified source/compact parity, tested cleanup, disk-full handling and proof
that old research records remain available as required.

## 48. M0.2 result and remaining gates

The bounded record reconciliation is complete; full M0.2 remains `BLOCKED BY
DATA` and `BLOCKED BY CAPACITY`. Bounded current Schwab read access and the
existing ETF/selected60 inventories are observed. The earlier sandbox login
failure is not an account-access blocker. Full entitlement and official field
units, NBBO fidelity, continuity, original availability, finality, corrections,
adjustments, faithful tape, canonical VIX, low-latency catalyst coverage,
qualifying sector/minute history, historical options/borrow, untouched final
validation and account-wide request/storage/memory/latency budgets remain open.
L2 remains an optional blocked enhancement, not a prerequisite for core strategies.
Research-rule choices are delegated; missing owner parameter permission is not
the blocker. D-090 remains a separate preserved arm. No live switch is enabled.

Reopen in this order:

1. Repair and prove storage capacity without deleting owner data in this audit.
2. Add one shared offline request queue and pass the recorded-load AT-13 test.
3. Incorporate the existing dated source proofs first. In a separately assigned
   source task under current owner authority, verify official fields/units and
   any remaining raw/normalized parity, exchange-hours continuity, coverage and
   limits for bars, quotes, chains, references, halts and events. No new provider
   request is needed for this record reconciliation.
4. Keep tape, VIX, catalyst, full breadth and historical options blocked unless
   their own reopening evidence passes. Preserve every named lower-fidelity mode.

Current authority is recorded in
`/root/trade-alerts-builder/repairs/codex-subscription/owner-active-supervision.json`:
up to **$60 total Databento API use, a fresh total** (owner decision D-101,
2026-09-16, superseding the earlier $40 cap) and 175 GB Google Drive build
storage, with normal archive admission stopping at 165 GB.
The earlier $16 of reservations and $24 unreserved amount are retired and
consume no part of the $60; `databento-build-spend-ledger.json` is historical.
The live ledger is `/root/trade-alerts-builder/databento-spend-ledger.json`.
Spending inside $60 needs no further approval; above it is forbidden.
Those calls had no paid retry. Other purchases, paid fallback and live actions
remain unauthorized. No new call, spending, purchase or storage change is needed
for this repair. Earlier D-091 caps, zero-use balances and the initial research
packet's $0/10 GB limits describe their dated sessions, not current authority.

### 48.9 M0.2I partial source-cost evidence and stopping boundary

The preserved V1 attempt returned no provider evidence. The separately reviewed
V2 task sent three cost requests. `EQUS.MINI` trades returned an estimate of USD
101.393871814013 and `EQUS.MINI` `mbp-1` returned USD 931.397507786751. The
`OPRA.PILLAR` `cmbp-1` request returned HTTP 400 for an unknown specific cause,
so the task stopped. Three OPRA requests remain unattempted. Dates before March
28, 2023 remain unpriced. No download, source-record request, retry, purchase,
reservation, ledger change or new spending occurred.

Both returned estimates exceed the current USD 24 unreserved amount. They are
not bills, account permission or source qualification. No further source request
is authorized by M0.2I. A separate M0.2J paperwork step would only repeat this
same boundary and is therefore not dependency-ready. Further progress requires
new owner or data authority that changes the present source, cost or budget
boundary. All source, split, capacity, replay, promotion and live gates remain
blocked.

At the M0.2 audit close, proposed next work was M0.2A's offline shared-storage
contract in ROADMAP. That dated proposal is now resolved by section 48.1. It
could not delete data, activate cleanup or establish production capacity from
synthetic examples. No downstream strategy is currently eligible: ROADMAP §14,
MASTER_SPEC §19, D-041 and CONTINUE_AUTOMATED step 8 require early Strategies
#1–#4 validation before #5–#8 implementation. M10.1 is Strategy #5 and frozen
definitions do not bypass that order.

### 48.1 M0.2A offline shared-storage contract

`M0_2A_STORAGE_CONTRACT.md` defines version 2 offline limits, pending repaired
protected verification and independent review, without changing or
activating the collector. Primary market and supporting records have a 750-day
minimum plus legal holds. Minute option parts remain for at least seven days
after source/compact parity proof; partial, held or unproved dates remain. The
disk reserve is the larger of 12,000,000,000 bytes or 15% of filesystem capacity.
Compaction uses the section 4 allowance
`max(ceil(2.25 * S), 2 * (C + O + P + A)) + E + T`, covering source bytes,
both new data files, proof, publication metadata, temporary siblings and all
existing/stale sets. Unknown bounds block admission. Chain, open interest and
proof publish as one verified set under section 5.1; a mixed or incomplete set
never qualifies for part removal. It uses at most 256,000,000 decoded source
bytes per batch, stays under
1,500,000,000 bytes peak resident memory and has a 15-minute daily time budget.

The same contract specifies protected source/compact parity, fresh-process
reopen, interruption, stale-temporary-file, disk-full, reserve, retention-plan
and bounded-resource cases for M0.2B. Current code does not meet those rules and
current free space is below the new reserve. No cleanup is active and no owner
data was removed. M0.2 capacity remains blocked until M0.2B implements and proves
the contract, then a separately reviewed measured saved-data run proves the
actual growth and resource use.

Prior controller proof is retained in the JSON audit: one focused run, one broad
acceptance run and two repeatability runs, with their exact selectors, published
artifact directories and controller timings. These are prior engineering proof,
not M0.2 source qualification or independent acceptance of this correction.
No product tests were rerun here. The supplied packet has no verification handoff;
the controller supplies any required final source comparison or protected stages.

### 48.2 M0.2C measured saved-data capacity assessment

`M0_2C_CAPACITY_ASSESSMENT.md` and its JSON record preserve the current blocked
admission result. The approved 2026-08-31 candidate has 390 option-part files
using 147,903,541 logical bytes and 148,725,760 allocated bytes. The storage
manager recorded 9,200,222,208 local free bytes at 01:39 Pacific on 2026-09-14.
That is already below the frozen 12,000,000,000-byte minimum reserve before an
isolated copy or working files exist, so the bounded compactor must not start.

No copy was created and no owner file was changed, moved or removed. Actual
source/compact record equality, output bytes, peak memory and wall time remain
unmeasured. Cleanup and live switches remain off. The 175 GB remote build
allowance does not replace the local compactor reserve. Reopen after current
storage recovery with fresh local capacity evidence and the unchanged full
admission formula. M0.2D's offline shared request queue and recorded-load AT-13
proof is proposed as independent shared work, subject to reviewer confirmation.


## 49. M0.3B V2 coverage-only audit

`M03B_OR_RESEARCH_V2` requires a complete intraday tape for the twelve base combinations, complete one-minute and reference histories for the common gates, point-in-time event and availability times, correction rules, compatible adjustments and valid increments. Executable short evidence additionally requires dated borrow eligibility and cost. Executable option evidence additionally requires full eligible-chain identity, bid/ask, size, Greek/as-of and exit coverage. Daily JSON files or one-minute bars cannot recreate the ten one-second acceptance samples.

The §§44–48 audit was reviewed without opening strategy results. It does not contain a qualifying source manifest or covered-session list. The latest saved collector date has no stock bars or option files. Therefore exact development, calibration and final-validation dates cannot yet be derived. [M0_3B_COVERAGE_AUDIT.json](./M0_3B_COVERAGE_AUDIT.json) records this as `BLOCKED_BY_SOURCE_MANIFEST` with null date lists and null manifest hash.

Reopen through M0.2's existing-source-first steps. Before replay, publish every covered date and symbol, expected/observed intervals, source/venue/adjustment basis, event and availability times, correction treatment, gaps, source-file hashes and one canonical manifest hash. Derive and publish the exact 60%/20%/remainder chronological date lists from that immutable manifest before generating candidates. This earlier freeze used no incremental spending; current saved Databento authority and reservations are in §48. Missing tape blocks faithful V2 replay; it does not authorize a one-minute substitute.

## 50. M0.3C HOD compression research inputs

`M03C_HOD_COMP_RS_V1` uses the M0.3A minute ATR, daily ATR, opening-five-minute
RVOL, median dollar-volume estimate and named session VWAP modes. It additionally
requires complete point-in-time stock and SPY one-minute bars for the 15-bar
relative-strength warm-up and the non-overlapping three/seven compression
windows. Every bar needs finality, event and availability times, session identity
and a compatible adjustment basis.

The faithful tape arm requires eligible executed shares with complete coverage
for each 15-second numerator and the identical interval in 20 prior sessions.
The separate quote/projected arm requires covered one-second quote samples,
fresh last trades, current-minute eligible volume and the corresponding minute
from 20 prior sessions. One-minute final bars cannot recreate either arm's ten
one-second acceptance samples. Missing tape does not become projected-volume
evidence, and missing projected inputs do not become tape evidence.

Executable short results also require point-in-time borrow availability and
cost. Option evidence remains separate and needs exact contract and quote facts.
M0.2's source-manifest and capacity gates remain open. These written data rules
do not prove that a provider or saved history supplies them.

## 51. M0.3D OR failure research inputs

`M03D_OR_FAILURE_REV_V1` uses the M0.3A minute ATR, daily ATR, opening-five-
minute RVOL, median dollar-volume estimate, five-minute opening range and named
session VWAP modes. It additionally requires the complete point-in-time break
path, furthest eligible trade, final one-minute reacceptance bar and the valid
price increment. Every input needs event and availability times, session
identity, finality or correction state and a compatible adjustment basis.

The faithful tape arm requires covered eligible trades for every fixed one-
second sample. The separate quote arm requires covered one-second quote
midpoints plus a fresh eligible last trade. Both need complete coverage of the
ten seconds before the reacceptance close when the catalyst-continuation
suppression applies. One-minute bars cannot recreate either ten-sample arm.

The suppression fact also requires a point-in-time `CATALYST_ORB5_V1` class and
source record available by evaluation. An unknown catalyst cannot
be changed to no catalyst. A current news headline without original event time,
received time, complete coverage and a faithful structured class does not meet
this requirement.

Executable short results require point-in-time borrow availability and cost.
Option evidence remains separate and needs exact contract and quote facts.
M0.2's source-manifest and capacity gates remain open. These written data rules
do not prove that a provider or saved history supplies them.

## 52. M0.3E first-pullback research inputs

`M03E_FIRST_PULLBACK_VWAP_V1` uses the M0.3A minute ATR, daily ATR,
opening-five-minute RVOL, median dollar-volume estimate and one named session
VWAP mode, plus `RS15_SPY_CLOSE_V1`. It requires complete point-in-time stock
and SPY one-minute bars for the impulse, two-bar swing confirmation, pullback,
reversal bar, VWAP slope and VWAP-close-cross count. Every bar needs finality,
event and availability times, session identity and a compatible adjustment
basis. Corrections create a new as-of version and cannot silently move a frozen
structure.

The duration-normalized volume ratio requires complete eligible-trade coverage,
covered-second counts and certified no-trade intervals for both impulse and
pullback legs. Final minute volumes may support a separately labeled bar proxy,
but cannot prove sub-minute trigger order or a faithful eligible-share rate.
The trigger requires consecutive fresh eligible trades, a fresh two-sided quote,
known halt and opposing-material-news status, and a known valid price increment.
One-minute bars cannot recreate that crossing.

The target catalog requires point-in-time session HOD/LOD, prior-day high/low
and close, and valid whole-dollar and half-dollar levels on a compatible price
basis. Executable short results require point-in-time borrow availability and
cost. Option evidence remains separate and needs exact contract and quote facts.
M0.2's source-manifest and capacity gates remain open. These written data rules
do not prove that a provider or saved history supplies them.

## 53. M0.3F index opening-drive breadth research inputs

`M03F_INDEX_OPEN_DRIVE_BREADTH_V2` uses the M0.3A minute ATR, daily ATR and
exactly `SESSION_VWAP_BAR_HLC3_V1` for all instrument and member VWAP values,
including slope and close-cross checks. Trade VWAP cannot substitute for it.
It requires complete point-in-time SPY, QQQ, IWM or DIA
one-minute bars and fresh eligible trades and quotes for the chosen instrument,
plus regular-session open, prior close, VWAP and three-minute VWAP slope. Every
input needs event and availability times, session identity, correction state
and a compatible adjustment basis.

`SECTOR_PROXY` requires complete same-instant inputs for exactly XLK, XLF, XLY,
XLC, XLI, XLV, XLP, XLE, XLU, XLRE and XLB. One missing ETF makes the mode
unavailable. `FULL_CONSTITUENT` requires point-in-time index membership and
weights, at least 95% member and weight coverage, and coverage in every sector
represented by the frozen index membership.
`HYBRID` requires that same constituent coverage plus every sector ETF. Current
membership cannot be copied backward. A mode cannot borrow a missing component
from another mode or rescale the remaining weights.

The Up Volume component uses `SESSION_DIRECTIONAL_TRADE_VOLUME_V1` in packet
§4.1: the complete eligible trade sequence from the regular open through
evaluation, each trade's share size and its immediately preceding eligible
trade price. Opening and equal-price shares enter only the denominator. Trade
IDs, equal-time source order, correction/cancellation links and their
availability times are mandatory, along with verified trade-condition mapping.
Unknown gaps or ambiguous ordering make that member uncovered; enforce the
mode's coverage thresholds. This is raw-share weighting, not index weighting
or a minute-volume proxy. These source checks remain M0.2 requirements.

This component and faithful ten-second acceptance require eligible
trade coverage with certified no-trade intervals. Final minute bars may support
a separately labeled proxy, but cannot reconstruct one-second acceptance or
unknown constituent paths. Macro suppression requires the point-in-time event
schedule and its availability. Full and hybrid historical evidence remain
blocked under M0.2 until membership, weights, minute history and coverage are
verified.

Executable short results require point-in-time borrow availability and cost.
Option evidence remains separate and needs exact contract and quote facts.
These written rules do not prove source coverage, a replay result or profit.

## 54. M0.3G failed-gap-fade research inputs

`M03G_GAP_FADE_FAILED_OPEN_V1` uses the M0.3A minute ATR, daily ATR, median
dollar-volume estimate and exactly `SESSION_VWAP_BAR_HLC3_V1`. Trade VWAP
cannot substitute for it. It requires the prior regular-session adjusted close,
the first eligible regular-session trade, all three final opening minutes,
complete point-in-time stock and SPY trades for `RS_OPEN_SPY_V1`, and final
one-minute bars for loss of open and failed reclaim. Every input needs event and
availability times, session identity, finality or correction state and a
compatible adjustment basis.

The faithful trigger requires correctly ordered eligible trades on both sides of
the frozen first-three-minute boundary, no more than three seconds apart, plus a
fresh two-sided quote. It also requires known spread, halt status and valid price
increment. A final minute bar may support a separately labeled bar proxy, but
cannot reconstruct the trade crossing or quote-side fill.

Catalyst evidence requires complete point-in-time morning-event coverage, original
receive time, source, classification version, class and continuation direction as
of trigger. An absent record without proven coverage is `UNKNOWN`, not class C.
Later news cannot rewrite an earlier candidate. Class A/B/C/D rows remain
separate.

The target catalog requires the prior close, open, current session VWAP and exact
25%, 50%, 75% and 100% gap-fill prices on one compatible basis. Executable short
results require point-in-time borrow availability and cost. Option evidence
remains separate and needs exact contract and quote facts.

M0.2's source-manifest, catalyst-history and capacity gates remain open. Before
replay, publish covered dates and symbols, expected and observed intervals,
corrections, gaps, adjustment basis, file hashes and one immutable manifest.
Freeze exact chronological development, calibration and untouched final dates
before opening strategy results. These written rules do not prove that a source
supplies the required facts.

## 55. M0.3H catalyst-first-consolidation research inputs

`M03H_CAT_FIRST_CONSOL_V1` uses the M0.3A minute ATR, daily ATR, opening-five-
minute RVOL, median dollar-volume estimate and exactly
`SESSION_VWAP_BAR_HLC3_V1`. Trade VWAP cannot substitute for it. It requires
complete point-in-time catalyst coverage, original publication and first receive
times, stable source-event identity, issuer identity, classification version,
class, direction and every correction or contradiction available by evaluation.
An absent event without proven coverage is `UNKNOWN`, not class C or no news.

The regular-session impulse and first consolidation require complete final
one-minute bars plus eligible trades from the reaction start through trigger.
Every record needs event and availability times, session identity, correction
state and a compatible adjustment basis. The volume ratio requires complete
eligible-share coverage for the impulse and consolidation. An unexplained gap
makes the faithful value unavailable.

The faithful trigger requires correctly ordered eligible trades on both sides of
the frozen boundary, no more than three seconds apart, ten covered one-second
acceptance samples, a fresh positive two-sided quote, known spread, halt status
and valid price increment. A final minute bar may support a separately labeled
bar proxy, but cannot reconstruct the crossing, ten-second acceptance or quote-
side fill.

The target catalog requires point-in-time session HOD/LOD, premarket high/low,
prior-day high/low/close, session VWAP and valid whole/half-dollar levels on a
compatible basis. Executable short results require point-in-time borrow
availability and cost. Option evidence remains separate and needs exact contract
and quote facts.

M0.2's source-manifest, catalyst-history and capacity gates remain open. Before
replay, publish covered dates and symbols, expected and observed events and
intervals, corrections, gaps, adjustment basis, file hashes and one immutable
manifest. Freeze exact chronological development, calibration and untouched
final dates before opening strategy results. These written rules do not prove
that a source supplies the required facts.

## 56. M0.3I prior-value/LVN research inputs

`M03I_VP_ACCEPT_LVN_V1` uses the immediately prior regular session on one
compatible adjustment basis. Approximate mode requires complete final
one-minute OHLCV, certified no-trade intervals, corrections, valid ticks, prior
close and daily ATR. True mode separately requires every eligible trade, trade
condition, share volume, cancel and correction through the prior-session freeze.
The modes cannot substitute for or be pooled with each other.

Current-session acceptance and trigger evidence requires correctly ordered
eligible trades for 90 fixed one-second samples and both value/LVN crossings,
final one-minute closes, opening-five-minute RVOL, the selected bar VWAP, fresh
two-sided quotes, halt state and valid ticks. Refill uses only observations
available through evaluation and the same fixed LVN interval and allocation
mode. Missing prior LVN volume makes refill `UNKNOWN`; missing event coverage
cannot be read as zero activity.

The structural arm also requires the frozen value edge, acceptance swing, LVN
far edge and next-HVN leading edge and center. Matched controls require
point-in-time market and sector returns plus the frozen time, RVOL, ATR,
liquidity, gap and break-strength buckets. Executable shorts require dated
borrow and cost. Option evidence remains separate and needs exact contract and
quote facts.

M0.2's source-manifest, adjustment, trade-history and capacity gates remain
open. Before replay, publish covered dates and symbols, expected and observed
intervals/events, corrections, gaps, corporate actions, file hashes and one
immutable manifest. Freeze exact chronological development, calibration and
untouched final dates before opening strategy results. These written rules do
not prove that a source supplies the required facts.

## 57. M3.3 relative-strength input boundary

The offline M3.3 calculation accepts supplied canonical regular-session one-minute
Bars for stock and SPY and supplied eligible opening/current trades for stock,
SPY, QQQ and the selected sector ETF. `RS15_SPY_CLOSE_V1` needs all first 15
scheduled minutes final and available on one compatible adjustment basis.
From-open values need positive trades from the same session and basis, original
availability and current trades no more than three seconds old. Sector identity
is supplied point in time; the feature code does not infer it from a current map.

Actual per-symbol coverage, eligible-trade conditions, cancels/corrections,
publication/finality, historical membership and corporate-action compatibility
remain under M0.2/M2.2/M2.4. A missing SPY, QQQ or sector path remains separately
unavailable. Synthetic Bars and trades do not close those source gates.

## 58. M0.2A offline storage contract

M0.2A records the version 2 offline storage rules, pending repaired protected
verification and independent review, in
`M0_2A_STORAGE_CONTRACT.md`: retained record classes, 7/30/750-day periods and
legal holds; the larger of 12,000,000,000 bytes or 15% filesystem reserve; a
1,500,000,000-byte process peak-memory limit; a 256,000,000-byte decoded batch
limit; and a 15-minute per-date compaction limit. The earlier controller's focused and
broad protected phases each passed 2994 tests, and its separate repeatability
phase passed 62 tests in each of two runs. The exact selectors, timings, hashes,
artifact directories and complete tested-source manifest are recorded in that
contract.

Review found that those selections omitted `tests/test_full_chain_collector.py`;
they do not establish acceptance. Section 9 of the contract requests that
focused check and the controller's expanded broader selection. The repair also
requires one complete chain/open-interest/proof set, per-member failure cases
and space bounds for every output. Section 10 preserves the subsequent
`ModuleNotFoundError` during collector-test collection and records the
owner-approved installed launcher recovery: a read-only collector file and
sanitized temporary-output settings. Repair count 2 and rejected attempts remain
unchanged. The collector check and existing contracts remain required; no fresh
pass is claimed. New protected figures will come from the controller.
M0.2B still owns the
off-by-default bounded implementation and its named failure tests. A later
saved-data measurement still owns growth, peak memory, temporary space and wall
time. Current free space remains below the chosen reserve. No cleanup was
activated, no owner data was removed or moved, and no source or capacity gate
closed.

### 58.1 Final M0.2A proof

The repaired protected selection passed on 2026-09-13 Pacific. The focused and
acceptance phases each passed 3001 tests, including
`tests/test_full_chain_collector.py` and `tests/trade_alerts_contracts`. The
separate repeatability phase passed 62 tests in each of two runs and its
recording comparison was stable. M0_2A_STORAGE_CONTRACT section 11 records the
exact phase selectors, reasons, controller wall times, pytest and JUnit times,
artifact directories, hashes and complete tested-source manifest. M0.2A is
complete as an offline contract. M0.2B remains open for the off-by-default
implementation and measured proof. Source qualification, saved-data capacity,
cleanup activation and live use remain blocked by their separate requirements.

## 59. M0.2D recorded request-load boundary

M0.2D adds one disabled offline queue for recorded traces. It fixes a 110-call
rolling 60-second safety ceiling, 256 pending requests, four priority classes,
class expiry and class timeout values. The protected cases must show that
interactive and actionable work runs before older research, stale work makes no
recorded call, high-priority work can displace research at the queue bound, and
the dispatch count remains shared after reopening the queue file.

The 110-call value preserves existing code headroom for the offline test. It is
not current provider-limit or subscription proof. Existing dated read access,
official field units, subscription scope, continuity and combined real load
remain separate source checks. No provider request or runtime consumer is part
of M0.2D.

## 60. M0.2E provider-limit and source-contract reconciliation

The 2026-09-14 Pacific check used saved evidence and public official documents.
It made no provider request, login, credential read, download or purchase. The
full record is in `M0_2E_SOURCE_RECONCILIATION.md`.

Schwab's public Market Data page did not supply a readable numeric account-wide
request limit, stream subscription or symbol limit, account entitlement, source-
time unit, NBBO guarantee, bar-finality rule, correction rule or history-depth
contract. The dated 2026-09-13 check still proves only that one restricted SPY
quote request and one restricted SPY option-chain request succeeded. Its 20
contracts, HTTP success, `realtime=true`, `isDelayed=false` and observed integer
time fields do not establish complete entitlement, freshness, field units or an
account allowance. Friday option times were stale when observed Sunday.

Therefore M0.2D's 110-dispatch-per-rolling-60-second value remains a configurable
local safety ceiling. It is not a Schwab limit and is not safe to present as one.
The queue's intended consumer classes are interactive commands, actionable
strategy reads, background collection and research collection, in that priority
order. No current consumer is wired to the queue, and combined account load is
unmeasured. Live collection still requires account-specific official limit and
subscription evidence plus a protected combined-consumer test.

Future Schwab source records must preserve the original field name and value,
raw source time, local received time and delay flag. An integer time may be
converted only under an explicitly labeled interpretation until official units
are established. A false delay flag cannot replace an age check or prove
freshness. M0.2E does not change the existing offline normalization code or claim
that every raw field is already retained.

Official Databento documents establish these narrower source rules:

- `XNYS.PILLAR` is the direct NYSE Integrated feed. Its event, send-delta and
  capture-receipt times are data-message times, not original-availability or bar-
  finality proof for the retained historical file.
- `EQUS.MINI` is a derived top-of-book source aggregated across component venues.
  Its trade venue is anonymized and its publisher identity is the derived source.
  Keep it separate from `XNYS.PILLAR`; do not add overlapping OHLCV volumes or
  describe it as a named-venue or complete consolidated tape.
- An OHLCV row is emitted only for an interval with a trade. A missing row is not
  automatically zero volume, a market closure or a feed failure. The existing
  per-symbol/session masks remain required, and a no-trade interval needs its own
  source-backed certification.
- Historical and Live are separate services. Public release notes show that
  degraded intervals and repairs occur, but do not provide a universal per-record
  finality, revision or original-availability history for the retained files.

These rules preserve the verified 4,257,208-row `XNYS.PILLAR` and 4,483,742-row
`EQUS.MINI` 13-ETF inventories and their four and fifteen provider-degraded dates.
They do not qualify either source for full-market coverage, point-in-time sector
membership, corrections, adjustments, finality, historical execution or
untouched final validation. The selected60 inventory and its stock-selection and
previously exposed final-date limits also remain unchanged.

M0.2E completes this bounded reconciliation. It does not close M0.2's source,
continuity, history, capacity or live gates. Reopen Schwab account limits, time
units and entitlement only with account-specific official evidence. Existing
retained Databento files may next support an offline source manifest and adapter
that keeps the two feeds separate and preserves all unknown facts; that work
cannot call the files final, correction-complete or executable evidence.

## 61. M0.2F retained Databento minute-source boundary

`M0_2F_SOURCE_MANIFEST.json` records the retained `XNYS.PILLAR` and `EQUS.MINI`
13-ETF `ohlcv-1m` files. Their verified counts are 4,257,208 and 4,483,742.
Their opening-window inventories have gaps, and their four and fifteen provider-
degraded dates remain explicit. File fingerprints and exclusive request bounds
identify the immutable inputs without reading price, volume or return values in
this milestone.

The files remain separate sources. `XNYS.PILLAR` identifies direct NYSE
Integrated observations. `EQUS.MINI` identifies a derived component-venue
aggregate whose trade venue is anonymized. Their overlapping bars and volumes
must not be joined or added. A missing minute stays missing without separate
source-backed no-trade evidence.

The offline adapter preserves each raw instrument ID, raw nanosecond event time,
publisher/venue identity, file fingerprint and provider-degraded condition. It
sets finality false and keeps original availability, corrections and adjustment
basis unknown. This contract does not qualify either source for complete
history, point-in-time membership, executable trading, historical results or
untouched final validation.

## 62. M0.2G coverage-only split admission

`M0_2G_COVERAGE_ONLY_MANIFEST.json` derives its decision from the accepted
M0.2F manifest and the two fixed inventory-only coverage records. It reads no
price, volume, return or strategy result. The inventories contain 22,958
dataset/symbol/date rows: 11,856 direct `XNYS.PILLAR` rows and 11,102 separate
derived `EQUS.MINI` rows. The feed records are not combined.

The exact qualifying symbol/date list is empty. The files contain only the 13
named ETFs, not a point-in-time stock universe. Minute-row presence does not
prove complete trades or certified no-trade intervals. Original availability,
finality, corrections, adjustments, point-in-time membership, borrow and
historical executable option quotes remain unproved. The selected60 inventory's
previously exposed final dates are not untouched final-validation evidence.

Therefore the immutable qualifying-manifest fingerprint and exact 60%
development, 20% calibration and remainder final-validation date lists remain
null. M0.2G finishes the bounded inventory assessment but does not admit a split.
Historical replay remains blocked until a later source task supplies all
required facts without opening results first.

## 63. M0.2H first-four source acquisition preflight

This section records the M0.2H preflight state. Section 64 holds the later
M0.2I cost-check evidence and current cost status.

`M0_2H_SOURCE_ACQUISITION_SPEC.json` freezes the bounded acquisition target for
`M03B_OR_RESEARCH_V2`, `M03C_HOD_COMP_RS_V1`,
`M03D_OR_FAILURE_REV_V1` and `M03E_FIRST_PULLBACK_VWAP_V1`. It names the exact
60 inventoried stocks, SPY, January 1, 2023 through August 21, 2026 historical
bounds, and September 15 through October 30, 2026 forward holdout bounds. The
old selected60 dates remain exploratory only because selection used data through
August 21 and prior final dates were exposed. A new exact chronological split
may be derived only after the forward and historical rows pass the full source
rule and before any result is opened.

The required source shapes remain separate: complete eligible stock trades;
one-second top-of-book quotes; point-in-time listing, universe and sector facts;
corporate actions and adjustments; dated borrow; complete eligible historical
option chains and executable quotes; and catalyst/halt publication, first-receive
and revision history. Each needs event and original-availability times,
correction/finality state, stable identity and source fingerprints where the
JSON specifies them. A missing group blocks only its dependent arm, but no row
enters the qualifying manifest unless it has every fact required by that row's
claimed mode.

Six exact Databento cost requests are preregistered but unsent: `EQUS.MINI`
trades and `mbp-1`, plus `OPRA.PILLAR` `cmbp-1`, trades, statistics and
definition. Their costs are unknown. `EQUS.MINI` remains a derived
component-venue source, and OPRA data does not supply every required option
field by itself. Security Master, corporate actions and adjustment factors need
separate entitlement and price evidence; these are unresolved gates, not
additional M0.2I requests. M0.2I is limited to the six preregistered
`Historical.metadata.get_cost` requests, once each and serially, after fresh
independent M0.2H review permits advancement. No additional reference,
entitlement, coverage or symbology request is authorized. No qualifying
historical borrow or catalyst source is identified.

This preflight made zero provider requests, credential reads, downloads,
reservations or spending. The Databento cap is now **$60, a fresh total**
(D-101, 2026-09-16); the prior $16 reservation and $24 unreserved amount are
retired. A later paid request needs the live ledger, local storage admission
and its own assigned acquisition step. See
`M0_2H_SOURCE_PREFLIGHT.md` for the saved evidence and official-source limits.
M0.2 source qualification, the chronological split, replay, promotion and live
use remain blocked.

## 64. M0.2I bounded source-cost evidence

The original `M0_2I_COST_CHECK_RESULT.json` remains unchanged. It records six
local SDK starts, zero provider connections and zero provider responses. Those
failures remain historical evidence and were not reset or replaced.

A separately assigned and independently reviewed zero-spend V2 check used the
same six frozen request shapes with a narrower common start of March 28, 2023.
It sent three POST requests, once each and in order. `EQUS.MINI` trades returned
an estimated cost of USD 101.393871814013 and `EQUS.MINI` `mbp-1` returned an
estimated cost of USD 931.397507786751. Both returned HTTP 200. The
`OPRA.PILLAR` `cmbp-1` request returned HTTP 400, so the task stopped. The
specific cause of that response is unknown. The remaining OPRA trades,
statistics and definition requests were not attempted. There were no retries,
redirects, downloads, source-record requests, reservations, ledger changes or
new spending. `M0_2I_COST_CHECK_V2_RESULT.json` preserves the exact bounded
result and its independently reviewed source references.

Each returned estimate exceeds the USD 24 unreserved part of the existing USD
40 cap. The estimates are not bills, reservations, account authorization or
proof that a purchase fits the cap. Billing remains unknown. Dates before March
28, 2023 remain unpriced, and OPRA availability remains unknown.

The cost responses do not qualify any source. Complete stock tape and NBBO,
original availability, corrections and finality, adjustment history,
point-in-time membership, historical borrow, complete historical options and
executable quotes, catalyst history, untouched final dates, and local capacity
remain blocked. No qualifying split can be frozen. Replay, promotion, profit
claims and live use remain blocked, and all switches stay off. A later source
acquisition or budget change requires a separate owner and data decision.

## 65. M0.2CB off-by-default cleanup decision

The accepted M0.2CA measurement supports building the narrow removal action in
`M0_2A_STORAGE_CONTRACT.md`; it does not support enabling cleanup now. The run
covered all 390 saved source files and 3,721,860 option rows, preserved source
identities, verified source-to-compact record equality and stayed inside its
disk, scratch, memory, batch and owner-authorized wall limits. Fresh protected
collector/storage proof and independent review passed.

M0.2CC may implement only an off-by-default action over the existing dry-run
retention plan. It must recheck root containment, legal holds, current source
identity, complete-set proof, age and file identity immediately before each
removal. Unknown, changed, incomplete, held or unproved state blocks removal.
Primary and supporting records remain outside this first cleanup action. Dry run
stays the default, checked-in cleanup stays off, and tests may remove only
temporary synthetic files.

`M0_2CB_SAFE_ACTIVATION_DECISION.md` records the full boundary. This decision
does not qualify a source, close any D-104 gap, open Strategies #5 through #8,
prove a trading result or enable any live switch.
