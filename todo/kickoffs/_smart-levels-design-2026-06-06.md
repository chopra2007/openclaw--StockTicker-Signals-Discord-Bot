# Smart Technical Levels Engine — Implementation Design

Date: 2026-06-06
Author: lead architect (design pass)
Status: design-only, default-OFF, shadow-first
Target command: `!all`
Touches: `consensus_engine/alerts/all_command/levels.py`, `aggregator.py`, `structured_fields.py`, `config/consensus.yaml`

---

## 1. Plain-language summary

Right now, when the bot builds a trade plan for `!all`, it tries to gather buy/sell prices that YouTubers and news articles mentioned. If it can't find at least 4 of them after grouping the close ones together, it gives up and just guesses: "buy here, stop a bit lower, take profit a bit higher" using a fixed wiggle-size (the stock's average daily move, called ATR). In 12 out of 12 real runs we logged, the bot took that guess. So almost every headline buy/stop/target number we post is made-up math, not a real chart level.

This design teaches the bot to read the chart itself. From the daily price-and-volume bars it already downloads (about 63 days of them), it computes its OWN real levels the way a trader would, FIVE ways: prices where the stock bounced or stalled before (support/resistance), price bands where big buyers/sellers showed up (supply/demand zones), the classic Fibonacci pullback zones, the prices where the most shares actually traded (volume profile), and the untested high-volume shelves the market hasn't traded back to yet (virgin Points of Control — §3e, research-then-build). It treats each of these computed levels exactly like a level a YouTuber gave it, so they flow through the same grouping machinery and stack up. When a Fibonacci level lands right on a YouTuber's level, that's a high-confidence agreement and it scores higher. The result: the bot reaches the "4 real levels" bar honestly, so it posts chart-grounded buy/stop/target zones with a confidence score and a risk-vs-reward number, instead of the fixed-wiggle guess. The guess stays only as a last resort, and the whole thing ships OFF first, logging side-by-side comparisons before it ever changes a posted message.

---

## 2. Integration plan

### 2.1 The core idea: technical levels ARE Anchor objects

The existing pipeline in `levels.py` is anchor-based:

```
extract_anchors_from_youtube_levels(rows)   -> [Anchor(source_type="yt_curated"|"yt")]
extract_swing_levels(candles)               -> [Anchor(source_type="swing")]
extract_anchors_from_search_snippets(snips) -> [Anchor(source_type="web")]
    |
cluster_anchors(all, threshold_pct=0.005)   -> merge within 0.5%
    |
rank_anchors(all, current_price, ticker=)   -> (supports_below, resistances_above)
    |
select_trade_plan(...)                       -> {sl, tp1, tp2, tp3, confidence, suppression_reason}
```

The new engine produces the same `Anchor` dataclass with **four new `source_type` values**, so its output enters the SAME `cluster_anchors`/`rank_anchors` machinery and merges with crowd anchors:

| source_type | method | meaning |
|---|---|---|
| `tech_sr` | swing-pivot S/R + round numbers (§3a) | horizontal level from clustered pivots |
| `tech_zone` | supply/demand zones (§3b) | base+impulse zone edge |
| `tech_fib` | Fibonacci retracement/extension (§3c) | golden-pocket / extension level |
| `tech_vp` | volume profile + (anchored) VWAP (§3d) | POC / VAH / VAL / HVN / AVWAP line |
| `tech_vpoc` | virgin/naked Point of Control (§3e) | an untested prior-session POC the market tends to revisit |

The `Anchor` dataclass already carries everything we need (no schema change): `price`, `source`, `source_type`, `touches`, `volume_strength`, `freshness_days`, `source_count`, `cluster_source_types`. We add **one optional field** to carry the per-level method confidence and the human-readable strength (so the assembler and embed can label each level):

```python
@dataclass
class Anchor:
    ...                                  # existing fields unchanged
    method_strength: Optional[float] = None   # 0-100 strength from the producing method (§3 scoring)
    method_label: Optional[str] = None        # e.g. "golden-pocket 0.618", "POC", "DBR demand", "swing-low x3"
```

### 2.2 Tier ordering for the new source_types

`SOURCE_TIER_ORDER` in `levels.py` currently is `("yt_curated", "swing", "yt", "web")` and `_max_tier` resolves a merged cluster's `source_type`. Technical levels must NOT outrank a real curated YouTuber level, but they SHOULD outrank a bare web snippet. New order:

```python
SOURCE_TIER_ORDER = (
    "yt_curated",   # human-curated YouTuber level
    "swing",        # raw 3-bar pivot (legacy)
    "tech_sr",      # clustered multi-touch pivot S/R
    "tech_vp",      # volume node / VWAP
    "tech_vpoc",    # virgin/naked POC (untested prior-session magnet)
    "tech_zone",    # supply/demand zone
    "tech_fib",     # fib level
    "yt",           # parsed YouTube mention
    "web",          # web snippet
)
```

Add the four new keys to `SCORE_V2_TIER_MULTIPLIERS` (shadow-score v2 path) so the existing v2 scoring doesn't fall through to the `yt` default of 0.5:

```python
SCORE_V2_TIER_MULTIPLIERS = {
    "yt_curated": 1.0, "swing": 0.7,
    "tech_sr": 0.75, "tech_vpoc": 0.70, "tech_vp": 0.65, "tech_zone": 0.6, "tech_fib": 0.55,
    "yt": 0.5, "web": 0.2,
}
```

Rationale: a clustered multi-touch pivot (`tech_sr`) is nearly as trustworthy as a curated human level; a fib level alone (`tech_fib`) is the weakest technical because it only matters with confluence — which is exactly what the confluence bonus rewards.

### 2.3 The fallback LADDER

`select_trade_plan` is extended to a 3-rung ladder. The new engine's anchors are added to the pool BEFORE the existing `total >= 4` gate, so rung 1 is reached far more often.

```
RUNG 1  real + technical anchors:
        crowd anchors (yt/swing/web) + technical anchors (tech_*) all clustered together.
        If clustered total >= cfg(min_anchors_for_plan, 4)  AND a valid SL + >=1 TP survive
        the drawdown/horizon gates  -> emit anchor-derived plan (confidence by §5).

RUNG 2  technical-only plan:
        if rung 1 fails the count gate but technical anchors alone yield a
        coherent structure plan (>= 1 strong support + >= 1 strong resistance,
        chosen entry support method_strength >= cfg(min_entry_strength, 55))
        -> emit technical-only plan, confidence "medium" max.

RUNG 3  ATR last resort (UNCHANGED _compute_atr_fallback):
        spot -+ 1/2/3 x ATR, confidence "low", R:R suppressed (as today).
```

Only when the flag is OFF, or both rung 1 and rung 2 produce nothing, do we hit rung 3. When the flag is OFF entirely, behavior is byte-for-byte today's (gate at 4 crowd anchors -> ATR fallback).

### 2.4 New flag + shadow-mode rollout

New config key (default OFF):

```yaml
all_command:
  levels:
    technical_engine_enabled: false        # master switch for the whole engine
    technical_engine_shadow_mode: true     # when enabled, COMPUTE + LOG but do not change posted plan
```

Three-state rollout (mirrors the existing `score_v2_shadow_mode` pattern already in `rank_anchors`):

1. **State A — fully off** (`technical_engine_enabled: false`): no technical anchors generated. This is the ship state. Zero risk.
2. **State B — shadow** (`enabled: true`, `shadow_mode: true`): technical anchors ARE generated and a parallel "what the plan WOULD have been" is computed and written to a shadow log (§8), but the **posted** plan still uses the crowd-only pipeline. We compare logs for N runs.
3. **State C — live** (`enabled: true`, `shadow_mode: false`): technical anchors enter the real pool; the posted plan is the ladder plan. R:R renders for rung-1/rung-2 plans.

Direction-awareness threads through unchanged: the aggregator already computes `_direction_for_plan` (BULLISH/BEARISH/NEUTRAL) and passes it to `select_trade_plan`. Every method below is direction-aware (long AND short); NEUTRAL still wipes levels exactly as today (`aggregator.py:942`).

---

## 3. Methods (exact formulas, computable on ~63 daily bars)

**Shared inputs** (all already in the aggregator payload — no new API call):

- `candles = data["daily_candles"]` — list of `{high, low, close, volume}` dicts, ~63 bars chronological, from `patterns.fetch_daily_candles(ticker, "3mo")` (aggregator line 204-208). **NOTE: there is no `open` key** (verified in `patterns.py:65-67`). Methods needing a body/open approximate `open[i] := close[i-1]` (prior close), and use true-range for impulse sizing so overnight gaps still count.
- `P = current_price` (`_current_price(data["technical_long"])`).
- `atr14` = `indicators.atr(highs, lows, closes, 14)` (already imported; aggregator passes `_atr_from_candles`, but the engine should recompute from `candles` so it never gets a stale/None ATR — fall back to `atr(highs,lows,closes,14)` then to `mean(high-low)` over the window if `atr()` returns None).
- `wk52_high, wk52_low, analyst_target_high/low, prev_close` from `snapshot.fetch_ticker_snapshot` (already fetched; in `data` via the snapshot task). Used as boundary levels and sanity clamps.

**Window upgrade (optional, recommended):** change the `fetch_daily_candles` task call (aggregator line 204-208) to request `"6mo"` so S/R and volume profile see ~126 bars (stronger levels). `52wk hi/lo from snapshot are still passed separately as always-valid boundaries.` Keep `"3mo"` if latency budget is tight; all formulas below are written to work on 63 bars.

Define once, used by every method:

```
TOL = max(0.5 * atr14, 0.005 * P)     # cluster/merge band: half an ATR, floored at 0.5% of price
```

Each method returns `list[Anchor]`. Each anchor gets `method_strength` (0-100) and `method_label`. The producer maps `method_strength -> Anchor.touches/volume_strength/source_count` so the EXISTING v1 `_score` (touches*2 + volume_strength*1.5 + source_count*3 + freshness) ranks them sensibly without rewriting `_score`:

```
touches         = round(method_strength / 20)         # 0..5, mirrors touch caps
volume_strength = method_strength / 50                # 0..2 range used by _score
source_count    = 1                                    # bumps to N when clustered (existing behavior)
freshness_days  = bars_since_most_recent_evidence
```

---

### 3a. Swing-pivot S/R + round numbers  -> `source_type="tech_sr"`

Replaces the naive 3-bar `extract_swing_levels` for plan purposes (the legacy function stays for back-compat/`swing` tier).

**STEP 1 — pivot detection (symmetric fractal, n=2).** For `2 <= i <= len-3`:
```
swing_high(i) = high[i] > high[i-1] and high[i] > high[i-2] and high[i] > high[i+1] and high[i] > high[i+2]
swing_low(i)  = low[i]  < low[i-1]  and low[i]  < low[i-2]  and low[i]  < low[i+1]  and low[i]  < low[i+2]
```
Store `{price, bar_index i, volume[i]}`. **Look-ahead guard:** the last 2 bars cannot be confirmed pivots — never emit them. (Optional n=3 pass for major-only swings; n=2 is the default, needs only 5 bars.)

**STEP 2 — cluster tolerance.** `TOL` as defined above.

**STEP 3 — cluster pivots into levels.** Sort pivot prices ascending; greedy single-linkage: keep adding while `(next_price - cluster_min) <= TOL`. Per cluster:
```
level_price = sum(p_k * vol_k) / sum(vol_k)      # volume-weighted (equal-weight if median vol tiny/missing)
touches     = count of pivots in cluster
tag         = 'support' if majority swing-lows else 'resistance' (ties -> by position vs P)
```
Discard clusters with `touches < 2` UNLESS the lone pivot is a 52wk extreme or within `TOL` of a round number (those survive as `touches=1`, hard-capped at strength 40). Merge any two final levels within `TOL` (combine touches, recompute volume-weighted price).

**STEP 4 — role-reversal flip.** A `support` level with a later bar `close < level - TOL` AND a still-later bar `close > level` retags `resistance(flipped)`; mirror for resistance. Flipped levels keep touch history and get `flip_bonus`.

**STEP 5 — round-number overlay.** Increment R by magnitude: `P<20 -> 1; 20<=P<100 -> 5; 100<=P<500 -> 10; 500<=P<1000 -> 50; P>=1000 -> 100`. For each multiple of R in `[wk52_low, wk52_high]` within `TOL` of a computed level: `round_number_flag += 1`. Naked round numbers in range emit as `touches=1` (strength-capped 40).

**STEP 6 — classify vs P:** levels below P = support candidates, above P = resistance candidates.

**Strength scoring (0-100):**
```
touch_score   = min(touches, 5) / 5
recency_score = 0.5 ** (bars_since_most_recent_touch / 21)
volume_score  = clamp(avg_volume_at_touches / median_daily_volume, 0, 2) / 2
round_bonus   = 0.15 if round_number_flag else 0
flip_bonus    = 0.15 if flipped else 0
raw = 0.40*touch_score + 0.25*recency_score + 0.20*volume_score + round_bonus + flip_bonus
STRENGTH = round(100 * clamp(raw, 0, 1))
```
Tiers: >=70 strong, 45-69 moderate, <45 weak. Only emit anchors with STRENGTH >= 45; the chosen entry support must be >= 55 to lead a technical-only (rung 2) plan.

---

### 3b. Supply/demand zones  -> `source_type="tech_zone"`

Per bar derive: `range[i]=high-low`, `body[i]=abs(close[i]-close[i-1])` (open approximated as prior close), `trueRange[i]=max(high-low, abs(high-close[i-1]), abs(low-close[i-1]))`, `avgRange20=SMA(range,20)`, `avgVol20=SMA(volume,20)`.

**STEP 1 — scan bases.** Window `B in {1..5}`. Candidate base `[s..e]`, `e=s+B-1`:
```
baseHigh=max(high[s..e]); baseLow=min(low[s..e]); baseWidth=baseHigh-baseLow
(a) TIGHTNESS:  baseWidth <= cfg(base_tightness_atr, 0.5) * atr14
(b) INDECISION: every base candle body[i] <= 0.5 * range[i]
```

**STEP 2 — require impulse.** Next `K=3` bars:
```
DEMAND: impulseMove = max(close[e+1..e+K]) - baseHigh
SUPPLY: impulseMove = baseLow - min(close[e+1..e+K])
(a) impulseMove >= cfg(impulse_atr_mult, 1.0) * atr14   (measure with trueRange so gaps count)
(b) >= 2 of the K departure candles are ERC: body[j] >= 0.5*range[j] AND trueRange[j] >= 1.0*avgRange20,
    all same direction (bullish for demand, bearish for supply)
```
Classify by leg-in over `L=3` bars before s: DEMAND drop-in -> DBR (reversal, stronger); rise-in -> RBR (continuation). SUPPLY rise-in -> RBD (reversal); drop-in -> DBD (continuation).

**STEP 3 — draw zone.** DEMAND: `proximal=baseHigh` (entry edge), `distal=baseLow` (stop edge). SUPPLY: `proximal=baseLow`, `distal=baseHigh`. Emit TWO anchors per zone (proximal + distal) so both flow into clustering; tag proximal as the actionable edge.

**STEP 4 — freshness T.** After the impulse, count distinct re-entries (low<=proximal for demand / high>=proximal for supply) AFTER price first moved `>=1*atr14` away. Drop zones with `T>=3`.

**STEP 5 — select vs P.** BUY = highest-scoring fresh demand with `proximal < P`. TARGET = lowest supply with `distal > P`. Discard zones whose distal is within `0.5*atr14` of P; dedup overlapping zones (>50% overlap -> keep higher score).

**Strength scoring (0-100):**
```
1) IMPULSE (35): impulse_atr = impulseMove/atr14; 35 * clamp((impulse_atr-1.0)/(3.0-1.0), 0, 1)
                 (+5 if departure was 1 candle, +3 if 2)
2) VOLUME  (25): volRatio = max(vol over K impulse bars)/avgVol20; 25 * clamp((volRatio-1.0)/(2.0-1.0), 0, 1)
3) FRESHNESS(25): T=0 ->25; T=1 ->12; T=2 ->4; T>=3 -> reject
4) TYPE/TIGHTNESS(15): reversal(DBR/RBD)=10, continuation(RBR/DBD)=5;
                 + tightness up to 5: 5*clamp((0.5*atr14 - baseWidth)/(0.5*atr14), 0, 1)
```
If `avgVol20 ~ 0` or volume missing, drop factor 2 and renormalize over the remaining 75. Labels: >=75 strong, 50-74 moderate, 30-49 weak, <30 discard. Emit anchors scoring >=50.

---

### 3c. Fibonacci retracement + extension  -> `source_type="tech_fib"`

**STEP 1 — pivots** (fractal `k=3` default; confirm only `k` bars back; last `k` bars unconfirmed).

**STEP 2 — pick anchor leg.** For each adjacent (low->high) or (high->low) pivot pair:
```
leg_size      = abs(priceB - priceA)
significance  = leg_size / atr14            # require >= 2.0 ATR
recency_weight= max(0, 1 - (N-1 - idxB)/30)
leg_score     = (leg_size/atr14) * (0.5 + 0.5*recency_weight)
```
Pick max `leg_score`. UP-leg (A=low, B=high, priceB>priceA) -> LONG; DOWN-leg -> SHORT. Fallback if none clears 2.0 ATR: anchor to rolling 63-bar extreme low/high, direction = which extreme is LATER (apply -15 score penalty).

**STEP 3 — retracements.** `H=max(A,B)`, `L=min(A,B)`, `R=H-L`. UP-leg: `level = H - r*R`; DOWN-leg: `level = L + r*R`. `r in {0.236, 0.382, 0.5, 0.618, 0.65, 0.786}`. Golden pocket = `[H-0.65R, H-0.618R]` (UP); entry midpoint `r=0.705`. Flag setup ACTIVE when P inside the pocket.

**STEP 4 — stop.** UP long: `(H - 0.786R) - 0.25*atr14` (wider variant: `priceA - buffer`). DOWN short: `(L + 0.786R) + 0.25*atr14`.

**STEP 5 — extensions.** Retracement point `C = P` if P inside the pullback else most-recent opposite pivot after B. UP: `target = C + e*R`; DOWN: `target = C - e*R`. `e in {1.0, 1.272, 1.414, 1.618, 2.0, 2.618}`. TP1=1.272, TP2=1.618 (primary), TP3=2.0. Simple variant if C undefined: `B + (e-1)*R` (lower score). **Clamp:** drop targets `> wk52_high*1.5` (long) or `< wk52_low/1.5` (short).

**STEP 6 — confluence boost** is handled centrally in §4 (the cluster step), not here — a fib level landing within `TOL` of a pivot/round/MA naturally clusters and gets the confluence bonus.

**Strength scoring (0-100):**
```
base by ratio:  0.618/0.65/1.618 = +40 ; 0.5/0.786/1.272 = +30 ; 0.382/2.0 = +20 ; 0.236/1.414/2.618 = +10
anchor quality: + min(20, 10*(leg_size/atr14 - 2)) ; + 15*recency_weight
volume:         + 8 if anchor pivot bar volume > 1.5x 63-bar avg
penalties:      -15 fallback-extremes leg ; -10 extension tripped 52wk clamp ; -10 if < ~30 valid bars
STRENGTH = clamp(sum, 0, 100)
```
Buckets: >=70 strong, 40-69 medium, <40 weak. **Unit-test invariant:** long targets above entry, short targets below (the LuxAlgo sign-bug pitfall).

---

### 3d. Volume profile (POC/VAH/VAL/HVN/LVN) + (anchored) VWAP  -> `source_type="tech_vp"`

**A. Volume profile.**
```
R_low=min(low); R_high=max(high); Span=R_high-R_low
binW = max(Span/50, 0.25*atr14); N = clamp(ceil(Span/binW), 20, 60)
```
Distribute each bar's volume by uniform spread across `[low,high]`: for each overlapping bin k add `vol_i * overlap_len / (high_i - low_i)` (if `high==low`, dump in bin of close). **POC** = center of max-volume bin. **Value Area (70%):** start at POC bin; iteratively compare SUM of next-two bins above vs below, add heavier pair, until cumulative `>= 0.70*total`; tie -> side closer to POC, then upper. VAH/VAL = top/bottom edges. **Nodes:** 3-bin moving-average smooth; HVN = local max AND `>= 1.3*mean(bin)`; LVN = local min AND `<= 0.6*mean(bin)`.

**B. Anchored VWAP.** Anchor bar: LONG = most recent swing LOW (±3-bar fractal, prefer last ~20 bars; fallback 63-bar low); SHORT = swing HIGH. Alt anchor = highest-volume bar in last 20, or largest `|close_i - close_{i-1}|` (gap proxy). From anchor a to latest t with `TP_i=(high+low+close)/3`:
```
AVWAP = sum(TP_i*vol_i) / sum(vol_i)
sigma = sqrt( sum(vol_i*(TP_i-AVWAP)^2) / sum(vol_i) )
bands = AVWAP +/- 1*sigma, +/- 2*sigma
```
Also a window-VWAP anchored at bar 0 as a second reference. (Reuse `indicators.vwap` for the plain cumulative version; AVWAP needs the slice + sigma computed here.)

**Emit anchors:** POC (label "POC"), VAH, VAL, each HVN, AVWAP and AVWAP±1σ as level anchors. LVNs are emitted but flagged `is_lvn=True` and EXCLUDED as stop locations (price slices through them — §5).

**Strength scoring (0-100):**
```
1) Volume concentration (0-35): POC/HVN -> 35*(bin_volume/max_bin_volume); VAH/VAL use boundary-bin volume
2) Touch/test (0-20): distinct prior bars whose [low,high] overlapped within 0.25*atr14 of the level; min(20, touches*5)
3) Confluence (0-25): +12 if two methods agree within 0.5*atr14, +13 if three+   (computed in §4)
4) Recency (0-10): re-profile with exp decay half-life ~20 bars; 10*(recent_share of that bin)
5) VWAP slope (0-10): +10 if AVWAP slope over last 10 bars rising (for a long support); mirror for shorts
DISCOUNT all HVN/LVN node scores by ~10% (daily bars have no true intrabar tape).
```
Buckets: >=75 strong, 50-74 moderate, <50 weak. Emit >=50. **80%-rule flag:** if today's first bar opened outside `[VAL,VAH]` and price re-entered and closed inside (ideally 2 closes), set a `value_area_play` flag toward the opposite boundary; surfaced to the assembler as a target hint, not a separate anchor.

---

### 3e. Virgin / Naked Point of Control (untested prior-session POC)  -> `source_type="tech_vpoc"`

**RESEARCH-THEN-IMPLEMENT (added per user request — research this method live before coding, then build it).** First confirm the exact definitions and trading rules against current volume-profile sources (search "point of control", "virgin POC / naked POC / vPOC / nPOC", "untested POC magnet"); the framing below is the intended design — adjust the specifics if the literature is clearer. This is DISTINCT from the §3d composite POC (which is the single POC of the whole window): here we want the SET of prior-period POCs that price has not yet returned to.

**Concept.** Every trading period (a session, or a week) has its own POC — the price where that period traded the most volume. When price later moves away from a period's POC and NO subsequent bar trades back through it, that POC stays "virgin" / "naked" — an unfilled high-volume shelf that the market statistically tends to revisit. Virgin POCs above spot are upside magnets/targets; below spot are downside magnets/support. They are valued because they mark unfinished business (a price the market paid a lot of attention to but hasn't retested).

**Computation on daily bars:**
- **STEP 1 — per-period POC.** Split the window into periods (default **per-week** = group ~5 daily bars; research whether per-day is better given only daily bars). For each period build a small volume-by-price profile (reuse §3d binning over that period's `[low, high]`, volume spread across the range) and take `POC_p` = center of the max-volume bin. With only one daily bar per "period", approximate `POC_p ≈ (high+low+close)/3` — weekly grouping gives a truer POC, so prefer it.
- **STEP 2 — virginity test.** For each `POC_p`, scan every LATER bar `q > p`: if any `[low_q, high_q]` contains `POC_p` (within `TOL`), the POC has been filled → discard. Survivors are the virgin POCs.
- **STEP 3 — classify vs spot.** Virgin POCs above `P` → resistance / upside-target anchors; below `P` → support / downside anchors. Drop any within `0.5*atr14` of `P`.
- **STEP 4 — emit** one `Anchor` per virgin POC (`method_label` e.g. `"vPOC wk 2026-05-12"`), so it clusters with the other four methods — a virgin POC landing on a fib extension or an S/R level is exactly the high-confluence signal we want.

**Strength scoring (0-100):**
```
1) Source volume (0-40):  40 * (period_volume_at_poc / max_period_poc_volume in window)   -- bigger-volume sessions' POCs are stronger magnets
2) Recency      (0-25):  25 * 0.5 ** (periods_since_formed / half_life)  (half_life = 4 periods/weeks — CORRECTED 2026-06-06 from 8, per virgin-POC research)
                          (RESOLVED: recency is primary (half_life=4), AND add a survival bonus +7 when
                           periods_since_formed >= 2*half_life — you MUST implement this branch; the design
                           originally lacked it. Captures the "overdue magnet" effect without inverting recency.)
3) Distance     (0-20):  20 * clamp(1 - distance_pct/0.5, 0, 1)         -- a magnet 50%+ away is not near-term
4) Cleanliness  (0-15):  +15 if no wick even grazed it (truly virgin); scaled down for near-misses within TOL
```
Buckets: >=70 strong, 45-69 moderate, <45 weak. Emit anchors scoring >=45.

**Direction handling.** The same set serves both sides — a virgin POC below is a long target / short-cover reference; above is a short target / long target. The assembler (§5) treats a strong virgin POC as a **high-priority TP candidate** (magnet); when one sits just beyond structure it becomes the natural TP3 / extended target. Add `extract_virgin_poc_levels` as the FIFTH extractor in `build_technical_anchors`. New config keys in §7: `vpoc_period`, `vpoc_half_life_periods`.

---

## 4. Confluence step (reuse existing machinery)

No new clustering code — we deliberately reuse `cluster_anchors(anchors, 0.005)` and the v2 confluence bonus that already exist.

1. Concatenate all anchors: `crowd_anchors + tech_sr + tech_zone + tech_fib + tech_vp`.
2. `cluster_anchors(all, threshold_pct=0.005)` merges anything within 0.5%. Because `cluster_anchors` already records `cluster_source_types` (the set of distinct `source_type`s in the merged cluster) and `source_count`, a cluster that contains e.g. `{tech_fib, yt_curated, tech_vp}` automatically registers 3 distinct sources.
3. **Enable the confluence bonus for go-live:** flip `all_command.confluence_bonus_enabled: true`. The existing `_confluence_bonus(cluster_source_types)` in `levels.py:129` already does `1.0 + (len(distinct_types) - 1) * SCORE_V2_CONFLUENCE_PER_TIER`. A fib level that lands on a YouTuber's level now gets the multi-source multiplier — exactly the "several unrelated tools agree" reward from the research.
4. `rank_anchors` splits supports/resistances and sorts. The number of distinct method families in a cluster IS the confluence count from the research (1=weak, 2=moderate, 3=strong, 4+=very strong). We expose it via `Anchor.cluster_source_types` for the assembler's confidence (§5).

**De-dup guard:** within a single method, two levels closer than `TOL` are merged at production time (each §3 method does its own intra-method merge) so the cross-method clustering measures genuine independence, not the same method counted twice — this matches the "cap each family's contribution" pitfall.

---

## 5. Trade-plan assembler

Extends `select_trade_plan` (keeps its signature + return shape; adds ladder + per-level metadata).

**Inputs (existing kwargs unchanged):** `supports, resistances` (now include technical anchors), `spot`, `atr14`, `direction`, `earnings_days`.

**ENTRY** — anchored on `spot` (no separate entry level today; keep that — `compute_risk_reward` already assumes spot is entry, `structured_fields.py:112`). For reporting, attach the nearest strong support (long) / resistance (short) as the "entry zone" label.

**STOP-LOSS — structure-vs-ATR hybrid** (research §5 assembly rule):
```
LONG:  structure_stop = best_support.price - buffer ;  buffer = max(0.10*atr14, 0.001*spot)
       IF best_support exists AND |spot - structure_stop| >= 1.0*atr14  -> use structure_stop
       ELIF best_support exists but distance < 1.0*atr14                -> widen to spot - 1.0*atr14
       ELSE (no clean structure OR atr14/spot > 0.04 fast regime)       -> atr_stop = spot - 2.0*atr14
       NEVER place the stop inside an LVN (tech_vp is_lvn) -> push below next HVN/strong support.
SHORT: mirror every sign; structure from best_resistance; atr_stop = spot + 2.0*atr14.
```
`risk_R = |spot - chosen_stop|`. Apply the EXISTING gates afterwards: drawdown gate (`abs(spot-sl)/spot > sl_max_drawdown_pct`, default 0.20) and short-horizon `>3*atr14` gate. If a gate trips, drop to the next-best structure stop before falling to ATR.

**TAKE-PROFIT ladder** — profit-side anchors (long = resistances above spot; short = supports below), sorted by distance:
```
TP1 = first profit-side level; floor at spot +/- 1.0*risk_R
TP2 = next profit-side level;  floor at spot +/- 2.0*risk_R
TP3 = next major (52wk extreme / round number / fib 1.272-1.618 extension); cap at wk52 hi/lo
If < 3 distinct profit-side levels, fill missing TPs with R-multiple defaults (1R/2R/3R) and flag them as fillers.
```

**Minimum reward:risk gate (load-bearing):**
```
RR_nearest = |TP1 - spot| / risk_R
REJECT plan if RR_nearest < cfg(min_reward_risk, 1.5)   (hard floor; prefer >= 2.0)
Also reject if no profit-side level inside the 52wk range.
DO NOT shrink the stop to manufacture a passing R:R — reject instead (research pitfall).
```

**Confidence** (replaces the binary low/None today):
```
distinct_types = len(entry cluster's cluster_source_types)
RR             = RR_nearest
"high"   if distinct_types >= 3 AND RR >= 2.0 AND no TP is a filler
"medium" if distinct_types == 2 OR (technical-only rung-2 plan) OR RR in [1.5, 2.0)
"low"    if ATR-fallback (rung 3) -- unchanged, R:R stays suppressed
```

**Output shape** (superset of today's dict — additive, existing keys unchanged):
```python
{
    "sl": float, "tp1": float, "tp2": float, "tp3": float,         # existing
    "suppression_reason": Optional[str],                            # existing
    "confidence": "high"|"medium"|"low"|None,                       # existing key, richer values
    # NEW (only populated when technical engine on; None/absent otherwise):
    "entry": float,                       # = spot (explicit for clarity)
    "risk_reward": Optional[float],       # RR_nearest, mirrors structured_fields.compute_risk_reward
    "rung": 1|2|3,                        # which ladder rung produced the plan
    "levels": [                           # per-level provenance for the embed/LLM
        {"role": "entry"|"stop"|"tp1"|"tp2"|"tp3",
         "price": float, "method": "tech_fib"|"tech_sr"|..., "label": "golden-pocket 0.618",
         "strength": 0-100, "confluence_sources": ["tech_fib","yt_curated"], "is_filler": bool},
        ...
    ],
}
```
All numeric outputs `round(x, 2)` at source (the float-precision-leak lesson — `levels.py:468`).

**R:R rendering:** `structured_fields.compute_risk_reward` currently returns None when `trade_plan_confidence == "low"` (`structured_fields.py:117`). Keep that — rung-3 ATR plans stay suppressed. Rung-1/rung-2 plans now carry `"high"`/`"medium"` confidence, so R:R renders for them. No change to `structured_fields.py:117` logic; it works correctly with the richer confidence values.

---

## 6. New function signatures + slots

### `levels.py` (new — all return `list[Anchor]` with `method_strength`/`method_label`):

```python
def extract_sr_levels(candles: list[dict], current_price: float, atr14: float,
                      wk52_high: float, wk52_low: float,
                      pivot_n: int = 2) -> list[Anchor]:                 # §3a -> tech_sr

def extract_supply_demand_zones(candles: list[dict], current_price: float,
                                atr14: float) -> list[Anchor]:          # §3b -> tech_zone

def extract_fib_levels(candles: list[dict], current_price: float, atr14: float,
                       wk52_high: float, wk52_low: float,
                       pivot_k: int = 3) -> list[Anchor]:               # §3c -> tech_fib

def extract_volume_profile_levels(candles: list[dict], current_price: float,
                                  atr14: float) -> list[Anchor]:        # §3d -> tech_vp (POC/VAH/VAL/HVN/LVN/AVWAP)

def extract_virgin_poc_levels(candles: list[dict], current_price: float,
                              atr14: float, period: str = "week") -> list[Anchor]:  # §3e -> tech_vpoc

def build_technical_anchors(candles: list[dict], current_price: float, atr14: float,
                            wk52_high: float, wk52_low: float) -> list[Anchor]:
    """Orchestrator: runs the five extractors, returns the concatenated tech_* anchors.
    No clustering here — the aggregator clusters tech + crowd together (§4)."""

# Helpers (private):
def _fractal_pivots(candles, n) -> tuple[list, list]    # (highs, lows) of {price,idx,volume}
def _avwap(candles, anchor_idx) -> tuple[float, float]  # (avwap, sigma)
def _value_area(bins) -> tuple[int, int, int]           # (poc_idx, vah_idx, val_idx)
```

`select_trade_plan` — extend in place: add ladder logic (rungs 1/2/3) + populate `entry/risk_reward/rung/levels`. Signature unchanged (all new kwargs default to preserve current callers/tests). Add `SOURCE_TIER_ORDER` + `SCORE_V2_TIER_MULTIPLIERS` entries (§2.2). Add the two new `Anchor` fields (§2.1).

### `aggregator.py` — slot at lines 881-913 (the existing anchor block):

```python
all_anchors = levels.cluster_anchors(initial_anchors + web_anchors, 0.005)   # existing
current_price = _current_price(data["technical_long"]) or 0.0

# NEW — technical engine (flag-gated)
if cfg.get("all_command.levels.technical_engine_enabled", False):
    _candles = data["daily_candles"] if isinstance(data["daily_candles"], list) else []
    _atr = _atr14_for_plan or indicators.atr(
        [c["high"] for c in _candles], [c["low"] for c in _candles],
        [c["close"] for c in _candles], 14)
    # !!! CORRECTED 2026-06-06 (Pass-0 + review): the next 4 lines were WRONG — `ticker_meta` is the
    # DB metadata dict (no 52wk data); the snapshot is `data["snapshot"]` and it defaults to None.
    # `week52_high`/`week52_low` keys never existed. Use the raw keys added in plan Wave 0.3 + `or {}`.
    _snap = data.get("snapshot") or {}   # `or {}` — snapshot defaults to None, NOT {}
    tech_anchors = levels.build_technical_anchors(
        _candles, current_price, _atr or 0.0,
        wk52_high=_snap.get("wk52_high") or current_price,   # raw key added in Wave 0.3 (was week52_high)
        wk52_low=_snap.get("wk52_low") or current_price)     # raw key added in Wave 0.3 (was week52_low)
    if cfg.get("all_command.levels.technical_engine_shadow_mode", True):
        _shadow_plan = levels.select_trade_plan(    # compute but don't use
            *levels.rank_anchors(levels.cluster_anchors(all_anchors + tech_anchors, 0.005),
                                 current_price, ticker=ticker),
            spot=current_price, atr14=_atr, direction=_direction_for_plan,
            earnings_days=_earnings_days_for_plan)
        _log_smart_levels_shadow(ticker, trade_plan, _shadow_plan)   # §8
    else:
        all_anchors = levels.cluster_anchors(all_anchors + tech_anchors, 0.005)

supports, resistances = levels.rank_anchors(all_anchors, current_price, ticker=ticker)   # existing line 883
...
trade_plan = levels.select_trade_plan(...)   # existing line 907, unchanged call
```

(`indicators` is already imported in the levels module path; add `from consensus_engine.analysis import indicators` in aggregator if not present.)

### `structured_fields.py`:

No logic change required. `compute_risk_reward` (line 101) already suppresses on `"low"` and renders otherwise — works with the new `"high"`/`"medium"` values. Optionally add `compute_levels_provenance(trade_plan) -> str` to surface the per-level method labels in the embed footer ("entry: golden-pocket 0.618 + LunaTrades; stop: swing-low x3"), reading `trade_plan["levels"]`.

---

## 7. Config keys (defaults)

```yaml
all_command:
  confluence_bonus_enabled: false        # EXISTING — flip true at go-live (§4)
  score_v2_shadow_mode: true             # EXISTING — unchanged
  levels:
    sl_max_drawdown_pct: 0.20            # EXISTING — unchanged
    technical_engine_enabled: false      # NEW — master switch (§2.4)
    technical_engine_shadow_mode: true   # NEW — compute+log only when enabled
    candle_range: "3mo"                  # NEW — "6mo"/"1y" for stronger S/R (§3 window upgrade)
    min_anchors_for_plan: 4              # NEW — rung-1 count gate (matches today's hard-coded 4)
    min_entry_strength: 55               # NEW — rung-2 technical-only entry support floor
    min_reward_risk: 1.5                 # NEW — hard R:R floor (§5 gate)
    pivot_n: 2                           # NEW — S/R fractal window (§3a)
    pivot_k: 3                           # NEW — fib fractal window (§3c)
    base_tightness_atr: 0.5              # NEW — supply/demand base width cap (§3b)
    impulse_atr_mult: 1.0                # NEW — supply/demand impulse threshold (§3b)
    vp_value_area_pct: 0.70              # NEW — volume-profile value area (§3d)
    vpoc_period: "week"                 # NEW — virgin-POC period granularity (§3e); research day vs week
    vpoc_half_life_periods: 4           # NEW — CORRECTED 2026-06-06 from 8 (research); weeks
    vpoc_survival_bonus: 7              # NEW — +7 when periods_since_formed >= 2*half_life (overdue magnet)
```

---

## 8. Real-data test plan

**Real test data available (verified):**
- `consensus.db` has `youtube_levels` with **321 rows** (crowd anchors to merge against).
- The engine fetches live daily candles for ANY ticker via `patterns.fetch_daily_candles(ticker, "6mo")` — no key needed (Yahoo chart endpoint, public).
- `snapshot.fetch_ticker_snapshot` gives live 52wk hi/lo + analyst targets.
- Discord history is fetchable for before/after comparison (token in `.env.service`, requires a `User-Agent` header).

**Tickers to run** (mix of liquid trenders, rangers, gappers, high-priced, low-priced):
`NVDA, TSLA, AMD, AAPL, SPY, AMZN, PLTR, SOFI, MSTR, COIN` — covers the 12 historical ATR-fallback cases plus volatility/price-regime spread.

**Procedure:**
1. **Baseline capture (today's behavior):** run `python3 -m consensus_engine` `!all <ticker>` (or the dry-run aggregator path) with `technical_engine_enabled: false`. Record `trade_plan` (sl/tp1-3, confidence, suppression_reason, R:R) for all 10. Expectation from the audit: ~all hit `atr_fallback`, confidence "low", R:R suppressed.
2. **Shadow run:** set `technical_engine_enabled: true`, `shadow_mode: true`. Re-run all 10. `_log_smart_levels_shadow` writes one JSONL line per ticker to `.omc/logs/smart-levels-shadow.jsonl`:
   ```json
   {"ts":..., "ticker":"NVDA", "spot":..., "atr14":...,
    "baseline":{"rung":3,"sl":...,"tp1":...,"conf":"low","rr":null,"reason":"atr_fallback"},
    "shadow":  {"rung":1,"sl":...,"tp1":...,"tp2":...,"tp3":...,"conf":"high","rr":2.4,
                "anchor_count_crowd":3,"anchor_count_after_tech":11,
                "entry_method":"tech_fib+yt_curated","stop_method":"tech_sr","distinct_types":3}}
   ```
3. **Compare against Discord history:** pull the last real `!all <ticker>` embed via the Discord API (token + `User-Agent` from `.env.service`) and diff the posted ATR levels vs the shadow plan.

**What "good" looks like (acceptance bar):**
- **Rung escalation:** >= 7/10 tickers produce a rung-1 or rung-2 plan in shadow (vs 0/10 non-fallback today).
- **Anchor lift:** `anchor_count_after_tech >= 4` on >= 8/10 (the engine clears the count gate honestly).
- **Confluence:** >= 4/10 show `distinct_types >= 2` at the entry cluster (a technical level merged with a crowd level).
- **R:R sanity:** every emitted rung-1/2 plan has `1.5 <= rr <= 20`; no plan with a TP beyond `wk52*1.5`; no stop inside an LVN.
- **Direction:** at least 1 BEARISH ticker produces a coherent short plan (stop above resistance, TPs at supports below).
- **Spot-check vs a chart:** for NVDA and TSLA, manually eyeball that the computed POC/golden-pocket/S/R levels land where a human would draw them (compare to the live chart). A level the bot calls "strong" that sits on visibly thin air is a fail.
- **No regression when OFF:** with `enabled: false`, the 10 baseline plans are byte-identical to step 1.

**Promote to live (State C)** only after the shadow log meets the bar for one full soak window, then flip `shadow_mode: false` + `confluence_bonus_enabled: true`, re-run the 10, and confirm posted embeds now show chart-grounded SL/TP with R:R.

---

## 9. Risks + de-risking

| Risk | Mitigation |
|---|---|
| Bad computed level posted as authoritative (worse than an honest "low-confidence guess") | (a) flag default OFF; (b) shadow mode logs N runs before any posted change; (c) `min_entry_strength`/`min_reward_risk` gates reject weak setups; (d) per-level `method`+`strength`+`confluence_sources` in the embed so a reader sees WHY (e.g. "golden-pocket only, 1 source" reads as tentative). |
| Daily-bar volume profile is coarse (no intrabar tape) -> POC off | uniform-spread distribution (not single-bin); HVN/LVN scores discounted 10%; POC snapped to nearest plausible close; clustering with crowd anchors corrects drift. |
| 63-bar window misses the real multi-month swing / 52wk extremes | optional `candle_range: "6mo"`; 52wk hi/lo passed separately as always-valid boundaries; fib fallback-to-extremes path + thin-sample penalty. |
| Wrong fib anchor leg -> garbage levels | 2.0-ATR significance filter + recency weighting; fallback penalty -15; sign unit-test (long targets above entry, short below). |
| Look-ahead/repaint (last n bars not yet confirmed pivots) | every extractor drops the last `n`/`k` bars; documented in each §3 step. |
| Stop manufactured by shrinking risk to pass R:R | assembler REJECTS sub-1.5 R:R instead of tightening; 1.0-ATR minimum stop distance enforced. |
| Shared-file tripwire (`levels.py` is on the DoD list) | additive changes only (new functions, optional fields, flag-gated branch); when flag OFF the path is unchanged; full `!all` regression for the 10 tickers + the always-on service/gateway/symlink checks before any commit. |
| Touch-count inflation / double-counting correlated methods | intra-method merge within TOL; cross-method confluence counts DISTINCT `source_type` families only (existing `cluster_source_types` semantics). |
| Counter-trend short into a hard uptrend (supply zone overhead) | continuation zones weighted lower in scoring; NEUTRAL direction still wipes; assembler is direction-gated by `_direction_for_plan`. |

The flag-gate makes go-live a no-op until we choose otherwise; shadow mode turns the first real exposure into a logged dry run we grade against today's output before a single posted message changes. The R:R floor + per-level strength + confluence labeling mean even a live plan is self-describing, so a thin level never masquerades as a confirmed one.

---

WROTE design: 5 methods
