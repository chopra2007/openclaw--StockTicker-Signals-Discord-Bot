"""Stage-3 options-chain legs (discover next-features-jul2026): k4 dealer GEX,
k5 gamma-flip, r10 IV skew, r16 OI-pinning HHI, plus the embed-only flag gating.

All helpers are pure and computed from the already-fetched front chains; these
tests use synthetic chains so they never touch the network."""
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from consensus_engine.scanners import options
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import embed


def _exp(days_out: int) -> str:
    return (date.today() + timedelta(days=days_out)).isoformat()


def _chain(calls_rows, puts_rows, *, with_greeks: bool):
    """Build a yfinance-shaped (no greeks) or Schwab-shaped (delta/gamma) chain."""
    cols = ["strike", "openInterest", "impliedVolatility"]
    if with_greeks:
        cols += ["delta", "gamma"]
    return SimpleNamespace(
        calls=pd.DataFrame(calls_rows, columns=cols),
        puts=pd.DataFrame(puts_rows, columns=cols),
    )


# --------------------------------------------------------------------------- #
# _bs_gamma
# --------------------------------------------------------------------------- #

def test_bs_gamma_finite_positive():
    g = options._bs_gamma(spot=100.0, K=100.0, t=30 / 365.0, iv=0.20)
    assert g is not None and g > 0


@pytest.mark.parametrize("kw", [
    dict(spot=0, K=100, t=0.1, iv=0.2),
    dict(spot=100, K=100, t=0, iv=0.2),
    dict(spot=100, K=100, t=0.1, iv=0),
    dict(spot=100, K=100, t=0.1, iv=None),
])
def test_bs_gamma_bad_inputs_none(kw):
    assert options._bs_gamma(**kw) is None


# --------------------------------------------------------------------------- #
# k4 GEX + k5 gamma-flip
# --------------------------------------------------------------------------- #

def test_gex_mixed_signs_and_interpolated_flip():
    # Constant gamma; net_raw(K) = 0.02*(call_oi - put_oi):
    #   90 -> +4.0 (cum +4), 100 -> -2.0 (cum +2), 110 -> -6.0 (cum -4).
    # cum crosses zero between 100 and 110: frac = 2/6 -> flip = 103.33.
    e = _exp(5)
    calls = [[90.0, 200, 0.2, 0.5, 0.02], [100.0, 0, 0.2, 0.4, 0.02], [110.0, 0, 0.2, 0.3, 0.02]]
    puts = [[90.0, 0, 0.2, -0.5, 0.02], [100.0, 100, 0.2, -0.4, 0.02], [110.0, 300, 0.2, -0.3, 0.02]]
    gex = options._gex_for_chain({e: _chain(calls, puts, with_greeks=True)}, spot=100.0, nearest=2)
    assert gex is not None
    signs = {1 if x["net_gex"] > 0 else -1 for x in gex["net_gex"]}
    assert signs == {1, -1}                       # mixed
    assert gex["basis"] == "schwab-native"        # native gamma present, no BS fill
    assert gex["net_sign"] == "short"             # total = 4-2-6 = -4 < 0
    assert gex["gamma_flip"] == pytest.approx(103.33, abs=0.05)


def test_gex_no_crossing_flip_none():
    # All-put chain -> every strike net-negative -> cumulative never crosses.
    e = _exp(5)
    puts = [[95.0, 100, 0.2, -0.5, 0.02], [100.0, 100, 0.2, -0.4, 0.02], [105.0, 100, 0.2, -0.3, 0.02]]
    calls = [[95.0, 0, 0.2, 0.5, 0.02], [100.0, 0, 0.2, 0.4, 0.02], [105.0, 0, 0.2, 0.3, 0.02]]
    gex = options._gex_for_chain({e: _chain(calls, puts, with_greeks=True)}, spot=100.0, nearest=2)
    assert gex is not None
    assert gex["gamma_flip"] is None              # never extrapolate


def test_gex_yfinance_path_uses_black_scholes():
    # No gamma/delta columns -> gamma must come from Black-Scholes on IV.
    e = _exp(7)
    calls = [[95.0, 100, 0.25], [100.0, 200, 0.25], [105.0, 100, 0.25]]
    puts = [[95.0, 100, 0.25], [100.0, 150, 0.25], [105.0, 100, 0.25]]
    gex = options._gex_for_chain({e: _chain(calls, puts, with_greeks=False)}, spot=100.0, nearest=2)
    assert gex is not None
    assert gex["basis"] == "black-scholes"
    assert gex["net_gex"]                          # non-empty


# --------------------------------------------------------------------------- #
# r10 IV skew
# --------------------------------------------------------------------------- #

def test_iv_skew_25_delta_put_skew():
    e = _exp(5)
    # Puts richer than calls at the ~25-delta wings -> positive skew.
    calls = [[105.0, 10, 0.18, 0.25, 0.01], [110.0, 10, 0.17, 0.15, 0.01]]
    puts = [[95.0, 10, 0.22, -0.25, 0.01], [90.0, 10, 0.24, -0.15, 0.01]]
    sk = options._iv_skew_for_chain({e: _chain(calls, puts, with_greeks=True)}, spot=100.0)
    assert sk is not None
    assert sk["basis"] == "25-delta"
    assert sk["value"] == pytest.approx(0.22 - 0.18, abs=1e-6)   # put_iv - call_iv > 0
    assert sk["value"] > 0


def test_iv_skew_moneyness_matched_when_no_delta():
    e = _exp(5)
    calls = [[105.0, 10, 0.18], [110.0, 10, 0.17]]
    puts = [[95.0, 10, 0.22], [90.0, 10, 0.24]]
    sk = options._iv_skew_for_chain({e: _chain(calls, puts, with_greeks=False)}, spot=100.0)
    assert sk is not None
    assert sk["basis"] == "moneyness-matched"
    assert sk["value"] > 0


def test_iv_skew_none_without_valid_pair():
    e = _exp(5)
    calls = [[105.0, 10, 0.18, 0.25, 0.01]]
    puts = pd.DataFrame([], columns=["strike", "openInterest", "impliedVolatility", "delta", "gamma"])
    ch = SimpleNamespace(calls=pd.DataFrame(calls, columns=["strike", "openInterest", "impliedVolatility", "delta", "gamma"]), puts=puts)
    assert options._iv_skew_for_chain({e: ch}, spot=100.0) is None


# --------------------------------------------------------------------------- #
# r16 OI-pinning HHI
# --------------------------------------------------------------------------- #

def test_pinning_hhi_handcheck_and_descriptor():
    e = _exp(3)
    # In-band OI: 100@99, 100@100, 200@101 -> shares .25/.25/.5 -> HHI = .375.
    calls = [[99.0, 100, 0.2], [100.0, 50, 0.2], [101.0, 100, 0.2]]
    puts = [[99.0, 0, 0.2], [100.0, 50, 0.2], [101.0, 100, 0.2]]
    p = options._pinning_herfindahl({e: _chain(calls, puts, with_greeks=False)}, spot=100.0, band_pct=0.05)
    assert p is not None
    assert p["hhi"] == pytest.approx(0.375, abs=1e-6)
    assert p["descriptor"] == "high"
    assert p["dominant_strike"] == 101.0
    assert 0.0 <= p["hhi"] <= 1.0


def test_pinning_none_when_far_from_opex():
    e = _exp(40)   # beyond _PINNING_MAX_DTE_DAYS
    calls = [[99.0, 100, 0.2], [100.0, 100, 0.2], [101.0, 100, 0.2]]
    puts = [[99.0, 100, 0.2], [100.0, 100, 0.2], [101.0, 100, 0.2]]
    assert options._pinning_herfindahl({e: _chain(calls, puts, with_greeks=False)}, spot=100.0) is None


def test_pinning_none_when_single_in_band_strike():
    e = _exp(3)
    calls = [[100.0, 100, 0.2], [200.0, 100, 0.2]]   # only 100 is within 5% of spot
    puts = [[100.0, 0, 0.2], [200.0, 0, 0.2]]
    assert options._pinning_herfindahl({e: _chain(calls, puts, with_greeks=False)}, spot=100.0) is None


# --------------------------------------------------------------------------- #
# _chain_legs flag gating (embed-only, default OFF)
# --------------------------------------------------------------------------- #

def _force_flags_on(monkeypatch, **overrides):
    from consensus_engine import config as _cfg
    current = _cfg.get   # already the conftest flag-off patch

    def _patched(key, default=None):
        if key in overrides:
            return overrides[key]
        return current(key, default)
    monkeypatch.setattr(_cfg, "get", _patched)


def test_chain_legs_all_none_when_flags_off():
    e = _exp(3)
    calls = [[99.0, 100, 0.2, 0.5, 0.02], [100.0, 100, 0.2, 0.4, 0.02], [101.0, 100, 0.2, 0.3, 0.02]]
    puts = [[99.0, 100, 0.2, -0.5, 0.02], [100.0, 100, 0.2, -0.4, 0.02], [101.0, 100, 0.2, -0.3, 0.02]]
    legs = options._chain_legs({e: _chain(calls, puts, with_greeks=True)}, spot=100.0)
    assert legs == {"gex": None, "iv_skew": None, "oi_pinning": None}


def test_chain_legs_computed_when_flags_on(monkeypatch):
    _force_flags_on(
        monkeypatch,
        **{"features.dealer_gamma.enabled": True,
           "features.iv_skew.enabled": True,
           "features.oi_pinning.enabled": True},
    )
    e = _exp(3)
    calls = [[99.0, 100, 0.18, 0.5, 0.02], [100.0, 100, 0.18, 0.25, 0.02], [101.0, 100, 0.17, 0.15, 0.02]]
    puts = [[99.0, 100, 0.22, -0.25, 0.02], [100.0, 100, 0.22, -0.4, 0.02], [101.0, 100, 0.24, -0.5, 0.02]]
    legs = options._chain_legs({e: _chain(calls, puts, with_greeks=True)}, spot=100.0)
    assert isinstance(legs["gex"], dict)
    assert isinstance(legs["iv_skew"], dict)
    assert isinstance(legs["oi_pinning"], dict)


# --------------------------------------------------------------------------- #
# Embed gating — new fields appear only when their flag is ON
# --------------------------------------------------------------------------- #

_LEGS = dict(
    max_pain={"spot": 100.0, "weekly": {"strike": 100.0, "expiry": _exp(3), "total_oi": 500},
              "monthly": None, "pc_oi_ratio": 1.1, "call_oi_sum": 300.0, "put_oi_sum": 330.0},
    gex={"net_gex": [{"strike": 100.0, "net_gex": 5.0}], "top": [{"strike": 100.0, "net_gex": 5.0}],
         "total_net_gex": 5.0, "net_sign": "long", "gamma_flip": 101.5,
         "basis": "schwab-native", "n_expiries": 2},
    iv_skew={"value": 0.03, "basis": "25-delta", "put_iv": 0.22, "call_iv": 0.19,
             "put_strike": 95.0, "call_strike": 105.0, "expiry": _exp(3)},
    oi_pinning={"hhi": 0.30, "descriptor": "high", "dominant_strike": 100.0, "dte": 3, "band_pct": 0.05},
    skew_index={"value": 148.0, "band": "elevated"},
)

_NEW_FIELD_NAMES = {"🎯 Dealer Gamma", "IV Skew", "OI Pinning", "SKEW"}


def _render():
    sf = StructuredFields(direction="BULLISH", confidence_label="HIGH",
                          current_price=100.0, **_LEGS)
    return embed.build_embed(
        ticker="SPY", structured=sf, score_breakdown=None, narrative="",
        sources_used=["news"], cache_age_seconds=None,
    )


def test_embed_new_fields_absent_when_flags_off():
    names = {f["name"] for f in _render().get("fields", [])}
    assert not (_NEW_FIELD_NAMES & names)
    # Existing options field still renders (Max Pain present).
    assert "Max Pain" in names


def test_embed_new_fields_present_when_flags_on(monkeypatch):
    _force_flags_on(
        monkeypatch,
        **{"features.dealer_gamma.enabled": True,
           "features.iv_skew.enabled": True,
           "features.oi_pinning.enabled": True,
           "features.skew_index.enabled": True},
    )
    fields = _render().get("fields", [])
    names = {f["name"] for f in fields}
    assert _NEW_FIELD_NAMES <= names               # all four appear
    assert "Max Pain" in names                      # existing field intact
    gex_field = next(f for f in fields if f["name"] == "🎯 Dealer Gamma")
    assert "front-2-exp dealer gamma" in gex_field["value"]
    skew_field = next(f for f in fields if f["name"] == "IV Skew")
    assert "25-delta" in skew_field["value"]
