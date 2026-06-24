"""LOOK-AHEAD test for the dispersion constructions.

Mirrors tests/test_lookahead_phase3.py exactly. Builds a synthetic wide panel that
includes SP500_DISP_value, SP500_DOWN_DISP_value, NDX_DISP_value, NDX_DOWN_DISP_value
(as if loaded from the Parquet store via load_panel), then asserts each construction's
firing series at time t is identical whether computed on the full panel or the prefix
panel[0..t]. Any divergence = look-ahead bias in the feature computation.

Key checks:
  - trailing_percentile (used for dispersion_pct): rolling window with apply; PIT by
    construction (only sees observations up to and including t).
  - near_high: rolling_max over 60 days; trailing-only.
  - downside semi-dispersion: same trailing_percentile applied to down_disp column.
  - The d_ndx_high_disp_near_high transfer construction: uses NDX_DISP_value and SPY
    near-high — both trailing, no future information.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals import conditions_dispersion as CD


def _synth_panel(n: int = 800, seed: int = 42) -> pd.DataFrame:
    """Synthetic panel with all columns that the dispersion constructions read."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2006-01-01", periods=n)

    def price_series(start: float, vol: float) -> pd.Series:
        r = rng.normal(0.0003, vol, n)
        return pd.Series(start * np.exp(np.cumsum(r)), index=idx)

    spy = price_series(120.0, 0.011)
    qqq = price_series(80.0, 0.013)
    rsp = price_series(60.0, 0.011)
    qqqe = price_series(55.0, 0.012)
    vix = price_series(16.0, 0.06).clip(9, 80)

    cols: dict = {}
    for nm, s in [("SPY", spy), ("QQQ", qqq), ("RSP", rsp), ("QQQE", qqqe), ("VIX", vix)]:
        cols[f"{nm}_close"] = s
        cols[f"{nm}_open"] = s.shift(1).fillna(s.iloc[0])
        cols[f"{nm}_high"] = s * (1 + np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_low"] = s * (1 - np.abs(rng.normal(0, 0.004, n)))
        cols[f"{nm}_volume"] = pd.Series(rng.integers(1_000_000, 9_000_000, n), index=idx, dtype=float)

    # Synthetic dispersion series (as stored in the Parquet store; column = "value")
    # Stored series come back with prefix "{name}_" -> "SP500_DISP_value" etc.
    base_disp = np.abs(rng.normal(0.008, 0.003, n))  # ~0.8% mean cross-sectional std
    cols["SP500_DISP_value"] = pd.Series(base_disp, index=idx)
    cols["SP500_DOWN_DISP_value"] = pd.Series(base_disp * rng.uniform(0.8, 1.2, n), index=idx)
    cols["NDX_DISP_value"] = pd.Series(base_disp * rng.uniform(0.9, 1.3, n), index=idx)
    cols["NDX_DOWN_DISP_value"] = pd.Series(base_disp * rng.uniform(0.85, 1.25, n), index=idx)

    return pd.DataFrame(cols, index=idx)


# All constructions to probe, including the internal primitives (same pattern as phase3 test)
_CONSTRUCTIONS: dict[str, object] = {c.name: c.fn for c in CD.build_constructions()}
# Also probe the dispersion primitives directly
_CONSTRUCTIONS["sp500_disp_pct[252]"] = lambda p: CD.sp500_disp_pct(p, 252)
_CONSTRUCTIONS["sp500_disp_pct[126]"] = lambda p: CD.sp500_disp_pct(p, 126)
_CONSTRUCTIONS["sp500_disp_pct[60]"] = lambda p: CD.sp500_disp_pct(p, 60)
_CONSTRUCTIONS["sp500_down_disp_pct[252]"] = lambda p: CD.sp500_down_disp_pct(p, 252)
_CONSTRUCTIONS["ndx_disp_pct[252]"] = lambda p: CD.ndx_disp_pct(p, 252)
_CONSTRUCTIONS["ctl_disp_only"] = CD.ctl_disp_only
_CONSTRUCTIONS["d_ndx_high_disp_near_high"] = CD.d_ndx_high_disp_near_high

_PROBE_TS = [600, 680, 740, 799]


@pytest.mark.parametrize("name", list(_CONSTRUCTIONS))
def test_dispersion_firing_is_point_in_time(name: str) -> None:
    """Truncation-invariance check: value at t computed on the full panel == value at t
    computed on the panel truncated to rows 0..t. Any divergence = look-ahead leak."""
    panel = _synth_panel()
    fn = _CONSTRUCTIONS[name]
    full = fn(panel)
    for t in _PROBE_TS:
        prefix_result = fn(panel.iloc[: t + 1])
        a = full.iloc[t]
        b = prefix_result.iloc[t]
        if isinstance(a, (bool, np.bool_)):
            assert bool(a) == bool(b), (
                f"{name} LOOK-AHEAD at t={t}: full={a} prefix={b}")
        elif pd.isna(a) and pd.isna(b):
            continue
        else:
            assert np.isclose(float(a), float(b), rtol=1e-9, atol=1e-12), (
                f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}")
