#!/usr/bin/env python3
"""F2 factor/style RS-rotation historical back-test — honest result.

Tests the PRE-REGISTERED F2 claim (preregistration_trade_edge.yaml
f2_factor_rotation; final-plan.md §8):

    a factor's trailing 21-63d RS-momentum predicts its forward 1-21d RELATIVE
    return with a POSITIVE sign AFTER SUBTRACTING SPY's own trailing return
    (the mandatory control), out-of-sample on a frozen-parameter QQQ transfer.

The math reuses the FROZEN live engine
``consensus_engine.analysis.factor_rotation.compute_factor_series`` (no
backtest-vs-live drift) and the F1 back-test helpers
(``scripts.backtest_sector_rotation``: forward_relative_returns,
benjamini_hochberg, spearman, spearman_p) — nothing is re-implemented.

Predictor      : rs_momentum  = 100*(rs[t]/rs[t-63] - 1)   (63d trailing RS vs SPY)
                 rs_vs_spy    = 100*(rs[t]/rs[t-21] - 1)   (21d, reported alongside)
Outcome        : forward 1d / 21d relative return (factor minus benchmark) using the
                 look-ahead-safe next-open entry convention.
Mandatory ctrl : SPY's OWN trailing 63d return, partialled out in a multiple OLS
                 (forward_rel ~ rs_momentum + spy_trailing). The slope on
                 rs_momentum AFTER the control is the registered edge test.
Independence   : the regression uses NON-OVERLAPPING observations (stride = horizon)
                 so overlapping forward windows don't manufacture significance.
Grid / FDR     : 11 factor x {1d,21d} horizon, one-sided (positive) p, BH-FDR q<0.1.
Transfer       : frozen params re-applied with QQQ in the benchmark slot (rs=etf/QQQ,
                 outcome vs QQQ, control = QQQ trailing return).
Precondition   : the factor-momentum AUTOCORRELATION (does relative-strength trend
                 persist?) is reproduced on the local data before trusting any edge.

Data: ~10y RAW daily OHLCV (auto_adjust=False) for the 11 factor ETFs + SPY + QQQ
via yfinance into data/market_store, reusing the sandbox parquet store and the F1
download helper. A clean NO-EDGE is a VALID, honest outcome and is reported plainly.

Usage:
    python3 scripts/backtest_factor_rotation.py             # download (if needed) + run
    python3 scripts/backtest_factor_rotation.py --no-download
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "volatility_regime_reversal_indicator"))

from consensus_engine.analysis import factor_rotation as fr_mod  # noqa: E402
from scripts.backtest_sector_rotation import (  # noqa: E402  (REUSE F1 helpers)
    benjamini_hochberg,
    download_and_store,
    forward_relative_returns,
    spearman,
    spearman_p,
    _get_store,
)

log = logging.getLogger("backtest_factor_rotation")

# Frozen pre-registered params (preregistration_trade_edge.yaml f2_factor_rotation)
RS_WINDOW = 21          # short RS lookback (rs_vs_spy)
MOM_WINDOW = 63         # long RS lookback (rs_momentum) — the registered predictor
HORIZONS = (1, 21)      # forward 1d / 21d relative return
BH_Q = 0.10
BACKTEST_START = "2012-01-01"

STORE_DIR = str(ROOT / "data" / "market_store")
FACTOR_ETFS = fr_mod.FACTOR_ETFS                 # 11
BENCHMARK = fr_mod.BENCHMARK                      # "SPY"
ALL_SYMBOLS = ("SPY", "QQQ", *FACTOR_ETFS)


# ---------------------------------------------------------------------------
# NEW pure, testable helpers (exercised by tests/test_backtest_factor_rotation.py)
# ---------------------------------------------------------------------------

def spy_trailing_return(closes: Sequence[float], window: int) -> pd.Series:
    """Benchmark's OWN trailing `window`-day return, point-in-time (no look-ahead).

    tr[t] = close[t]/close[t-window] - 1 for t >= window, else NaN. This is the
    mandatory SPY-trailing control column: it uses only PAST closes, so day-t
    never references day t+1.
    """
    s = pd.Series(list(closes), dtype=float).reset_index(drop=True)
    return s / s.shift(window) - 1.0


def controlled_regression(
    predictor: Sequence[float],
    control: Sequence[float],
    outcome: Sequence[float],
    alternative: str = "greater",
) -> tuple[float, float, int]:
    """OLS slope of `outcome` on `predictor` AFTER partialling out `control`.

    Fits  outcome = b0 + b1*predictor + b2*control  and returns
    (b1, one-sided p-value for b1, n_valid). The control (SPY's own trailing
    return) is included as a covariate, so b1 is the predictor's contribution
    NET of any market-wide trailing-return effect — the registered F2 test.

    alternative='greater' tests H1: b1 > 0 (the claimed positive sign). NaN-safe:
    rows with any NaN are dropped; returns (nan, nan, n) when n < 4 (no residual df).
    """
    a = np.asarray(predictor, dtype=float)
    c = np.asarray(control, dtype=float)
    y = np.asarray(outcome, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(c) | np.isnan(y))
    a, c, y = a[mask], c[mask], y[mask]
    n = int(len(y))
    if n < 4:
        return float("nan"), float("nan"), n
    X = np.column_stack([np.ones(n), a, c])
    # guard against a degenerate (collinear / zero-variance) design
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return float("nan"), float("nan"), n
    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    df = n - X.shape[1]
    if df <= 0:
        return float("nan"), float("nan"), n
    sigma2 = float(resid @ resid) / df
    xtx_inv = np.linalg.inv(X.T @ X)
    se_b1 = float(np.sqrt(sigma2 * xtx_inv[1, 1]))
    b1 = float(beta[1])
    if se_b1 == 0:
        return b1, float("nan"), n
    t = b1 / se_b1
    from scipy import stats
    if alternative == "greater":
        p = float(stats.t.sf(t, df))
    elif alternative == "less":
        p = float(stats.t.cdf(t, df))
    else:
        p = float(2.0 * stats.t.sf(abs(t), df))
    return b1, p, n


def factor_rs_autocorr(rs: Sequence[float], window: int) -> float:
    """Factor-momentum persistence: Spearman(trailing RS return, forward RS return).

    For each date t with both defined, trailing = rs[t]/rs[t-window]-1 and forward
    = rs[t+window]/rs[t]-1; returns their rank correlation. Positive => a factor
    that has been gaining relative strength keeps gaining (the precondition for any
    RS-momentum edge). NaN-safe (NaN if fewer than 3 overlapping pairs).
    """
    s = np.asarray(rs, dtype=float)
    m = len(s)
    trailing: list[float] = []
    forward: list[float] = []
    for t in range(window, m - window):
        base, fwd = s[t - window], s[t + window]
        if not base or np.isnan(base) or np.isnan(s[t]) or np.isnan(fwd) or not s[t]:
            continue
        trailing.append(s[t] / base - 1.0)
        forward.append(fwd / s[t] - 1.0)
    return spearman(trailing, forward)


# ---------------------------------------------------------------------------
# Per-factor analysis (reuse the FROZEN factor engine; benchmark-swap for transfer)
# ---------------------------------------------------------------------------

def _stride(arr: np.ndarray, step: int) -> np.ndarray:
    """Non-overlapping subsample (every `step`-th element) to respect independence."""
    return arr[::max(1, step)]


def _analyse_factor(panel: pd.DataFrame, factor: str, benchmark: str) -> Optional[dict]:
    """Per-factor RS-momentum -> forward-relative-return analysis for one benchmark.

    Returns per-horizon raw + controlled stats plus the factor-momentum
    autocorrelation, or None if the factor/benchmark closes are unavailable.
    """
    if f"{factor}_close" not in panel.columns or f"{benchmark}_close" not in panel.columns:
        return None
    # per-factor closes_df preserves each factor's own start date (no cross-truncation)
    fdf = pd.DataFrame({
        BENCHMARK: panel[f"{benchmark}_close"],   # frozen module reads the 'SPY' slot
        factor: panel[f"{factor}_close"],
    }).dropna(how="any")
    if len(fdf) <= MOM_WINDOW + max(HORIZONS) + 5:
        return None

    series = fr_mod.compute_factor_series(fdf, RS_WINDOW, MOM_WINDOW)
    cells = series.get(factor)
    if cells is None:
        return None
    rs_mom = np.array([c["rs_momentum"] if c else np.nan for c in cells])
    rs_vs = np.array([c["rs_vs_spy"] if c else np.nan for c in cells])

    sub = panel.reindex(fdf.index)
    fwd = forward_relative_returns(sub, factor, benchmark, HORIZONS)
    control = spy_trailing_return(fdf[BENCHMARK].to_numpy(), MOM_WINDOW).to_numpy()

    # factor-momentum autocorrelation precondition (relative-strength line)
    rs_line = (100.0 * fdf[factor] / fdf[BENCHMARK]).to_numpy()
    ac21 = factor_rs_autocorr(rs_line, RS_WINDOW)
    ac63 = factor_rs_autocorr(rs_line, MOM_WINDOW)

    per_h: list[dict] = []
    for h in HORIZONS:
        out = fwd[h].to_numpy()
        # raw (uncontrolled) Spearman of the registered predictor vs forward rel ret
        corr_raw, p_raw, n_raw = spearman_p(list(rs_mom), list(out))
        # mandatory control on NON-OVERLAPPING obs (stride = horizon)
        b1, p_ctrl, n_ctrl = controlled_regression(
            _stride(rs_mom, h), _stride(control, h), _stride(out, h),
            alternative="greater",
        )
        # 21d-predictor (rs_vs_spy) controlled, for the 21-63d span
        b1_short, p_short, _ = controlled_regression(
            _stride(rs_vs, h), _stride(control, h), _stride(out, h),
            alternative="greater",
        )
        per_h.append({
            "factor": factor, "horizon": h,
            "corr_raw": corr_raw, "p_raw": p_raw, "n_raw": n_raw,
            "beta_ctrl": b1, "p_ctrl": p_ctrl, "n_ctrl": n_ctrl,
            "beta_ctrl_short": b1_short, "p_ctrl_short": p_short,
        })
    return {"factor": factor, "per_h": per_h, "ac21": ac21, "ac63": ac63,
            "rs_mom": rs_mom, "rs_vs": rs_vs, "control": control, "fwd": fwd,
            "n_dates": len(fdf)}


def _analyse_benchmark(panel: pd.DataFrame, benchmark: str,
                       factors: list[str]) -> dict:
    """Run every factor + a POOLED controlled regression for one benchmark."""
    rows: list[dict] = []
    autocorr: list[dict] = []
    pooled = {h: {"pred": [], "ctrl": [], "out": []} for h in HORIZONS}

    for f in factors:
        res = _analyse_factor(panel, f, benchmark)
        if res is None:
            log.warning("[F2] %s vs %s: insufficient data, skipped", f, benchmark)
            continue
        rows.extend(res["per_h"])
        autocorr.append({"factor": f, "ac21": res["ac21"], "ac63": res["ac63"]})
        for h in HORIZONS:
            out = res["fwd"][h].to_numpy()
            pooled[h]["pred"].extend(_stride(res["rs_mom"], h).tolist())
            pooled[h]["ctrl"].extend(_stride(res["control"], h).tolist())
            pooled[h]["out"].extend(_stride(out, h).tolist())

    pooled_res = {}
    for h in HORIZONS:
        b1, p, n = controlled_regression(
            pooled[h]["pred"], pooled[h]["ctrl"], pooled[h]["out"],
            alternative="greater",
        )
        # raw pooled Spearman (no control) for contrast
        cr, pr, nr = spearman_p(pooled[h]["pred"], pooled[h]["out"])
        pooled_res[h] = {"beta_ctrl": b1, "p_ctrl": p, "n": n,
                         "corr_raw": cr, "p_raw": pr, "n_raw": nr}

    return {"rows": rows, "autocorr": autocorr, "pooled": pooled_res}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "  n/a"
    return f"{x:.{nd}f}"


def _verdict(spy_res: dict, qqq_res: dict, n_survivors: int) -> tuple[str, str]:
    """Honest edge / inconclusive / no-edge call + one-line reason."""
    spy_pooled = spy_res["pooled"]
    qqq_pooled = qqq_res["pooled"]
    # positive controlled slope on SPY at any horizon?
    spy_pos = any(not np.isnan(spy_pooled[h]["beta_ctrl"]) and spy_pooled[h]["beta_ctrl"] > 0
                  for h in HORIZONS)
    spy_sig = any(not np.isnan(spy_pooled[h]["p_ctrl"]) and spy_pooled[h]["p_ctrl"] < 0.05
                  and spy_pooled[h]["beta_ctrl"] > 0 for h in HORIZONS)
    qqq_pos = any(not np.isnan(qqq_pooled[h]["beta_ctrl"]) and qqq_pooled[h]["beta_ctrl"] > 0
                  for h in HORIZONS)
    if spy_sig and n_survivors > 0 and qqq_pos:
        return "edge", ("controlled SPY slope positive+significant, BH survivors>0, "
                        "and the QQQ transfer keeps the positive sign")
    if not spy_pos:
        return "no-edge", ("the controlled (SPY-trailing-removed) slope is <=0 at both "
                           "horizons — no positive RS-momentum edge after the control")
    return "inconclusive", ("controlled slope is positive but not significant / no BH "
                            "survivor / sign does not transfer cleanly to QQQ")


def build_report(spy_res: dict, qqq_res: dict, data_range: str,
                 missing: list[str], bh: dict) -> tuple[str, str, str]:
    lines: list[str] = []
    w = lines.append
    w("# F2 Factor/Style RS-Rotation Historical Back-test — honest result")
    w("")
    w(f"_Generated {time.strftime('%Y-%m-%d %H:%M %Z')}_")
    w("")
    w("Frozen pre-registered params (preregistration_trade_edge.yaml "
      f"f2_factor_rotation): rs_window={RS_WINDOW}, mom_window={MOM_WINDOW}, "
      f"horizons={list(HORIZONS)}d, control=subtract_spy_trailing_return, "
      f"BH-FDR q<{BH_Q}, OOS transfer=QQQ. Predictor = rs_momentum (63d trailing "
      "RS vs the benchmark); outcome = forward relative return (factor minus "
      "benchmark, next-open entry).")
    w("")
    w(f"Data: {data_range}. Missing tickers: {missing or 'none'}.")
    w("")
    w("The control is applied as a multiple OLS — `forward_rel ~ rs_momentum + "
      "spy_trailing` — on NON-OVERLAPPING observations (stride = horizon), so the "
      "reported slope is the factor's RS-momentum contribution NET of SPY's own "
      "trailing return, and overlapping forward windows can't inflate significance.")
    w("")

    # ---- precondition: factor-momentum autocorrelation ----
    w("## Precondition — factor-momentum autocorrelation (must hold first)")
    w("")
    w("Spearman of each factor's trailing RS return vs its forward RS return "
      "(relative-strength line = 100*factor/benchmark). If RS-momentum does not "
      "persist, no predictive edge can exist. Benchmark = SPY.")
    w("")
    w("| factor | autocorr (21d) | autocorr (63d) |")
    w("|---|---|---|")
    ac21s, ac63s = [], []
    for a in spy_res["autocorr"]:
        w(f"| {a['factor']} | {_fmt(a['ac21'],3)} | {_fmt(a['ac63'],3)} |")
        if not np.isnan(a["ac21"]):
            ac21s.append(a["ac21"])
        if not np.isnan(a["ac63"]):
            ac63s.append(a["ac63"])
    med21 = float(np.median(ac21s)) if ac21s else float("nan")
    med63 = float(np.median(ac63s)) if ac63s else float("nan")
    w("")
    w(f"**Median factor-momentum autocorrelation: 21d={_fmt(med21,3)}, "
      f"63d={_fmt(med63,3)}.** "
      + ("Positive => RS trends persist, so an edge is at least possible."
         if (not np.isnan(med63) and med63 > 0.05)
         else "Near-zero / negative => RS-momentum does NOT persist; an edge is "
              "unlikely a priori."))
    w("")

    # ---- pooled controlled result (the headline) ----
    w("## Headline — pooled controlled regression (SPY benchmark)")
    w("")
    w("All factors stacked. `beta_ctrl` = slope on rs_momentum AFTER the SPY-"
      "trailing control; `corr_raw` = uncontrolled Spearman for contrast. "
      "One-sided p tests the claimed POSITIVE sign.")
    w("")
    w("| horizon | n (non-overlap) | corr_raw (p) | beta_ctrl (p, one-sided>0) |")
    w("|---|---|---|---|")
    for h in HORIZONS:
        pr = spy_res["pooled"][h]
        w(f"| {h}d | {pr['n']} | {_fmt(pr['corr_raw'])} ({_fmt(pr['p_raw'],3)}) | "
          f"{_fmt(pr['beta_ctrl'],6)} ({_fmt(pr['p_ctrl'],3)}) |")
    w("")

    # ---- per-factor x horizon grid with BH-FDR (controlled p) ----
    w("## Per-factor x horizon grid — controlled slope, BH-FDR q<0.1 (SPY)")
    w("")
    w("`beta_ctrl` = rs_momentum slope after the SPY-trailing control (one-sided "
      "p for >0). BH-FDR across the full 11x2 grid.")
    w("")
    w("| factor | horizon | n | corr_raw | beta_ctrl | raw p | BH-adj p | BH reject q<0.1 |")
    w("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(spy_res["rows"]):
        w(f"| {r['factor']} | {r['horizon']}d | {r['n_ctrl']} | "
          f"{_fmt(r['corr_raw'],3)} | {_fmt(r['beta_ctrl'],6)} | "
          f"{_fmt(r['p_ctrl'],4)} | {_fmt(bh['adj'].get(i),4)} | "
          f"{'YES' if bh['rej'].get(i) else 'no'} |")
    w("")
    w(f"**BH-FDR survivors (q<{BH_Q}): {bh['n_rej']} / {bh['n_tested']} tested "
      "cells (positive controlled slope).**")
    w("")

    # ---- QQQ transfer ----
    w("## Frozen-parameter QQQ transfer (out-of-sample)")
    w("")
    w("Identical frozen params, QQQ in the benchmark slot (rs=factor/QQQ, outcome "
      "vs QQQ, control = QQQ's own trailing return). The claim survives only if "
      "the positive controlled sign holds out-of-sample.")
    w("")
    w("| horizon | n | corr_raw (p) | beta_ctrl (p, one-sided>0) | positive sign? |")
    w("|---|---|---|---|---|")
    for h in HORIZONS:
        pr = qqq_res["pooled"][h]
        pos = ("yes" if (not np.isnan(pr["beta_ctrl"]) and pr["beta_ctrl"] > 0)
               else ("no" if not np.isnan(pr["beta_ctrl"]) else "n/a"))
        w(f"| {h}d | {pr['n']} | {_fmt(pr['corr_raw'])} ({_fmt(pr['p_raw'],3)}) | "
          f"{_fmt(pr['beta_ctrl'],6)} ({_fmt(pr['p_ctrl'],3)}) | {pos} |")
    w("")

    verdict, reason = _verdict(spy_res, qqq_res, bh["n_rej"])
    w("## Verdict")
    w("")
    w(f"**{verdict.upper()}** — {reason}.")
    w("")
    w("Kill-gate rule (preregistration f2): positive sign AFTER the SPY-trailing "
      "control + OOS QQQ, else keep the `factor_rs_daily` table for display and "
      "DROP the lead claim. SPHB/SPLV demote to descriptive on control failure.")
    w("")

    # ---- machine-readable key numbers (for the structured return) ----
    kn = []
    for h in HORIZONS:
        p = spy_res["pooled"][h]
        q = qqq_res["pooled"][h]
        kn.append(f"SPY {h}d beta_ctrl={_fmt(p['beta_ctrl'],6)} (p={_fmt(p['p_ctrl'],3)}); "
                  f"QQQ {h}d beta_ctrl={_fmt(q['beta_ctrl'],6)} (p={_fmt(q['p_ctrl'],3)})")
    key_numbers = (f"median factor-mom autocorr 63d={_fmt(med63,3)}; "
                   + "; ".join(kn)
                   + f"; BH survivors={bh['n_rej']}/{bh['n_tested']}")
    return "\n".join(lines), verdict, key_numbers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="F2 factor-rotation historical back-test.")
    ap.add_argument("--no-download", action="store_true",
                    help="Use cached parquet store only (no yfinance calls).")
    ap.add_argument("--force-download", action="store_true")
    ap.add_argument("--start", default=BACKTEST_START)
    args = ap.parse_args()

    store = _get_store()
    if args.no_download:
        have = [s for s in ALL_SYMBOLS if store.series_exists(s)]
    else:
        have = download_and_store(store, ALL_SYMBOLS, args.start,
                                  force=args.force_download)

    missing = [s for s in ALL_SYMBOLS if s not in have]
    if "SPY" not in have:
        log.error("SPY missing — cannot run.")
        return 1

    panel = store.load_panel(have)
    panel = panel[panel.index >= pd.Timestamp(args.start)]
    if len(panel) == 0:
        log.error("Empty panel after start filter.")
        return 1
    data_range = (f"{len(have)} symbols, {str(panel.index.min().date())} -> "
                  f"{str(panel.index.max().date())} ({len(panel)} trading days)")
    log.info("Panel: %s", data_range)

    factors = [f for f in FACTOR_ETFS if f in have]
    log.info("Analysing SPY benchmark (%d factors) ...", len(factors))
    spy_res = _analyse_benchmark(panel, "SPY", factors)

    qqq_res = {"rows": [], "autocorr": [],
               "pooled": {h: {"beta_ctrl": float("nan"), "p_ctrl": float("nan"),
                              "n": 0, "corr_raw": float("nan"),
                              "p_raw": float("nan"), "n_raw": 0} for h in HORIZONS}}
    if "QQQ" in have:
        log.info("Analysing QQQ-relative transfer ...")
        qqq_res = _analyse_benchmark(panel, "QQQ", factors)

    # BH-FDR across the SPY controlled-slope grid (one-sided positive p)
    pvals = [r["p_ctrl"] for r in spy_res["rows"]]
    valid_idx = [i for i, p in enumerate(pvals)
                 if not (p is None or (isinstance(p, float) and np.isnan(p)))]
    valid_p = [pvals[i] for i in valid_idx]
    rejected, adj = benjamini_hochberg(valid_p, BH_Q)
    rej_map = {valid_idx[j]: rejected[j] for j in range(len(valid_idx))}
    # BH "reject" only counts a survivor if the slope is actually positive
    for j, i in enumerate(valid_idx):
        if rejected[j] and not (spy_res["rows"][i]["beta_ctrl"] > 0):
            rej_map[i] = False
    adj_map = {valid_idx[j]: adj[j] for j in range(len(valid_idx))}
    bh = {"rej": rej_map, "adj": adj_map,
          "n_rej": sum(rej_map.values()), "n_tested": len(valid_p)}

    report, verdict, key_numbers = build_report(spy_res, qqq_res, data_range,
                                                missing, bh)
    out_dir = ROOT / ".claude" / "discover" / "trade-edge-features"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "F2-backtest-result.md"
    out_path.write_text(report)
    print("\n" + report + "\n")
    log.info("VERDICT=%s | %s", verdict, key_numbers)
    log.info("Report written to %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
