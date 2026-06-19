"""LOOK-AHEAD test for the Phase-4 capitulation->thrust (Lowry 90/90) constructions.

LOAD-BEARING: if any firing series, utils feature, or eligibility mask is not
truncation-invariant (feature[t] on the full panel == feature[t] on the prefix panel[0..t]),
the whole backtest is fake. Builds a synthetic wide panel with EVERY column the Phase-4
conditions read (GSPC_close/OHLC and NYSE_UDVOL_adv_volume/dec_volume) and asserts each
construction's firing series at t is identical whether computed on the full panel or panel[0..t].

The synthetic volume is built so genuine 90% up/down days actually occur (so the AND-composites
fire on live True values, not vacuous False==False).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features import utils as U
from src.signals import conditions_phase4 as C4


def _synth_panel(n: int = 800, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("1980-01-01", periods=n)

    ret = rng.normal(0.0002, 0.012, n)
    gspc = pd.Series(100.0 * np.exp(np.cumsum(ret)), index=idx)
    cols = {
        "GSPC_close": gspc,
        "GSPC_open": gspc.shift(1).fillna(gspc.iloc[0]),
        "GSPC_high": gspc * (1 + np.abs(rng.normal(0, 0.004, n))),
        "GSPC_low": gspc * (1 - np.abs(rng.normal(0, 0.004, n))),
        "GSPC_volume": pd.Series(rng.integers(1_000_000, 9_000_000, n), index=idx).astype(float),
    }
    # advancing/declining VOLUME: base random, but inject extreme 90%+ days both directions so
    # capitulation_90 / thrust_90 / the 90/90 sequence actually fire on the synthetic seed.
    adv = rng.uniform(2e8, 2e9, n)
    dec = rng.uniform(2e8, 2e9, n)
    down_days = rng.choice(n, size=40, replace=False)        # 90%+ down days
    dec[down_days] = adv[down_days] * rng.uniform(12, 30, len(down_days))
    up_days = rng.choice(n, size=40, replace=False)          # 90%+ up days
    adv[up_days] = dec[up_days] * rng.uniform(12, 30, len(up_days))
    cols["NYSE_UDVOL_adv_volume"] = pd.Series(adv, index=idx)
    cols["NYSE_UDVOL_dec_volume"] = pd.Series(dec, index=idx)
    cols["NYSE_UDVOL_unch_volume"] = pd.Series(rng.uniform(1e7, 1e8, n), index=idx)
    return pd.DataFrame(cols, index=idx)


# every registered construction + the leak-prone primitives + the eligibility masks
_CONSTRUCTIONS = {c.name: c.fn for c in C4.build_constructions()}
_CONSTRUCTIONS["capitulation_90"] = C4.capitulation_90
_CONSTRUCTIONS["thrust_90"] = C4.thrust_90
_CONSTRUCTIONS["_recent_capitulation_w10"] = lambda p: C4._recent_capitulation(p, 10)
_CONSTRUCTIONS["zbt_volume_thrust"] = C4.zbt_volume_thrust
_CONSTRUCTIONS["eligible_drawdown"] = lambda p: C4.eligible_drawdown(p, -0.05)
_CONSTRUCTIONS["eligible_post_capitulation"] = lambda p: C4.eligible_post_capitulation(p, 25)
# the raw same-day volume-share utils features (continuous)
_CONSTRUCTIONS["up_volume_share"] = lambda p: U.up_volume_share(
    p["NYSE_UDVOL_adv_volume"], p["NYSE_UDVOL_dec_volume"])
_CONSTRUCTIONS["down_volume_share"] = lambda p: U.down_volume_share(
    p["NYSE_UDVOL_adv_volume"], p["NYSE_UDVOL_dec_volume"])

_PROBE_TS = [600, 680, 740, 799]


@pytest.mark.parametrize("name", list(_CONSTRUCTIONS))
def test_phase4_firing_is_point_in_time(name: str) -> None:
    panel = _synth_panel()
    fn = _CONSTRUCTIONS[name]
    full = fn(panel)
    for t in _PROBE_TS:
        prefix = fn(panel.iloc[: t + 1])
        a, b = full.iloc[t], prefix.iloc[t]
        if isinstance(a, (bool, np.bool_)):
            assert bool(a) == bool(b), f"{name} LOOK-AHEAD at t={t}: full={a} prefix={b}"
        else:  # continuous (volume shares)
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(a, b, rtol=1e-9, atol=1e-12), (
                f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}")


def test_synth_panel_actually_fires() -> None:
    """Guard against a vacuous look-ahead test: the 90/90 sequence + both 90% day primitives
    must actually FIRE on the synthetic panel, else the invariance assertions are False==False."""
    panel = _synth_panel()
    assert int(C4.capitulation_90(panel).sum()) > 0
    assert int(C4.thrust_90(panel).sum()) > 0
    assert int(C4.lowry_90_90(panel, 25).sum()) > 0
