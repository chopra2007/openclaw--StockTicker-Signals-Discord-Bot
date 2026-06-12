# Eval Agent 2 — Issue 3: `!all` Fwd P/E shows 16, should be ~24

**Mode:** READ-ONLY investigation. No files edited. Live yfinance + Finnhub probed (data fetch only).
**Date:** 2026-06-11. **Live price used:** NVDA $204.87 (Finnhub `/quote` `c`, matches yfinance currentPrice).

---

## 1. ROOT CAUSE — CONFIRMED

`consensus_engine/scanners/snapshot.py` line 101:
```python
"fwd_pe": _num(info.get("forwardPE")),
```
`info` is obtained at line 60: `yf.Ticker(ticker).info or {}` (a single yfinance `.info` fetch, run in a 2-worker thread pool with an 8s timeout).

Current price for the existing 52-week math is computed at lines 110–112:
```python
price = (_num(info.get("currentPrice"))
         or _num(info.get("regularMarketPrice"))
         or _num(info.get("previousClose")))
```
So a price source already exists in the same struct (no extra fetch needed).

**Live proof the field is wrong:**
```
NVDA .info: forwardPE = 16.097, forwardEps = 12.72715, trailingEps = 6.53, currentPrice = 204.87
```
yfinance's `forwardPE` = price / `forwardEps`, and `forwardEps` = **12.727 = the NEXT full fiscal year (FY2028, ends Jan 2028) consensus EPS** (yfinance `+1y` avg = 12.682, ≈ 12.727). 204.87 / 12.727 = 16.1. **Confirmed: yfinance uses next-FY EPS, producing the low 16.** Root cause is exactly as diagnosed.

---

## 2. DATA AVAILABILITY — THE SUGGESTED FIX IS NOT BUILDABLE AS WRITTEN

The diagnosis says "sum the next 4 quarters' EPS estimates." **yfinance only exposes 2 forward quarters, not 4.** Tested on 5 tickers — identical structure every time:

`t.earnings_estimate` returns a DataFrame indexed by exactly `['0q', '+1q', '0y', '+1y']`:

| ticker | 0q | +1q | 0y (current FY) | +1y (next FY) | fwd quarters |
|--------|------|------|------|------|---|
| NVDA | 2.079 | 2.346 | 8.962 | 12.682 | **2** |
| AAPL | 1.895 | 2.011 | 8.757 | 9.667 | **2** |
| SOFI | 0.109 | 0.171 | 0.580 | 0.780 | **2** |
| MSFT | 4.237 | 4.615 | 16.812 | 19.342 | **2** |
| TSLA | 0.454 | 0.537 | 2.058 | 2.513 | **2** |

**Only 2 of the 4 NTM quarters ever have explicit quarterly estimates.** A literal "sum next 4 quarters" is impossible for every ticker.

**Quarter anchoring (does have dates):**
- `0q` = the **next quarter to be reported** (forward-looking, not yet reported). Proof: NVDA `t.earnings_dates` shows next earnings 2026-08-26 with EPS Estimate 2.08, which equals `0q` 2.079. That quarter **ends ~Jul 2026** (NVDA FY ends late Jan; quarters end ~Apr/Jul/Oct/Jan).
- `+1q` = the one after (~Oct 2026 quarter, reported ~Nov).
- `t.calendar` and `t.earnings_dates` give the actual report dates, and `info["mostRecentQuarter"]` / `lastFiscalYearEnd` / `nextFiscalYearEnd` give fiscal anchors. So the calendar mapping IS solvable.
- The two missing NTM quarters (Jan 2027, Apr 2027 for NVDA) have **no quarterly estimate** — they'd have to be derived from the annual (`0y`/`+1y`) figures.

**Fiscal-vs-calendar problem:** NVDA's FY ends in January, so its `0y` (FY2027) already includes the past Apr-2026 quarter (actual 1.87) that is NOT in the next 12 months. Any annual-based math has to subtract already-reported quarters.

---

## 3. THE TARGET NUMBER (~24 / "8.35") DOES NOT MATCH A TRUE 4-QUARTER NTM SUM

I built the best possible true rolling-NTM estimate for NVDA by stitching the 2 real quarters with the 2 derived ones:

```
0q (Jul26)        = 2.079   (real)
+1q (Oct26)       = 2.346   (real)
Q Jan27 (derived) = FY2027(8.962) - Q1act(1.87) - 0q - +1q = 2.666
Q Apr27 (derived) = FY2028(12.682)/4 = 3.171
NTM EPS = 10.262  ->  204.87 / 10.262 = P/E 20.0
```

**A correctly-built rolling-NTM number for NVDA is ~20, NOT ~24.** The diagnosis's own arithmetic (200 / 8.35 = 24) does not correspond to summing 4 forward quarters — 4 forward quarters sum to ~10.3, not 8.35.

**What "8.35 / ~24" actually is:** the **current fiscal year (`0y`) consensus EPS** basis.

| basis | EPS | NVDA P/E (live $204.87) |
|---|---|---|
| yfinance forwardPE (next FY, FY2028) | 12.73 | **16.1** ← the bug |
| true rolling-NTM (4 quarters, 2 derived) | 10.26 | ~20.0 |
| Finnhub free `forwardPE` (implied EPS 9.84) | 9.84 | 20.8 |
| **current-FY `0y` consensus EPS** | **8.96** | **22.9** ← closest robust path |
| user's stated 8.35 | 8.35 | 24.0 |

The user's 8.35 sits between `0y` avg (8.96) and `0y` low (8.20). Most retail sites that show "Forward P/E ≈ 24" for NVDA are using **current-FY consensus EPS**, which is the only basis that lands near the target. yfinance is the outlier because it uniquely uses next-FY EPS.

---

## 4. APPROACH EVALUATION

- **(A) Sum next 4 quarters** — **NOT POSSIBLE.** yfinance gives 2 forward quarters, 100% of the time, on every ticker tested. Reject.
- **(B) 0q + +1q + derive remainder from annual** — Buildable, but gives ~20 for NVDA (not 24), needs subtracting already-reported quarters and a naive split of next-FY/4. Most moving parts, most failure surface, and still misses the target. Reject.
- **(C) Direct NTM field from a provider** — Finnhub's `/stock/eps-estimate` and `/stock/price-target` are **403 (paid tier)**, confirmed live. But Finnhub's free `/stock/metric?metric=all` returns `forwardPE` (NVDA = 20.82, implied EPS 9.84) — different basis again, still not 24, and adds a second network dependency. Reject as primary.
- **(D) FY-weighted blend of two annual EPS** — gives ~19.8 for NVDA (double-counts past FY2027 quarters unless corrected; corrected ≈ same ~20 as B). Doesn't hit 24 either. Reject.
- **(E — RECOMMENDED) Current-fiscal-year (`0y`) consensus EPS.** `t.earnings_estimate.loc['0y','avg']` / current price. NVDA → 22.9 (≈ the user's 24, far better than 16). Single field, present on 5/5 tickers, no quarter stitching, no second provider.

### RECOMMENDED FORMULA
```python
ee = yf.Ticker(ticker).earnings_estimate          # already have the Ticker; one extra attr
eps_cfy = ee.loc['0y', 'avg']                      # current-fiscal-year consensus EPS
price = (info.get("currentPrice")
         or info.get("regularMarketPrice")
         or info.get("previousClose"))             # SAME price chain already at snapshot.py:110-112
fwd_pe = price / eps_cfy   if (eps_cfy and eps_cfy > 0 and price) else None
# fallback if 0y missing/invalid: omit, or fall back to info.get("forwardPE") with label "Fwd P/E (FY+1)"
```
Price comes from the existing `.info` price chain (no new fetch). `earnings_estimate` is one additional yfinance attribute on the Ticker already constructed in `_fetch_info` (note: `_fetch_info` currently returns only `.info`; it would need to also return `earnings_estimate`, or be refetched — a small change).

**Caveat for the implementer / user decision:** this delivers the number the user is anchored to (~24, current-FY basis), which is what retail sites show — but it is technically a *current-fiscal-year* P/E, not a true *rolling-next-12-calendar-months* P/E (that would be ~20). If the user genuinely wants strict calendar-NTM, the honest answer is ~20 and approach (B) is needed. The "~24" goal and the "rolling NTM" label are in tension; (E) honors the number, (B) honors the label. **Flag this to the user.**

---

## 5. FAILURE MODES + GRACEFUL FALLBACK (for recommended approach E)

| failure mode | behavior | fallback |
|---|---|---|
| `earnings_estimate` empty/throttled (yfinance returns {} like delisted) | `0y` missing | omit field, or fall back to `info["forwardPE"]` |
| `0y` EPS negative or zero (unprofitable co.) | P/E meaningless | omit field (don't show negative P/E) — same guard the smart-levels code uses |
| stale estimates | `eps_trend` shows estimates can lag; `0y` still the consensus | acceptable; this is consensus data, not real-time |
| fiscal-year companies (NVDA FY ends Jan) | `0y` is the correct current-FY figure regardless | handled — `0y` is fiscal-aware by definition |
| current quarter already partly reported | `0y` already blends actuals + estimates for the FY | handled — `0y` is the as-of consensus |
| price source mismatch | uses `.info` price chain; could differ slightly from Finnhub `/quote` | acceptable; both ~204.87 today, <0.1% drift |

**Graceful fallback recommendation:** if `0y` EPS is missing OR ≤ 0, omit the `fwd_pe` field entirely (cleanest — matches the file's existing "omit on no data" philosophy). A relabeled `info["forwardPE"]` (e.g. "Fwd P/E FY+1") is an option but reintroduces the confusing next-FY number, so prefer omission.

---

## CONFIDENCE ON HITTING ~24 FOR NVDA

- **Approach E (current-FY `0y` EPS): HIGH confidence of landing ~23–24 today.** Live: 204.87 / 8.96 = 22.9. Robust across all 5 tickers (0y present 5/5). This is the recommendation.
- **A true 4-forward-quarter NTM (the literal diagnosis): cannot be built (data missing) and would give ~20, missing the 24 target.** The diagnosis's "sum 4 quarters → 8.35 → 24" arithmetic does not hold up — 4 forward quarters actually sum to ~10.3.
- Net: the fix that satisfies the user's observed goal (~24, matching the retail sites) is the current-FY EPS basis, with a clear note that this is current-FY, not strict rolling-calendar-NTM.

---

## LIVE DATA APPENDIX

```
NVDA .info: forwardPE=16.097  forwardEps=12.727  trailingEps=6.53  currentPrice=204.87  previousClose=200.42

NVDA earnings_estimate (index 0q/+1q/0y/+1y):
            avg     low    high  numberOfAnalysts
0q      2.07925  2.031   2.20    40
+1q     2.34630  2.130   2.63    39
0y      8.96160  8.200   9.85    48     <- current FY (FY2027, ends Jan 2027)
+1y    12.68225  9.650  16.00    49     <- next FY (FY2028) = what yfinance forwardPE uses

NVDA earnings_dates: next = 2026-08-26 (EPS est 2.08 == 0q). last reported 2026-05-20 (1.87 actual).
NVDA fiscal: lastFiscalYearEnd=2026-01-25, mostRecentQuarter=2026-04-26, nextFiscalYearEnd=2027-01-25.

Finnhub (live, free key): /quote NVDA c=204.87 OK.
  /stock/eps-estimate  -> HTTP 403 (paid)
  /stock/price-target  -> HTTP 403 (paid)
  /stock/metric?all    -> OK; forwardPE=20.82 (implied EPS 9.84), peTTM=30.66, epsTTM=6.53

Cross-ticker forwardPE comparison (live):
TK     price   fh_fwdPE  fh_impEPS  yf_fwdPE  yf_0yEPS  PE_on_0y
NVDA  204.87    20.82     9.841     16.10     8.962     22.86
AAPL  295.63    33.39     8.854     30.81     8.757     33.76
SOFI   16.67    26.82     0.622     21.37     0.580     28.76
MSFT  390.34    23.46    16.638     20.18    16.812     23.22
TSLA  399.15   200.65     1.989    159.54     2.058    193.93
```
