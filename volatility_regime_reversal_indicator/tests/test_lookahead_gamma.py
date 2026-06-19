"""LOOK-AHEAD test for the Phase-GAMMA constructions.

Like the Phase-3 look-ahead suite, but for the dealer-gamma (gex) top constructions, the
dark-pool-dix (dix) bottom constructions, and their controls. Extends the synthetic wide panel
with SQZ_gex (a signed series that crosses zero — so the negative-gamma flag actually fires) and
SQZ_dix (a 0-1 buy ratio), then asserts each construction's firing series at t is identical
whether computed on the full panel or the prefix panel[0..t]. A non-vacuous 'it actually fires'
guard makes sure the truncation-invariance check isn't trivially False==False.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features import utils as U
from src.signals import conditions_gamma as CG


def _synth_panel(n: int = 800, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-01", periods=n)

    def series(start, vol):
        r = rng.normal(0.0003, vol, n)
        return pd.Series(start * np.exp(np.cumsum(r)), index=idx)

    spy = series(120, 0.011)
    qqq = series(80, 0.013)
    rsp = series(60, 0.011)
    qqqe = series(55, 0.012)
    vix = series(16, 0.06).clip(9, 80)
    vix3m = series(17, 0.05).clip(9, 80)
    vvix = series(90, 0.05).clip(60, 200)
    cols = {}
    for nm, s in [("SPY", spy), ("QQQ", qqq), ("RSP", rsp), ("QQQE", qqqe),
                  ("VIX", vix), ("VVIX", vvix)]:
        cols[f"{nm}_close"] = s
        cols[f"{nm}_open"] = s.shift(1).fillna(s.iloc[0])
        cols[f"{nm}_high"] = s * (1 + np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_low"] = s * (1 - np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_volume"] = pd.Series(rng.integers(1_000_000, 9_000_000, n), index=idx).astype(float)
    cols["VIX3M_close"] = vix3m
    cols["ABINYSE_adv"] = pd.Series(rng.uniform(1000, 4000, n), index=idx)
    cols["ABINYSE_dec"] = pd.Series(rng.uniform(1000, 4000, n), index=idx)
    cols["ABINYSE_abi"] = pd.Series(rng.uniform(0.0, 0.9, n), index=idx)
    # SQZ: gex is a signed $ gamma series that crosses zero (so neg_gamma_flag fires);
    # dix is a 0-1 dark-pool buy ratio.
    cols["SQZ_gex"] = pd.Series(rng.normal(0.0, 1.5e9, n), index=idx)
    cols["SQZ_dix"] = pd.Series(rng.uniform(0.33, 0.55, n), index=idx)
    return pd.DataFrame(cols, index=idx)


_CONSTRUCTIONS = {c.name: c.fn for c in CG.build_constructions()}
# Exercise the leak-prone PRIMITIVE features directly, with live True/continuous values, so the
# AND-composites' look-ahead surface is covered even when an AND rarely fires on the synth seed.
_CONSTRUCTIONS["neg_gamma_regime"] = CG.neg_gamma_regime
_CONSTRUCTIONS["low_gex_regime"] = CG.low_gex_regime
_CONSTRUCTIONS["neg_gamma_ma"] = CG.neg_gamma_ma
_CONSTRUCTIONS["high_dix"] = CG.high_dix
_CONSTRUCTIONS["negative_gamma_flag"] = lambda p: U.negative_gamma_flag(p["SQZ_gex"])
_CONSTRUCTIONS["gex_trailing_pct"] = lambda p: U.trailing_percentile(p["SQZ_gex"], 252)
_CONSTRUCTIONS["dix_trailing_pct"] = lambda p: U.trailing_percentile(p["SQZ_dix"], 252)

_PROBE_TS = [600, 680, 740, 799]


@pytest.mark.parametrize("name", list(_CONSTRUCTIONS))
def test_gamma_firing_is_point_in_time(name: str) -> None:
    panel = _synth_panel()
    fn = _CONSTRUCTIONS[name]
    full = fn(panel)
    for t in _PROBE_TS:
        prefix = fn(panel.iloc[: t + 1])
        a, b = full.iloc[t], prefix.iloc[t]
        if isinstance(a, (bool, np.bool_)):
            assert bool(a) == bool(b), f"{name} LOOK-AHEAD at t={t}: full={a} prefix={b}"
        else:
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(a, b, rtol=1e-9, atol=1e-12), (
                f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}")


def test_gamma_constructions_actually_fire() -> None:
    """Non-vacuous guard: the negative-gamma flag, low-gex regime and high-dix flag must each
    fire at least once on the synth panel, so the truncation-invariance check above is exercised
    against real True values rather than an all-False series."""
    panel = _synth_panel()
    assert CG.neg_gamma_regime(panel).sum() > 0, "neg_gamma_regime never fires on synth panel"
    assert CG.low_gex_regime(panel).sum() > 0, "low_gex_regime never fires on synth panel"
    assert CG.high_dix(panel).sum() > 0, "high_dix never fires on synth panel"
