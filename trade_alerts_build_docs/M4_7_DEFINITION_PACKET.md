# M4.7 first-four options and portfolio contract

Version `M47_FIRST4_RESEARCH_V1`. Status: **FROZEN FOR OFFLINE RESEARCH AND
IMPLEMENTATION**, 2026-09-14 Pacific. The owner delegated these finite research
choices in `RESEARCH_AUTHORIZATION_20260913.md`. This contract does not validate
an option result, qualify a source or authorize live use.

## 1. Preserved rules and scope

`CRVOL_ORB5_OPTION_POLICY_V1` and
`OPTION_SCORE_INTRADAY_LONG_PREMIUM_V1` remain unchanged. The 72 ORB research
arms remain separate. Portfolio recording never pools their outcomes or selects
a winner. The other first-four policies are:

- `HOD_COMP_RS_OPTION_ORDINARY_RESEARCH_V1`;
- `OR_FAILURE_REV_OPTION_ORDINARY_RESEARCH_V1`;
- `FIRST_PULLBACK_VWAP_OPTION_ORDINARY_RESEARCH_V1`.

Those three policies select ordinary 1–5 DTE only. A long stock setup buys a
call and a short setup buys a put. Absolute delta is 0.50–0.70 inclusive with
0.60 as the target. Their 0DTE rows are
`NOT_SELECTED_BY_THIS_RESEARCH_POLICY`. This does not remove the shared 0–7 DTE
engine or #1's strict 0DTE branch.

## 2. Required option evidence

Inputs are one immutable stock candidate, its as-of stock quote, a complete
chain snapshot and immutable option rows. Identity, strategy/version/research
arm, source mode/version, instrument/session, chain and quote IDs, availability,
input IDs and config hash stay linked. A later Greek, quote or reference row may
not be joined to an earlier snapshot.

Standardness must be proved independently: multiplier 100 and a plain
same-underlying 100-share deliverable with no cash or adjustment. Blank text is
not proof. DTE is listed expiry date minus the current Pacific date. Actual
listed expirations are required. Delta sign must match the right.

Only nondelayed regular-session option and stock quotes may be used. Provider
time must be no later than availability, which must be no later than evaluation.
Effective age is the greater of provider age and reported age. Both quote ages
and provider-time separation are at most three seconds.

Ordinary filters are inclusive: positive bid/ask, ask at least bid, midpoint at
least $0.20 per share, spread ratio `(ask-bid)/midpoint` at most 0.10, OI at
least 100 contracts, bid and ask sizes at least two contracts, known
nonnegative current-session volume, positive annualized-fraction IV, gamma at
least zero and theta at most zero option dollars per calendar day. Units and
the matching Greek snapshot must be proved. Missing mandatory possibly eligible
facts make the result unavailable.

## 3. Frozen score and order

Let `clamp(x)=min(100,max(0,x))`, `d=abs(delta)` and use exact values before
display rounding:

```text
SpreadFit = clamp(100*(0.10-spread_ratio)/0.10)
DeltaFit = clamp(100*(1-abs(d-0.60)/0.10))
OIFit = clamp(100*(OI-100)/900)
VolumeFit = clamp(100*volume/1000)
SizeFit = clamp(100*(min(bid_size,ask_size)-2)/8)
LiquidityFit = 0.40*OIFit + 0.40*VolumeFit + 0.20*SizeFit
DTEFit = 100 for the same ISO Monday–Sunday week, otherwise 0
IVFit = clamp(100*(1-abs(IV/median_IV-1)))
x = 0.5*gamma*(0.01*underlying_midpoint)^2/abs(theta)
GreekFit = 100*x/(1+x)
OptionScore = 0.30*SpreadFit + 0.25*DeltaFit + 0.25*LiquidityFit
              + 0.10*DTEFit + 0.05*IVFit + 0.05*GreekFit
```

If theta is zero and gamma positive, GreekFit is 100; if both are zero, it is
zero. The IV median uses all positive finite-IV standard rows for the same
underlying/right/expiry inside the inclusive delta band in the proved complete
snapshot, before later score filters. Even counts average the middle two. No
missing factor is renormalized. Ordinary score must be at least 65.

Order passing rows by score descending, distance from delta 0.60 ascending,
spread ascending, minimum displayed size descending, volume descending, OI
descending, same week first, expiry ascending, then canonical contract ID
ascending. The selected contract and snapshot are frozen. Delayed-entry research
revalidates that same contract; it may not switch to a later better row.

For #1 0DTE, preserve SPY/QQQ or proved common-stock market value of at least
$500 billion as of the prior close, plus an actual listed same-session standard
expiry. Ages and time separation must be at most one second, spread at most
0.05, OI and volume at least 1,000, both sizes at least ten, all ordinary gates
and score at least 75. Unknown membership permits only a labeled complete
ordinary selection: `ORDINARY_DTE_ONLY / SAME_DAY_MEMBERSHIP_UNAVAILABLE`.

A complete passing set yields `RECOMMENDED`. A complete set with no passing row
yields `STOCK_VALID_OPTIONS_POOR` with reason counts. Missing or truncated
coverage, a possibly eligible row with unknown delta, or missing in-band facts
yields `OPTIONS_UNAVAILABLE`. Stock validity is unchanged in every case.

## 4. Stable candidate identity and complete-batch recording

`M47_CANDIDATE_KEY_V1` contains strategy/version, config hash, research arm,
source mode, instrument/session, alert type, producer structure ID, sorted
unique frozen input IDs and original mechanical-event availability as integer
epoch nanoseconds. JSON uses sorted Unicode code-point keys, compact separators,
literal UTF-8 (`ensure_ascii=False`), no normalization and no nonfinite numbers.
Reject unpaired surrogates. SHA-256 of those bytes is the wrapper fingerprint.
Reception, display, option ranking and delivery attempts are not key material.
A matching wrapper with different semantic event bytes is
`IDENTITY_COLLISION_UNAVAILABLE`.

`M47_FIRST4_GROUP_RECORDING_V1` is an offline recording projection only. Its
namespace is `(portfolio_experiment_id,data_mode,price_source_basis,
global_config_hash)`. A frozen manifest must name the full candidate roster,
required invalidation/release records and cutoff. An incomplete or uncertified
batch yields `GROUPING_UNAVAILABLE`; every independent candidate remains stored.
Process the complete batch from empty state and save it atomically by manifest
hash. A later input needs a new manifest and full recomputation.

Order by mechanical availability, fixed priority tier (normal 0, second
pullback 1), then wrapper fingerprint. Same instrument/session/direction/source
mode candidates in the same portfolio experiment join a primary only when they
are at most 180 seconds from the original primary and both trigger and stop are
within `0.25 * primary_frozen_daily_ATR`. The anchor never moves. If several
groups qualify, choose least time distance, least normalized maximum price
distance, earliest primary time, then primary fingerprint. Each candidate joins
one group and all independent rows survive.

An opposite direction records `OPPOSITE_DIRECTION_CONFLICT`. Without a common
versioned calibration, the incumbent stays primary and confidence arbitration
is unavailable. Do not compare raw scores as probabilities. ORB ownership moves
to `OR_FAILURE_REV` only at the reversal's own trigger after the exact frozen
inside-range invalidation/release matches symbol, session, parent structure and
input IDs. The ORB event remains immutable. Another fade or continuation cannot
transfer ownership.

## 5. Cooldown, expiry and recovery

Preserve producer quotas. A new same-direction HOD structure and a new ORB
attempt require 600 seconds from the prior mechanical event; equality passes.
ORB also retains its reset and quota rules. Delivery time and a new wrapper do
not reset either clock.

Delivery-intent expiry is a fixed engineering rule: heads-up is the earlier of
structure expiry and availability plus 30 seconds; actionable is the earlier
of session close and trigger availability plus 120 seconds. Equality is expired.
This never deletes the historical candidate or changes entry/outcome clocks.
Recovery restores the original key, quotas, mechanical clock, group owner,
parent release and absolute expiry. Restart cannot extend a deadline.

## 6. Evidence limits

AT-08 and AT-09 must cover every boundary above, both directions, poor versus
unavailable results, stock independence, UTF-8 fingerprints, reordered and
incomplete batches, anchor grouping, conflicts, exact reversal release,
cooldowns, expiry equality and recovery. Synthetic supplied records prove only
this offline contract. Source units, complete chains, historical bid/ask,
executable fills, calibration, remaining strategies, M14/M15 completion,
profitability, shadow use and live use remain separate gates.
