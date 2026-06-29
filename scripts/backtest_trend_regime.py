#!/usr/bin/env python3
"""F3 trend-regime historical back-test — market-level, the well-powered test.

Tests the PRE-REGISTERED F3 claim (preregistration_trade_edge.yaml f3_trend_regime
+ final-plan.md §8) at the MARKET level, where there is real statistical power:

  Does the index's forward return (next 1d and 5d, long) differ by trend state?
  Registered framing: above-200DMA vs below-200DMA forward win-rate
  (P(forward return > 0)) and mean forward return, the GAP between them, and
  whether the win-rate GAP clears the pre-registered >= 4pp bar. The
  unconditional baseline (all days) is reported as the control reference.

  Control (registered: own_lagged_5d_move): at the market level the "ticker's
  own lagged 5-day move" is the index's own trailing 5-day return. We re-run the
  above-vs-below gap WITHIN lagged-5d-up and lagged-5d-down strata — if the
  regime gap is merely a proxy for short-term momentum it collapses; if it
  survives in both strata it carries information beyond the lagged move.

  Out-of-sample / transfer: confirm the sign holds on QQQ and on a held-out
  late sub-period of SPY.

HONESTY: the above-/below-200DMA forward-return spread is a WELL-KNOWN regime
effect. The job here is to report whether it is real AND large enough (>= 4pp)
AND robust to the lagged-move control and transfer — not to discover a novel
edge. The PER-TICKER >= 4pp alert-win-rate lift CANNOT be proven on the current
48-alert sample; that part stays SHADOW and is stated as such.

The trend computation REUSES the FROZEN consensus_engine.analysis.regime engine:
trend_state_series replicates _compute_trend's component formulas exactly and
classifies via the frozen _classify_trend_state. A unit test
(tests/test_backtest_trend_regime.py) pins it to _compute_trend so there is no
back-test-vs-live drift.

Data: ~14y daily SPY + QQQ (auto_adjust=False, RAW close) via yfinance into
data/market_store, reusing the sandbox parquet store. The F1 back-test already
seeds SPY/QQQ there; --no-download uses the cache.

Usage:
    python3 scripts/backtest_trend_regime.py              # download (if needed) + run
    python3 scripts/backtest_trend_regime.py --no-download

A clean NO-EDGE / INCONCLUSIVE outcome is a VALID result and is reported plainly.
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

from consensus_engine.analysis.regime import _classify_trend_state  # noqa: E402
# reuse the frozen F1 helpers (do not re-implement)
from scripts.backtest_sector_rotation import benjamini_hochberg  # noqa: E402

log = logging.getLogger("backtest_trend_regime")

# Frozen pre-registered params (preregistration_trade_edge.yaml f3_trend_regime)
SMA_SLOW = 200
SMA_FAST = 50
TSMOM_LB = 63          # 3-month time-series momentum
SLOPE_WINDOW = 10      # 50DMA slope window (matches features.trend_regime.slope_window)
HORIZONS = (1, 5)      # forward next-1d / next-5d long
MIN_LIFT_PP = 4.0      # pre-registered win-rate gap bar
LAGGED_MOVE_DAYS = 5   # registered control: own lagged 5-day move
BH_Q = 0.10
SEED = 1729
N_DRAWS = 2000
BACKTEST_START = "2012-01-01"

STORE_DIR = str(ROOT / "data" / "market_store")
INDEX_SYMBOLS = ("SPY", "QQQ")


# ---------------------------------------------------------------------------
# Pure, testable helpers (the test file exercises these without any download)
# ---------------------------------------------------------------------------

def trend_state_series(
    closes: pd.Series,
    sma_slow: int = SMA_SLOW,
    sma_fast: int = SMA_FAST,
    tsmom_lb: int = TSMOM_LB,
    slope_window: int = SLOPE_WINDOW,
) -> pd.DataFrame:
    """Point-in-time trend components, REUSING the frozen classifier.

    Each row i uses only closes up to and including day i (the close-of-day read
    the live cron also uses). Component formulas are byte-identical to
    consensus_engine.analysis.regime._compute_trend; the test file pins them.

      * sma_200 = mean of the last `sma_slow` closes
      * sma_50  = mean of the last `sma_fast` closes
      * sma_50_slope = (sma_50 - sma_50 `slope_window` days ago) / that prior sma_50
      * tsmom_3m = close / close `tsmom_lb` days ago - 1
      * above_200/slope_up/tsmom_up -> _classify_trend_state -> green/yellow/red
    """
    c = closes.astype(float)
    sma_200 = c.rolling(sma_slow).mean()
    sma_50 = c.rolling(sma_fast).mean()
    sma_50_prev = sma_50.shift(slope_window)
    sma_50_slope = (sma_50 - sma_50_prev) / sma_50_prev
    tsmom_3m = c / c.shift(tsmom_lb) - 1.0

    above_200 = c > sma_200
    slope_up = sma_50_slope > 0
    tsmom_up = tsmom_3m > 0

    states = []
    for a, s, t, valid in zip(above_200, slope_up, tsmom_up, ~sma_200.isna()):
        states.append(_classify_trend_state(bool(a), bool(s), bool(t)) if valid else None)

    return pd.DataFrame(
        {
            "close": c,
            "sma_200": sma_200,
            "sma_50": sma_50,
            "sma_50_slope": sma_50_slope,
            "tsmom_3m": tsmom_3m,
            "above_200": above_200 & ~sma_200.isna(),
            "slope_up": slope_up,
            "tsmom_up": tsmom_up,
            "trend_state": states,
        },
        index=closes.index,
    )


def forward_long_returns(closes: pd.Series, horizons: Iterable[int]) -> pd.DataFrame:
    """Forward LONG return of the index itself: close[i+h]/close[i] - 1.

    Close-to-close (the index's own forward return conditioned on its own
    regime). Tail rows with no future close are NaN.
    """
    c = closes.astype(float)
    out = {h: c.shift(-h) / c - 1.0 for h in horizons}
    return pd.DataFrame(out, index=closes.index)


def win_rate(returns: np.ndarray) -> float:
    """Fraction of strictly-positive forward returns (NaN-safe). NaN if no data."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return float("nan")
    return float(np.mean(r > 0))


def regime_gap(fwd: np.ndarray, above: np.ndarray, below: np.ndarray) -> dict:
    """Above-200DMA minus below-200DMA forward stats, plus the baseline control.

    Returns win-rates, mean returns, the GAPs (above - below), and the
    unconditional baseline (all valid rows) as the control reference.
    """
    fwd = np.asarray(fwd, dtype=float)
    above = np.asarray(above, dtype=bool)
    below = np.asarray(below, dtype=bool)
    valid = ~np.isnan(fwd)

    a = fwd[above & valid]
    b = fwd[below & valid]
    base = fwd[valid]

    a_wr = float(np.mean(a > 0)) if len(a) else float("nan")
    b_wr = float(np.mean(b > 0)) if len(b) else float("nan")
    base_wr = float(np.mean(base > 0)) if len(base) else float("nan")
    a_mean = float(np.mean(a)) if len(a) else float("nan")
    b_mean = float(np.mean(b)) if len(b) else float("nan")
    base_mean = float(np.mean(base)) if len(base) else float("nan")

    return {
        "above_n": int(len(a)),
        "below_n": int(len(b)),
        "above_wr": a_wr,
        "below_wr": b_wr,
        "wr_gap_pp": (a_wr - b_wr) * 100 if len(a) and len(b) else float("nan"),
        "above_mean": a_mean,
        "below_mean": b_mean,
        "mean_gap_pp": (a_mean - b_mean) * 100 if len(a) and len(b) else float("nan"),
        "baseline_wr": base_wr,
        "baseline_mean": base_mean,
        "baseline_n": int(len(base)),
    }


def permutation_gap_pvalue(
    fwd: np.ndarray,
    above: np.ndarray,
    below: np.ndarray,
    n_draws: int = N_DRAWS,
    seed: int = SEED,
) -> float:
    """Two-sided permutation p for the win-rate GAP via label shuffling.

    Null = random episode timing: the regime labels are randomly reassigned to
    the same set of days, preserving the above/below group sizes. p = fraction of
    shuffled |win-rate gaps| at least as large as the observed |gap| (+1 smooth).

    Caveat: overlapping multi-day windows (h>1) leave residual autocorrelation
    that this label-shuffle does not fully neutralise; treat h=5 p-values as
    optimistic and lean on the h=1 (non-overlapping) result.
    """
    fwd = np.asarray(fwd, dtype=float)
    above = np.asarray(above, dtype=bool)
    below = np.asarray(below, dtype=bool)
    mask = (above | below) & ~np.isnan(fwd)
    f = fwd[mask]
    n_above = int(np.sum(above[mask]))
    n = len(f)
    if n_above == 0 or n_above == n:
        return float("nan")

    wins = (f > 0).astype(float)
    obs_above = wins[above[mask]].mean()
    obs_below = wins[~above[mask]].mean()
    obs_gap = abs(obs_above - obs_below)

    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_draws):
        perm = rng.permutation(n)
        idx_above = perm[:n_above]
        idx_below = perm[n_above:]
        gap = abs(wins[idx_above].mean() - wins[idx_below].mean())
        if gap >= obs_gap:
            hits += 1
    return (hits + 1) / (n_draws + 1)


# ---------------------------------------------------------------------------
# Data store (reuse sandbox parquet store, redirected to data/market_store)
# ---------------------------------------------------------------------------

def _get_store():
    from src.data import store as _store  # type: ignore
    _orig_get = _store.get

    def _patched_get(key, default=None):
        if key == "data.store_dir":
            return STORE_DIR
        return _orig_get(key, default)

    _store.get = _patched_get
    return _store


def download_and_store(store, symbols: Iterable[str], start: str,
                       force: bool = False) -> list[str]:
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
        log.info("[store] wrote %s: %d rows", sym, len(df))
    return have


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse_symbol(closes: pd.Series, label: str) -> dict:
    """Full above/below-200DMA forward analysis for one index series."""
    ts = trend_state_series(closes)
    fwd = forward_long_returns(closes, HORIZONS)
    above = ts["above_200"].to_numpy()
    below = (~ts["above_200"].to_numpy()) & (~ts["sma_200"].isna().to_numpy())

    # lagged 5-day move control (own trailing 5d return, known at signal time)
    lag_move = (closes / closes.shift(LAGGED_MOVE_DAYS) - 1.0).to_numpy()
    lag_up = lag_move > 0
    lag_dn = lag_move < 0

    per_h: dict[int, dict] = {}
    for h in HORIZONS:
        f = fwd[h].to_numpy()
        g = regime_gap(f, above, below)
        g["p_perm"] = permutation_gap_pvalue(f, above, below)
        # control: gap within lagged-up and lagged-down strata
        g["gap_lag_up"] = regime_gap(f, above & lag_up, below & lag_up)
        g["gap_lag_dn"] = regime_gap(f, above & lag_dn, below & lag_dn)
        # trend_state (3-way) win-rates for context
        g["state_wr"] = {}
        for st_name in ("green", "yellow", "red"):
            m = (ts["trend_state"] == st_name).to_numpy()
            g["state_wr"][st_name] = {
                "n": int(np.sum(m & ~np.isnan(f))),
                "wr": win_rate(f[m]),
                "mean": float(np.nanmean(f[m])) if np.any(m & ~np.isnan(f)) else float("nan"),
            }
        per_h[h] = g
    return {"label": label, "per_h": per_h, "n_days": int(len(closes))}


def analyse_held_out(closes: pd.Series, label: str) -> dict:
    """Split into early/late halves; report the late (held-out) half gap."""
    n = len(closes)
    mid = n // 2
    early = closes.iloc[:mid]
    late = closes.iloc[mid:]
    return {
        "early": analyse_symbol(early, f"{label} EARLY"),
        "late": analyse_symbol(late, f"{label} LATE (held-out)"),
        "split_date": str(closes.index[mid].date()),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _verdict(spy: dict, qqq: Optional[dict], held: dict) -> tuple[str, list[str]]:
    """edge / inconclusive / no-edge for the MARKET-LEVEL regime effect.

    edge: h=1 SPY win-rate gap >= 4pp AND positive AND p<0.05, the gap survives
          BOTH lagged-move strata (still positive), AND the sign holds on QQQ and
          the held-out late sub-period.
    no-edge: h=1 SPY gap < 1pp or negative.
    else: inconclusive (real but under the 4pp bar, or fails a transfer/control).
    """
    notes: list[str] = []
    g1 = spy["per_h"][1]
    gap = g1["wr_gap_pp"]
    p = g1["p_perm"]
    sig = (not np.isnan(p)) and p < 0.05
    clears = (not np.isnan(gap)) and gap >= MIN_LIFT_PP

    up_gap = g1["gap_lag_up"]["wr_gap_pp"]
    dn_gap = g1["gap_lag_dn"]["wr_gap_pp"]
    control_ok = (not np.isnan(up_gap) and up_gap > 0) and (not np.isnan(dn_gap) and dn_gap > 0)

    qqq_ok = False
    if qqq is not None:
        qgap = qqq["per_h"][1]["wr_gap_pp"]
        qqq_ok = (not np.isnan(qgap)) and qgap > 0
    held_gap = held["late"]["per_h"][1]["wr_gap_pp"]
    held_ok = (not np.isnan(held_gap)) and held_gap > 0

    notes.append(f"SPY h=1 win-rate gap = {_fmt(gap)}pp (bar {MIN_LIFT_PP}pp), perm p={_fmt(p,4)}")
    notes.append(f"control (lagged-5d strata): up-stratum gap={_fmt(up_gap)}pp, "
                 f"down-stratum gap={_fmt(dn_gap)}pp")
    notes.append(f"transfer: QQQ h=1 gap={_fmt(qqq['per_h'][1]['wr_gap_pp']) if qqq else 'n/a'}pp, "
                 f"held-out late SPY gap={_fmt(held_gap)}pp")

    if np.isnan(gap) or gap < 1.0:
        return "no-edge", notes
    if clears and sig and control_ok and qqq_ok and held_ok:
        return "edge", notes
    return "inconclusive", notes


def build_report(spy: dict, qqq: Optional[dict], held: dict,
                 data_range: str, verdict: str, vnotes: list[str]) -> str:
    L: list[str] = []
    w = L.append
    w("# F3 Trend-Regime Historical Back-test — honest, market-level result")
    w("")
    w(f"_Generated {time.strftime('%Y-%m-%d %H:%M %Z')}_")
    w("")
    w("Frozen pre-registered params (preregistration_trade_edge.yaml f3_trend_regime): "
      f"sma_slow={SMA_SLOW}, sma_fast={SMA_FAST}, tsmom_lookback_days={TSMOM_LB}, "
      f"slope_window={SLOPE_WINDOW}. Registered metric = above-200DMA minus "
      f"below-200DMA forward win-rate; bar = >= {MIN_LIFT_PP}pp; control = own "
      f"lagged {LAGGED_MOVE_DAYS}-day move; null = label-shuffle permutation "
      f"({N_DRAWS} draws, seed {SEED}); BH-FDR q<{BH_Q}.")
    w("")
    w(f"Data: {data_range}. Forward horizons: next 1d and 5d, LONG, close-to-close.")
    w("")
    w(f"## VERDICT (market-level regime effect): **{verdict.upper()}**")
    w("")
    for n in vnotes:
        w(f"- {n}")
    w("")

    # ---- main table: above vs below by horizon, SPY + QQQ ----
    w("## Above-200DMA vs below-200DMA forward return")
    w("")
    w("`gap` = above minus below. Baseline = unconditional (all days) win-rate / "
      "mean, the control reference. `perm p` = two-sided label-shuffle p on the "
      "win-rate gap.")
    w("")
    w("| index | h | n above | n below | above WR | below WR | **WR gap (pp)** | baseline WR | above mean | below mean | mean gap (pp) | perm p |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    results = [("SPY", spy)]
    if qqq is not None:
        results.append(("QQQ (transfer)", qqq))
    gap_pvals: list[float] = []
    gap_cells: list[tuple] = []
    for name, res in results:
        for h in HORIZONS:
            g = res["per_h"][h]
            w(f"| {name} | {h}d | {g['above_n']} | {g['below_n']} | "
              f"{_fmt(g['above_wr']*100 if not np.isnan(g['above_wr']) else float('nan'))}% | "
              f"{_fmt(g['below_wr']*100 if not np.isnan(g['below_wr']) else float('nan'))}% | "
              f"**{_fmt(g['wr_gap_pp'])}** | "
              f"{_fmt(g['baseline_wr']*100 if not np.isnan(g['baseline_wr']) else float('nan'))}% | "
              f"{_fmt(g['above_mean']*100,3)}% | {_fmt(g['below_mean']*100,3)}% | "
              f"{_fmt(g['mean_gap_pp'],3)} | {_fmt(g['p_perm'],4)} |")
            if not np.isnan(g["p_perm"]):
                gap_pvals.append(g["p_perm"])
                gap_cells.append((name, h))
    w("")
    rej, adj = benjamini_hochberg(gap_pvals, BH_Q)
    w(f"**BH-FDR (q<{BH_Q}) across the {len(gap_pvals)}-cell SPY+QQQ x horizon grid:** "
      f"{sum(rej)} survivors.")
    for (name, h), r, a in zip(gap_cells, rej, adj):
        w(f"- {name} {h}d: BH-adj p={_fmt(a,4)}, reject={'YES' if r else 'no'}")
    w("")

    # ---- control: lagged-move strata ----
    w("## Control — gap WITHIN lagged 5-day move strata (registered control)")
    w("")
    w("If the regime gap is merely a proxy for the index's own recent move, it "
      "collapses once we split by whether the trailing 5-day return was up or "
      "down. Survival in BOTH strata = the trend regime adds information beyond "
      "the lagged move.")
    w("")
    w("| index | h | up-stratum WR gap (pp) | up n(a/b) | down-stratum WR gap (pp) | down n(a/b) |")
    w("|---|---|---|---|---|---|")
    for name, res in results:
        for h in HORIZONS:
            g = res["per_h"][h]
            up, dn = g["gap_lag_up"], g["gap_lag_dn"]
            w(f"| {name} | {h}d | {_fmt(up['wr_gap_pp'])} | {up['above_n']}/{up['below_n']} | "
              f"{_fmt(dn['wr_gap_pp'])} | {dn['above_n']}/{dn['below_n']} |")
    w("")

    # ---- 3-way trend_state context ----
    w("## Context — forward win-rate by 3-way trend_state (green/yellow/red)")
    w("")
    w("Frozen `_classify_trend_state`: green = all 3 votes bullish, red = none, "
      "yellow = mixed. SPY only.")
    w("")
    w("| h | green n | green WR | yellow n | yellow WR | red n | red WR |")
    w("|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        s = spy["per_h"][h]["state_wr"]
        w(f"| {h}d | {s['green']['n']} | {_fmt(s['green']['wr']*100 if not np.isnan(s['green']['wr']) else float('nan'))}% | "
          f"{s['yellow']['n']} | {_fmt(s['yellow']['wr']*100 if not np.isnan(s['yellow']['wr']) else float('nan'))}% | "
          f"{s['red']['n']} | {_fmt(s['red']['wr']*100 if not np.isnan(s['red']['wr']) else float('nan'))}% |")
    w("")

    # ---- held-out sub-period ----
    w("## Out-of-sample — held-out late sub-period (SPY)")
    w("")
    w(f"Split at {held['split_date']}. The late half is the held-out test; the "
      "win-rate gap sign should hold.")
    w("")
    w("| sub-period | h | n above | n below | WR gap (pp) | perm p |")
    w("|---|---|---|---|---|---|")
    for key in ("early", "late"):
        sub = held[key]
        for h in HORIZONS:
            g = sub["per_h"][h]
            w(f"| {sub['label']} | {h}d | {g['above_n']} | {g['below_n']} | "
              f"{_fmt(g['wr_gap_pp'])} | {_fmt(g['p_perm'],4)} |")
    w("")

    # ---- honesty section ----
    w("## Honest caveats")
    w("")
    w("- The above-/below-200DMA forward-return spread is a **well-known regime "
      "effect**, not a novel discovery. This back-test only certifies whether it "
      "is real, large enough (>= 4pp), control-robust, and transfers — exactly "
      "the pre-registered bar.")
    w("- h=5 uses **overlapping** windows; its permutation p is optimistic "
      "(residual autocorrelation). Lean on the h=1 non-overlapping result.")
    w("- This is a MARKET-LEVEL test of the index's own forward return by its own "
      "regime. It does **NOT** prove the per-ticker alert-level claim.")
    w("- **The PER-TICKER >= 4pp alert-win-rate lift CANNOT be proven on the "
      "current 48-alert sample** (n far too small for a 4pp proportion gap). That "
      "per-ticker gating stays **SHADOW / forward-collect only**; only the "
      "market-level regime read is certified here.")
    w("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="F3 trend-regime historical back-test.")
    ap.add_argument("--no-download", action="store_true",
                    help="Use cached parquet store only (no yfinance calls).")
    ap.add_argument("--force-download", action="store_true",
                    help="Re-download even if a series is already cached.")
    ap.add_argument("--start", default=BACKTEST_START)
    args = ap.parse_args()

    store = _get_store()
    if args.no_download:
        have = [s for s in INDEX_SYMBOLS if store.series_exists(s)]
    else:
        have = download_and_store(store, INDEX_SYMBOLS, args.start,
                                  force=args.force_download)

    if "SPY" not in have:
        log.error("SPY missing — cannot run the back-test.")
        return 1

    panel = store.load_panel(have)
    panel = panel[panel.index >= pd.Timestamp(args.start)]
    spy_closes = panel["SPY_close"].dropna()
    data_range = (f"{len(have)} index symbols, "
                  f"{str(spy_closes.index.min().date())} -> "
                  f"{str(spy_closes.index.max().date())} ({len(spy_closes)} trading days)")
    log.info("Panel: %s", data_range)

    spy = analyse_symbol(spy_closes, "SPY")
    qqq = None
    if "QQQ" in have:
        qqq_closes = panel["QQQ_close"].dropna()
        qqq = analyse_symbol(qqq_closes, "QQQ")
    held = analyse_held_out(spy_closes, "SPY")

    verdict, vnotes = _verdict(spy, qqq, held)
    report = build_report(spy, qqq, held, data_range, verdict, vnotes)

    out_dir = ROOT / ".claude" / "discover" / "trade-edge-features"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "F3-backtest-result.md"
    out_path.write_text(report)
    print("\n" + report + "\n")
    log.info("Verdict: %s. Report written to %s", verdict, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
