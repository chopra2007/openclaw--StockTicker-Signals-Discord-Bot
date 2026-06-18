"""LOOK-AHEAD test for the Phase-2 CONFLUENCE composites.

The base look-ahead suite proves each utility is truncation-invariant. The critic's
concern: a NEW composite condition can still pass vacuously unless its *firing series*
is itself truncation-checked. This file builds a synthetic wide panel with every column
the Phase-2 conditions read and asserts each construction's boolean firing series at t is
identical whether computed on the full panel or the prefix panel[0..t].
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals import conditions_phase2 as C2


def _synth_panel(n: int = 700, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-01", periods=n)

    def series(start, vol):
        r = rng.normal(0.0003, vol, n)
        return pd.Series(start * np.exp(np.cumsum(r)), index=idx)

    spy = series(120, 0.011)
    qqq = series(80, 0.013)
    rsp = series(60, 0.011)
    qqqe = series(55, 0.012)
    vix = series(16, 0.06).clip(9, 80)
    vvix = series(90, 0.05).clip(60, 200)
    cols = {}
    for nm, s in [("SPY", spy), ("QQQ", qqq), ("RSP", rsp), ("QQQE", qqqe),
                  ("VIX", vix), ("VVIX", vvix)]:
        cols[f"{nm}_close"] = s
        cols[f"{nm}_open"] = s.shift(1).fillna(s.iloc[0])
        cols[f"{nm}_high"] = s * (1 + np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_low"] = s * (1 - np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_volume"] = pd.Series(rng.integers(1_000_000, 9_000_000, n), index=idx).astype(float)
    cols["ABINYSE_abi"] = pd.Series(rng.uniform(0.0, 0.9, n), index=idx)
    return pd.DataFrame(cols, index=idx)


_CONSTRUCTIONS = {c.name: c.fn for c in C2.build_constructions()}
_CONSTRUCTIONS["dist_cooccur_baseline"] = C2.dist_cooccur_baseline
_CONSTRUCTIONS["ungated_watch"] = C2.ungated_watch
_CONSTRUCTIONS["DSI"] = C2.distribution_stress_index
_CONSTRUCTIONS["eligible_top"] = C2.eligible_top
_CONSTRUCTIONS["eligible_bottom"] = C2.eligible_bottom

_PROBE_TS = [560, 600, 650, 699]


@pytest.mark.parametrize("name", list(_CONSTRUCTIONS))
def test_phase2_firing_is_point_in_time(name: str) -> None:
    panel = _synth_panel()
    fn = _CONSTRUCTIONS[name]
    full = fn(panel)
    for t in _PROBE_TS:
        prefix = fn(panel.iloc[: t + 1])
        a, b = full.iloc[t], prefix.iloc[t]
        if isinstance(a, (bool, np.bool_)):
            assert bool(a) == bool(b), f"{name} LOOK-AHEAD at t={t}: full={a} prefix={b}"
        else:  # DSI (continuous)
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(a, b, rtol=1e-9, atol=1e-12), (
                f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}")
