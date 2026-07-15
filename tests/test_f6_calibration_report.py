"""F6 (#76 menu) — weekly calibration report Discord formatter.

Tests the pure formatter (no DB): healthy horizons render Brier/AUC lines;
thin-sample horizons (n < min_n_number) print the raw count, never a number;
NaN/None metrics render as 'n/a', never 'nan'.
"""
from __future__ import annotations

from consensus_engine.eval import report


def _sections(cal_24h_n=240, disc_24h_n=300):
    return {
        "calibration": {"horizons": {
            "1h": {"n": 4, "note": "too few rows"},
            "24h": {"n": cal_24h_n, "n_test": 72,
                    "raw": {"brier": 0.211, "base_rate_brier": 0.244, "auc": 0.61},
                    "isotonic_test_brier": 0.203, "beta_test_brier": float("nan")},
        }},
        "discrimination": {"horizons": {
            "1h": {"n": 5, "note": "too few resolved"},
            "24h": {"n": disc_24h_n, "base_rate": 0.52, "auc": 0.63,
                    "p_at_10": 0.71, "top_decile_lift": 1.37},
        }},
    }


def test_healthy_horizon_shows_brier_and_auc():
    out = report.format_discord(_sections())
    assert "Brier 0.211 vs base-rate 0.244" in out
    assert "AUC 0.630" in out
    assert "top-decile lift 1.37" in out


def test_thin_sample_prints_raw_count_not_a_number():
    out = report.format_discord(_sections())
    # n=4 and n=5 horizons must show the count, never a Brier/AUC value
    assert "1h: 4 resolved — too few to score yet" in out
    assert "1h: 5 resolved — too few to score yet" in out


def test_below_min_n_number_suppresses_numbers():
    # A horizon that HAS raw numbers but n < 10 must still be suppressed.
    out = report.format_discord(_sections(cal_24h_n=6), min_n_number=10)
    assert "6 resolved — too few to score yet" in out
    assert "Brier 0.211" not in out


def test_nan_renders_as_na_never_nan():
    out = report.format_discord(_sections())
    assert "beta n/a" in out
    assert "nan" not in out.lower()


def test_empty_sections_do_not_crash():
    out = report.format_discord({})
    assert "no calibration data yet" in out
    assert "no discrimination data yet" in out


def test_fmt_num_guards():
    assert report._fmt_num(float("nan")) == "n/a"
    assert report._fmt_num(None) == "n/a"
    assert report._fmt_num(0.5) == "0.500"
    assert report._fmt_num(0.5, 2) == "0.50"
