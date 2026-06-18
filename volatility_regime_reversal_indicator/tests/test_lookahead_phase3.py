"""LOOK-AHEAD test for the Phase-3 constructions.

Like the Phase-2 look-ahead suite, but for the Phase-3 watch-state composite, the
watch->break trigger, the breadth-thrust bottom + controls, and the benchmarks. Builds a
synthetic wide panel with EVERY column the Phase-3 conditions read (adds VIX3M_close and
ABINYSE_adv/ABINYSE_dec, which the Phase-2 synth panel lacks) and asserts each construction's
firing series at t is identical whether computed on the full panel or the prefix panel[0..t].
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals import conditions_phase2 as C2
from src.signals import conditions_phase3 as C3


def _synth_panel(n: int = 800, seed: int = 13) -> pd.DataFrame:
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
    return pd.DataFrame(cols, index=idx)


_CONSTRUCTIONS = {c.name: c.fn for c in C3.build_constructions()}
_CONSTRUCTIONS["top_watch_state"] = C3.top_watch_state
_CONSTRUCTIONS["watch_on"] = C3.watch_on
# Assert each leak-prone PRIMITIVE directly: some composites (T_watch_break[*,50],
# B_thrust_canonical) rarely fire on the synthetic seed, so the AND-composite test alone is
# weak (False==False). Exercising the parts guarantees the leak surface is covered with live
# True/continuous values regardless of whether the AND happens to fire.
_CONSTRUCTIONS["support_break"] = C3.support_break
_CONSTRUCTIONS["zbt_thrust"] = C3.zbt_thrust
_CONSTRUCTIONS["zbt_thrust_canonical"] = C3.zbt_thrust_canonical
_CONSTRUCTIONS["_recent_washout"] = C3._recent_washout
_CONSTRUCTIONS["eligible_top"] = C2.eligible_top
_CONSTRUCTIONS["eligible_bottom"] = C2.eligible_bottom

_PROBE_TS = [600, 680, 740, 799]


@pytest.mark.parametrize("name", list(_CONSTRUCTIONS))
def test_phase3_firing_is_point_in_time(name: str) -> None:
    panel = _synth_panel()
    fn = _CONSTRUCTIONS[name]
    full = fn(panel)
    for t in _PROBE_TS:
        prefix = fn(panel.iloc[: t + 1])
        a, b = full.iloc[t], prefix.iloc[t]
        if isinstance(a, (bool, np.bool_)):
            assert bool(a) == bool(b), f"{name} LOOK-AHEAD at t={t}: full={a} prefix={b}"
        else:  # continuous (top_watch_state)
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(a, b, rtol=1e-9, atol=1e-12), (
                f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}")
