#!/usr/bin/env python3
"""F1 historical back-test — the make-or-break, honest result.

Reconstructs the daily sector-rotation RRG quadrants POINT-IN-TIME with the
PRE-REGISTERED frozen params (volatility_regime_reversal_indicator/backtest/
preregistration_trade_edge.yaml: n=10, k=5, distance=2, persistence=2,
horizons 21/63d, BH-FDR q<0.1, seed 1729, null = lagging-quadrant-only) and
runs the decisive A/B from final-plan.md §0/§8:

  * forward 21d / 63d SECTOR return (vs the benchmark) following each state;
  * does the lagging->improving INFLECTION (and/or RS-Momentum) beat the
    RS-Ratio LEVEL signal, BOTH measured against a lagging-quadrant-ONLY
    opportunity-set null (the fair comparison set);
  * BH-FDR across the 13-ETF x horizon grid;
  * frozen-parameter transfer: recompute QQQ-relative + check SMH/XBI sign holds.

Data: ~max free daily OHLCV (auto_adjust=False, RAW close) for the 13 sector
ETFs + SPY + QQQ via yfinance into data/market_store, reusing the sandbox
parquet store (volatility_regime_reversal_indicator/src/data/store.py).

The math reuses consensus_engine.analysis.sector_rotation.compute_series (the
exact frozen point-in-time engine the live cron uses) — the back-test does NOT
re-implement the RRG.

Usage:
    python3 scripts/backtest_sector_rotation.py            # download (if needed) + run
    python3 scripts/backtest_sector_rotation.py --no-download   # use cached store only

A clean NO-GO (momentum ties/loses to level; inflection no better than the
lagging null) is a VALID, honest result and is reported plainly.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "volatility_regime_reversal_indicator"))

from consensus_engine.analysis import sector_rotation as sr  # noqa: E402

log = logging.getLogger("backtest_sector_rotation")

# Frozen pre-registered params (preregistration_trade_edge.yaml f1_sector_rotation)
N_WINDOW = 10
K_WINDOW = 5
DISTANCE = 2.0
PERSISTENCE = 2
HORIZONS = (21, 63)
BH_Q = 0.10
SEED = 1729
N_DRAWS = 2000
EPISODE_WINDOW = 21          # collapse same-ETF inflections within 21 trading days
BACKTEST_START = "2012-01-01"

STORE_DIR = str(ROOT / "data" / "market_store")
SECTOR_ETFS = sr.SECTOR_ETFS                 # 13
ALL_SYMBOLS = ("SPY", "QQQ", *SECTOR_ETFS)


# ---------------------------------------------------------------------------
# Pure, testable helpers (the test file exercises these without any download)
# ---------------------------------------------------------------------------

def forward_relative_returns(
    panel: pd.DataFrame, etf: str, benchmark: str, horizons: Iterable[int]
) -> pd.DataFrame:
    """Forward relative return (ETF minus benchmark) per date per horizon.

    Look-ahead-safe entry convention (mirrors event_study.forward_returns):
    a signal on the CLOSE of day i enters at the OPEN of day i+1 and exits at
    the CLOSE of day i+h. The relative return subtracts the benchmark's own
    same-window forward return, so it measures SECTOR-vs-market outperformance.
    """
    e_entry = panel[f"{etf}_open"].shift(-1)
    e_close = panel[f"{etf}_close"]
    b_entry = panel[f"{benchmark}_open"].shift(-1)
    b_close = panel[f"{benchmark}_close"]
    out: dict[int, pd.Series] = {}
    for h in horizons:
        e_ret = e_close.shift(-h) / e_entry - 1.0
        b_ret = b_close.shift(-h) / b_entry - 1.0
        out[h] = e_ret - b_ret
    return pd.DataFrame(out, index=panel.index)


def benjamini_hochberg(pvalues: list[float], q: float) -> tuple[list[bool], list[float]]:
    """BH-FDR. Returns (rejected mask aligned to input order, adjusted p-values).

    Standard step-up: sort p ascending, threshold p_(i) <= (i/m)*q; reject the
    largest such i and everything below it.
    """
    m = len(pvalues)
    if m == 0:
        return [], []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [0.0] * m
    rejected = [False] * m
    # adjusted p-values (monotone from the top)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        val = pvalues[i] * m / rank
        prev = min(prev, val)
        adj[i] = min(prev, 1.0)
    # rejection: largest k with p_(k) <= (k/m)*q
    kmax = 0
    for rank in range(1, m + 1):
        i = order[rank - 1]
        if pvalues[i] <= (rank / m) * q:
            kmax = rank
    for rank in range(1, kmax + 1):
        rejected[order[rank - 1]] = True
    return rejected, adj


def permutation_pvalue(
    observed_mean: float,
    pool: list[float],
    sample_size: int,
    n_draws: int = N_DRAWS,
    seed: int = SEED,
    alternative: str = "greater",
) -> float:
    """One-sided permutation p: draw `sample_size` from `pool` `n_draws` times,
    fraction of draw-means at least as extreme as `observed_mean` (+1 smoothing).

    `pool` is the lagging-quadrant-only opportunity set's forward returns; the
    observed mean is the inflection (or improving) group's mean. alternative
    'greater' = the signal should beat blindly buying a lagging sector.
    """
    pool_arr = np.asarray(pool, dtype=float)
    pool_arr = pool_arr[~np.isnan(pool_arr)]
    if sample_size <= 0 or len(pool_arr) < sample_size:
        return float("nan")
    rng = np.random.default_rng(seed)
    draws = np.empty(n_draws)
    for d in range(n_draws):
        draws[d] = rng.choice(pool_arr, size=sample_size, replace=False).mean()
    if alternative == "greater":
        hits = int(np.sum(draws >= observed_mean))
    elif alternative == "less":
        hits = int(np.sum(draws <= observed_mean))
    else:
        center = float(np.mean(draws))
        hits = int(np.sum(np.abs(draws - center) >= abs(observed_mean - center)))
    return (hits + 1) / (n_draws + 1)


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation; NaN-safe; NaN if <3 valid pairs or zero variance."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def spearman_p(x: list[float], y: list[float]) -> tuple[float, float, int]:
    """Spearman corr + two-sided p-value + n (via scipy); NaN-safe."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 3:
        return float("nan"), float("nan"), len(a)
    from scipy import stats
    r = stats.spearmanr(a, b)
    return float(r.statistic), float(r.pvalue), len(a)


def collapse_episodes(flags: list[bool], window: int) -> list[bool]:
    """Collapse True flags within `window` positions to the FIRST (episode entry)."""
    out = [False] * len(flags)
    last = -10 ** 9
    for i, f in enumerate(flags):
        if f and (i - last) >= window:
            out[i] = True
            last = i
    return out


# ---------------------------------------------------------------------------
# Data download + store (reuse sandbox parquet store)
# ---------------------------------------------------------------------------

def _get_store():
    """Import the sandbox parquet store, redirected to data/market_store."""
    from src.data import store as _store  # type: ignore
    _orig_get = _store.get

    def _patched_get(key, default=None):
        if key == "data.store_dir":
            return STORE_DIR
        return _orig_get(key, default)

    _store.get = _patched_get  # store_dir() = project_root()/ABS = ABS
    return _store


def download_and_store(store, symbols: Iterable[str], start: str,
                       force: bool = False) -> list[str]:
    """Download RAW OHLCV per symbol into the store. Returns the symbols that
    have usable data afterwards (missing/failed ones are reported, not fatal)."""
    import yfinance as yf
    have: list[str] = []
    for sym in symbols:
        if store.series_exists(sym) and not force:
            have.append(sym)
            log.info("[store] %s already cached, skipping download", sym)
            continue
        df = None
        for attempt in range(4):
            try:
                raw = yf.download(sym, start=start, interval="1d",
                                  auto_adjust=False, progress=False,
                                  group_by="column", threads=False)
                if raw is None or len(raw) == 0:
                    raise ValueError("empty frame")
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                cols = [c for c in ["Open", "High", "Low", "Close", "Volume"]
                        if c in raw.columns]
                df = raw[cols].dropna(how="any")
                if len(df) == 0:
                    raise ValueError("all-NaN after dropna")
                break
            except Exception as e:  # noqa: BLE001
                wait = 2 ** attempt
                log.warning("[dl] %s attempt %d failed (%s); retry in %ds",
                            sym, attempt + 1, e, wait)
                time.sleep(wait)
        if df is None or len(df) == 0:
            log.error("[dl] %s FAILED after retries — proceeding without it", sym)
            continue
        store.write_series(sym, df, source="yfinance", adjusted=False)
        have.append(sym)
        log.info("[store] wrote %s: %d rows %s -> %s", sym, len(df),
                 str(df.index.min().date()), str(df.index.max().date()))
    return have


# ---------------------------------------------------------------------------
# Rotation reconstruction (reuse the FROZEN engine; benchmark-swap for transfer)
# ---------------------------------------------------------------------------

def _closes_df_for(panel: pd.DataFrame, benchmark: str,
                   etfs: Iterable[str]) -> pd.DataFrame:
    """Build the closes_df sector_rotation.compute_series expects (a 'SPY' column
    = the benchmark's close, plus one column per ETF). For the QQQ transfer we
    simply feed QQQ's close in the 'SPY' slot — the frozen math is unchanged."""
    data = {"SPY": panel[f"{benchmark}_close"]}
    for etf in etfs:
        if f"{etf}_close" in panel.columns:
            data[etf] = panel[f"{etf}_close"]
    df = pd.DataFrame(data, index=panel.index).dropna(how="any")
    return df


def _analyse_benchmark(panel: pd.DataFrame, benchmark: str,
                       etfs: list[str], distance: float = DISTANCE) -> dict:
    """Run the full per-ETF state -> forward-return analysis for one benchmark.

    Returns a dict with per-ETF/per-horizon records and the pooled lagging-set
    momentum-vs-level race. ``distance`` defaults to the frozen pre-registered
    value; a non-registered robustness pass may override it.
    """
    closes_df = _closes_df_for(panel, benchmark, etfs)
    series = sr.compute_series(closes_df, N_WINDOW, K_WINDOW, distance, PERSISTENCE)
    # forward returns indexed on the same dates as closes_df
    fwd_panel = panel.reindex(closes_df.index)

    per_etf: list[dict] = []
    raw_inflections = 0
    # pooled lagging-set arrays for the momentum-vs-level race
    pooled = {h: {"rs_ratio": [], "rs_momentum": [], "fwd": []} for h in HORIZONS}

    for etf in etfs:
        cells = series.get(etf)
        if cells is None:
            continue
        fr = forward_relative_returns(fwd_panel, etf, benchmark, HORIZONS)
        quad = [c["quadrant"] if c else None for c in cells]
        rsr = [c["rs_ratio"] if c else np.nan for c in cells]
        rsm = [c["rs_momentum"] if c else np.nan for c in cells]
        infl_raw = [bool(c["inflection"]) if c else False for c in cells]
        raw_inflections += sum(infl_raw)
        infl = collapse_episodes(infl_raw, EPISODE_WINDOW)

        for h in HORIZONS:
            fwd = fr[h].to_numpy()
            # lagging opportunity set (the null) — forward returns on lagging days
            lag_idx = [i for i in range(len(cells))
                       if quad[i] == "lagging" and not np.isnan(fwd[i])]
            lag_fwd = [fwd[i] for i in lag_idx]
            # inflection episodes (lagging->improving), forward returns
            inf_idx = [i for i in range(len(cells))
                       if infl[i] and not np.isnan(fwd[i])]
            inf_fwd = [fwd[i] for i in inf_idx]
            # improving quadrant (broader) forward returns
            imp_idx = [i for i in range(len(cells))
                       if quad[i] == "improving" and not np.isnan(fwd[i])]
            imp_fwd = [fwd[i] for i in imp_idx]

            lag_mean = float(np.mean(lag_fwd)) if lag_fwd else float("nan")
            inf_mean = float(np.mean(inf_fwd)) if inf_fwd else float("nan")
            imp_mean = float(np.mean(imp_fwd)) if imp_fwd else float("nan")

            p_inf = (permutation_pvalue(inf_mean, lag_fwd, len(inf_fwd))
                     if inf_fwd and len(lag_fwd) >= len(inf_fwd) else float("nan"))

            # momentum-vs-level race WITHIN the lagging opportunity set
            lag_rsr = [rsr[i] for i in lag_idx]
            lag_rsm = [rsm[i] for i in lag_idx]
            corr_level = spearman(lag_rsr, lag_fwd)
            corr_mom = spearman(lag_rsm, lag_fwd)

            pooled[h]["rs_ratio"].extend(lag_rsr)
            pooled[h]["rs_momentum"].extend(lag_rsm)
            pooled[h]["fwd"].extend(lag_fwd)

            per_etf.append({
                "etf": etf, "horizon": h,
                "n_lagging": len(lag_fwd), "n_inflection": len(inf_fwd),
                "n_improving": len(imp_fwd),
                "lag_mean": lag_mean, "inf_mean": inf_mean, "imp_mean": imp_mean,
                "inf_lift_pp": (inf_mean - lag_mean) * 100 if inf_fwd else float("nan"),
                "p_inflection_vs_null": p_inf,
                "corr_level": corr_level, "corr_momentum": corr_mom,
            })

    pooled_race = {}
    for h in HORIZONS:
        rl, pl, n = spearman_p(pooled[h]["rs_ratio"], pooled[h]["fwd"])
        rm, pm, _ = spearman_p(pooled[h]["rs_momentum"], pooled[h]["fwd"])
        pooled_race[h] = {
            "n": n,
            "corr_level": rl, "p_level": pl,
            "corr_momentum": rm, "p_momentum": pm,
        }
    return {"per_etf": per_etf, "pooled_race": pooled_race,
            "raw_inflections": raw_inflections, "distance": distance}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "  n/a"
    return f"{x:.{nd}f}"


def build_report(panel: pd.DataFrame, spy_res: dict, qqq_res: dict,
                 data_range: str, missing: list[str],
                 robust_res: Optional[dict] = None) -> str:
    lines: list[str] = []
    w = lines.append
    w("# F1 Sector-Rotation Historical Back-test — honest result")
    w("")
    w(f"_Generated {time.strftime('%Y-%m-%d %H:%M %Z')}_")
    w("")
    w("Frozen pre-registered params (preregistration_trade_edge.yaml): "
      f"n_window={N_WINDOW}, k_window={K_WINDOW}, distance={DISTANCE}, "
      f"persistence={PERSISTENCE}, horizons={list(HORIZONS)}, BH-FDR q<{BH_Q}, "
      f"seed={SEED}, null=lagging-quadrant-only, episode_window={EPISODE_WINDOW}td.")
    w("")
    w(f"Data: {data_range}. Missing tickers: {missing or 'none'}.")
    w("")

    # ---- degeneracy flag ----
    w("## CRITICAL: the frozen inflection params are mathematically degenerate")
    w("")
    w(f"Raw inflections fired at the frozen params (distance={DISTANCE}, "
      f"k_window={K_WINDOW}): **{spy_res['raw_inflections']}** across all 13 "
      "ETFs over the whole history (SPY benchmark).")
    w("")
    w("`rs_momentum = 100 + zscore_last(ROC over a k=5 window)`. The maximum "
      "population z-score of the LAST element of a 5-value window is exactly "
      "`sqrt(k-1) = sqrt(4) = 2.0` (attained only in the degenerate all-others-"
      "equal case). The inflection rule requires `rs_momentum - 100 > distance` "
      "= `> 2.0`, which is therefore **unreachable**. So the lagging->improving "
      "INFLECTION event NEVER fires at the frozen contract — the inflection "
      "edge-claim is **vacuous / untestable as pre-registered**, independent of "
      "any market behaviour. This is a flaw in the frozen contract "
      "(distance must be < sqrt(k_window-1)), surfaced honestly, NOT tuned away.")
    w("")
    w("Two things are still testable at the frozen params and reported below: "
      "(a) the continuous **RS-Momentum vs RS-Ratio LEVEL** race inside the "
      "lagging opportunity set (does not depend on the inflection event); and "
      "(b) a clearly-labelled NON-registered robustness pass at distance=1.0 "
      "(where inflections CAN fire) to show the inflection claim is null either "
      "way, not just vacuous.")
    w("")

    # ---- decisive momentum-vs-level race (pooled lagging opportunity set) ----
    w("## Make-or-break A/B — RS-Momentum vs RS-Ratio LEVEL")
    w("")
    w("Both measured INSIDE the lagging-quadrant-only opportunity set (fair "
      "comparison). Spearman rank corr of each predictor vs forward relative "
      "return, with two-sided p. Momentum 'wins' only if its corr is higher AND "
      "positive AND significant.")
    w("")
    w("| benchmark | horizon | n(lagging) | corr LEVEL (p) | corr MOMENTUM (p) | winner |")
    w("|---|---|---|---|---|---|")
    for label, res in (("SPY", spy_res), ("QQQ (transfer)", qqq_res)):
        for h in HORIZONS:
            pr = res["pooled_race"][h]
            cl, cm = pr["corr_level"], pr["corr_momentum"]
            if np.isnan(cl) or np.isnan(cm):
                win = "n/a"
            elif cm > cl and cm > 0 and pr.get("p_momentum", 1) < 0.05:
                win = "momentum"
            elif cl > cm and cl > 0 and pr.get("p_level", 1) < 0.05:
                win = "LEVEL"
            elif abs(cm) < 0.05 and abs(cl) < 0.05:
                win = "neither (both ~0)"
            else:
                win = "tie"
            w(f"| {label} | {h}d | {pr['n']} | {_fmt(cl)} ({_fmt(pr.get('p_level'),3)}) | "
              f"{_fmt(cm)} ({_fmt(pr.get('p_momentum'),3)}) | {win} |")
    w("")

    # ---- inflection vs lagging null, with BH-FDR across the SPY grid ----
    w("## Inflection (lagging->improving) vs lagging-quadrant null")
    w("")
    w("Forward relative return of the confirmed inflection episodes vs a "
      f"permutation null drawn from the lagging pool ({N_DRAWS} draws, seed {SEED}). "
      "BH-FDR applied across the 13-ETF x 2-horizon SPY grid.")
    w("")
    spy_rows = spy_res["per_etf"]
    pvals = [r["p_inflection_vs_null"] for r in spy_rows]
    valid_idx = [i for i, p in enumerate(pvals)
                 if not (p is None or (isinstance(p, float) and np.isnan(p)))]
    valid_p = [pvals[i] for i in valid_idx]
    rejected, adj = benjamini_hochberg(valid_p, BH_Q)
    rej_map = {valid_idx[j]: rejected[j] for j in range(len(valid_idx))}
    adj_map = {valid_idx[j]: adj[j] for j in range(len(valid_idx))}
    w("| ETF | horizon | n(infl) | n(lag) | infl mean | lag mean | lift (pp) | raw p | BH-adj p | BH reject q<0.1 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(spy_rows):
        w(f"| {r['etf']} | {r['horizon']}d | {r['n_inflection']} | {r['n_lagging']} | "
          f"{_fmt(r['inf_mean'])} | {_fmt(r['lag_mean'])} | {_fmt(r['inf_lift_pp'],2)} | "
          f"{_fmt(r.get('p_inflection_vs_null'),4)} | {_fmt(adj_map.get(i),4)} | "
          f"{'YES' if rej_map.get(i) else 'no'} |")
    n_rej = sum(rej_map.values())
    w("")
    w(f"**BH-FDR survivors (q<{BH_Q}): {n_rej} / {len(valid_p)} tested cells.** "
      f"(At frozen distance={DISTANCE} every n(infl)=0, so this grid is empty "
      "— see the degeneracy note above.)")
    w("")

    # ---- non-registered robustness: distance=1.0 so inflections CAN fire ----
    if robust_res is not None:
        rd = robust_res["distance"]
        w(f"## Robustness (NON-registered): inflection vs null at distance={rd}")
        w("")
        w(f"The frozen distance={DISTANCE} is unreachable, so this labelled "
          f"sensitivity pass lowers distance to {rd} (where "
          f"{robust_res['raw_inflections']} raw inflections fire) to check the "
          "lagging->improving claim is genuinely null, not merely vacuous. "
          "Same lagging-quadrant permutation null + BH-FDR across the grid.")
        w("")
        rrows = robust_res["per_etf"]
        rpv = [r["p_inflection_vs_null"] for r in rrows]
        rvi = [i for i, p in enumerate(rpv)
               if not (p is None or (isinstance(p, float) and np.isnan(p)))]
        rvp = [rpv[i] for i in rvi]
        rrej, radj = benjamini_hochberg(rvp, BH_Q)
        rrej_map = {rvi[j]: rrej[j] for j in range(len(rvi))}
        radj_map = {rvi[j]: radj[j] for j in range(len(rvi))}
        w("| ETF | horizon | n(infl) | infl mean | lag mean | lift (pp) | raw p | BH-adj p | reject |")
        w("|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(rrows):
            if r["n_inflection"] == 0:
                continue
            w(f"| {r['etf']} | {r['horizon']}d | {r['n_inflection']} | "
              f"{_fmt(r['inf_mean'])} | {_fmt(r['lag_mean'])} | "
              f"{_fmt(r['inf_lift_pp'],2)} | {_fmt(r.get('p_inflection_vs_null'),4)} | "
              f"{_fmt(radj_map.get(i),4)} | {'YES' if rrej_map.get(i) else 'no'} |")
        w("")
        w(f"**Robustness BH-FDR survivors (q<{BH_Q}): "
          f"{sum(rrej_map.values())} / {len(rvp)} tested cells.**")
        w("")

    # ---- transfer: SMH/XBI sign under SPY benchmark ----
    w("## Frozen-parameter transfer")
    w("")
    w("QQQ-relative recompute is the full table above (benchmark=QQQ). Below: "
      "SMH/XBI sign check under the SPY benchmark (do the two transfer ETFs keep "
      "the same momentum>level sign as the pooled result?).")
    w("")
    w("| ETF | horizon | corr LEVEL | corr MOMENTUM | momentum>level? |")
    w("|---|---|---|---|---|")
    for r in spy_rows:
        if r["etf"] in ("SMH", "XBI"):
            cl, cm = r["corr_level"], r["corr_momentum"]
            sign = ("yes" if (not np.isnan(cl) and not np.isnan(cm) and cm > cl)
                    else ("no" if not np.isnan(cl) and not np.isnan(cm) else "n/a"))
            w(f"| {r['etf']} | {r['horizon']}d | {_fmt(cl)} | {_fmt(cm)} | {sign} |")
    w("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="F1 sector-rotation historical back-test.")
    ap.add_argument("--no-download", action="store_true",
                    help="Use cached parquet store only (no yfinance calls).")
    ap.add_argument("--force-download", action="store_true",
                    help="Re-download even if a series is already cached.")
    ap.add_argument("--start", default=BACKTEST_START,
                    help=f"Download start date (default {BACKTEST_START}).")
    args = ap.parse_args()

    store = _get_store()
    if args.no_download:
        have = [s for s in ALL_SYMBOLS if store.series_exists(s)]
    else:
        have = download_and_store(store, ALL_SYMBOLS, args.start,
                                  force=args.force_download)

    missing = [s for s in ALL_SYMBOLS if s not in have]
    if "SPY" not in have:
        log.error("SPY missing — cannot run the back-test.")
        return 1

    panel = store.load_panel(have)
    panel = panel[panel.index >= pd.Timestamp(args.start)]
    if len(panel) == 0:
        log.error("Empty panel after start filter.")
        return 1
    data_range = (f"{len(have)} symbols, "
                  f"{str(panel.index.min().date())} -> {str(panel.index.max().date())} "
                  f"({len(panel)} trading days)")
    log.info("Panel: %s", data_range)

    etfs = [e for e in SECTOR_ETFS if e in have]
    log.info("Analysing SPY benchmark ...")
    spy_res = _analyse_benchmark(panel, "SPY", etfs)
    qqq_res = {"per_etf": [], "pooled_race": {h: {"n": 0, "corr_level": float("nan"),
                                                  "corr_momentum": float("nan")}
                                             for h in HORIZONS}}
    if "QQQ" in have:
        log.info("Analysing QQQ-relative transfer ...")
        qqq_res = _analyse_benchmark(panel, "QQQ", etfs)

    # Non-registered robustness: distance=1.0 so inflections can actually fire.
    log.info("Robustness pass (non-registered, distance=1.0) ...")
    robust_res = _analyse_benchmark(panel, "SPY", etfs, distance=1.0)

    report = build_report(panel, spy_res, qqq_res, data_range, missing,
                          robust_res=robust_res)
    out_dir = ROOT / ".claude" / "discover" / "trade-edge-features"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "F1-backtest-result.md"
    out_path.write_text(report)
    print("\n" + report + "\n")
    log.info("Report written to %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
