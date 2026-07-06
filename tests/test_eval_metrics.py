"""Deterministic unit tests for the eval math and feature extraction.

No network, no live DB. Every expected number is hand-computable so a
reviewer can check the math. Covers the two mistakes prior reviews made:
(1) counting NULL outcomes as misses, (2) confident-wrong log-loss blowups.
"""

from __future__ import annotations

import math

import pytest

from consensus_engine.eval import metrics
from consensus_engine.eval.loaders import Snapshot, extract_features


# ---------------------------------------------------------------------------
# Proper scoring rules
# ---------------------------------------------------------------------------

def test_brier_perfect_and_worst():
    assert metrics.brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert metrics.brier_score([0.0, 1.0], [1, 0]) == pytest.approx(1.0)


def test_brier_half():
    # all 0.5 predictions -> (0.5)^2 mean = 0.25 regardless of labels
    assert metrics.brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == pytest.approx(0.25)


def test_base_rate_brier_equals_variance():
    # base rate 0.4 -> b*(1-b) = 0.24
    labels = [1, 1, 0, 0, 0]  # mean 0.4
    assert metrics.base_rate_brier(labels) == pytest.approx(0.4 * 0.6)


def test_log_loss_clips_confident_wrong():
    # p=1.0 but label 0 would be +inf; clip keeps it finite
    ll = metrics.log_loss([1.0], [0])
    assert math.isfinite(ll) and ll > 30


def test_log_loss_known_value():
    # p=0.5 -> -ln(0.5) = 0.6931 for every point
    assert metrics.log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2), abs=1e-6)


# ---------------------------------------------------------------------------
# Reliability / deciles
# ---------------------------------------------------------------------------

def test_reliability_bins_group_and_average():
    probs = [0.05, 0.15, 0.95, 0.85]
    labels = [0, 1, 1, 0]
    bins = metrics.reliability_bins(probs, labels, n_bins=10)
    # 0.05->bin0, 0.15->bin1, 0.85->bin8, 0.95->bin9  => 4 non-empty bins
    assert len(bins) == 4
    b0 = next(b for b in bins if b["bin_lo"] == 0.0)
    assert b0["n"] == 1 and b0["mean_pred"] == pytest.approx(0.05) and b0["mean_actual"] == 0.0


def test_reliability_last_bin_includes_one():
    bins = metrics.reliability_bins([1.0], [1], n_bins=10)
    assert len(bins) == 1 and bins[0]["n"] == 1


def test_decile_table_equal_counts_and_monotone_range():
    scores = list(range(20))
    labels = [0] * 10 + [1] * 10
    dt = metrics.decile_table(scores, labels, n_bins=10)
    assert len(dt) == 10
    assert all(b["n"] == 2 for b in dt)
    # top two deciles should be all hits (scores 16-19)
    assert dt[-1]["hit_rate"] == 1.0 and dt[0]["hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# Discrimination
# ---------------------------------------------------------------------------

def test_auc_perfect_separation():
    assert metrics.auc([1, 2, 3, 4], [0, 0, 1, 1]) == pytest.approx(1.0)


def test_auc_reversed():
    assert metrics.auc([4, 3, 2, 1], [0, 0, 1, 1]) == pytest.approx(0.0)


def test_auc_ties_half():
    # all identical scores -> pure coin flip 0.5
    assert metrics.auc([1, 1, 1, 1], [0, 1, 0, 1]) == pytest.approx(0.5)


def test_auc_single_class_is_nan():
    assert math.isnan(metrics.auc([1, 2, 3], [1, 1, 1]))


def test_auc_known_value():
    # scores 1,2,3 labels 0,1,0 ; pos={2}. neg scores {1,3}. 2>1 (win), 2<3 (loss)
    # AUC = wins/(pos*neg)=1/2
    assert metrics.auc([1, 2, 3], [0, 1, 0]) == pytest.approx(0.5)


def test_precision_at_k_top_half():
    # top 50% of 4 = top 2 by score: scores 4,3 -> labels 1,1 => precision 1.0
    r = metrics.precision_at_k([1, 2, 3, 4], [0, 0, 1, 1], 0.5)
    assert r["n_selected"] == 2 and r["precision"] == pytest.approx(1.0)


def test_precision_at_k_includes_ties():
    # requested top-1 but a tie at the cutoff pulls in both -> n_selected 2
    r = metrics.precision_at_k([5, 5, 1], [1, 0, 0], 0.34)  # round(3*.34)=1
    assert r["n_selected"] == 2 and r["hits"] == 1 and r["precision"] == pytest.approx(0.5)


def test_top_decile_lift():
    # 20 rows, base rate 0.5; top decile (2 rows, scores 18,19) both hits -> 1.0/0.5 = 2.0
    scores = list(range(20))
    labels = [0] * 10 + [1] * 10
    assert metrics.top_decile_lift(scores, labels) == pytest.approx(2.0)


def test_fpr_by_band():
    scores = [10, 20, 30, 40]
    labels = [0, 1, 1, 1]
    bands = [0, 25, 50]
    out = metrics.fpr_by_band(scores, labels, bands)
    lo = next(b for b in out if b["lo"] == 0)
    hi = next(b for b in out if b["lo"] == 25)
    assert lo["n"] == 2 and lo["hit_rate"] == pytest.approx(0.5) and lo["fpr"] == pytest.approx(0.5)
    assert hi["n"] == 2 and hi["fpr"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Wilson & IC
# ---------------------------------------------------------------------------

def test_wilson_lower_bound_known():
    # 8/10 with z=1.96 -> Wilson LB approx 0.490
    lb = metrics.wilson_lower_bound(8, 10)
    assert lb == pytest.approx(0.490, abs=0.01)


def test_wilson_lb_zero_n():
    assert metrics.wilson_lower_bound(0, 0) == 0.0


def test_wilson_lb_below_upper():
    lo, hi = metrics.wilson_interval(50, 100)
    assert 0 < lo < 0.5 < hi < 1
    assert metrics.wilson_lower_bound(50, 100) == pytest.approx(lo)


def test_wilson_small_n_punished():
    # same 60% hit rate, bigger n -> higher (less punished) lower bound
    small = metrics.wilson_lower_bound(6, 10)
    big = metrics.wilson_lower_bound(60, 100)
    assert big > small


def test_spearman_ic_perfect_monotone():
    assert metrics.spearman_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert metrics.spearman_ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_ic_constant_is_nan():
    assert math.isnan(metrics.spearman_ic([1, 1, 1], [1, 2, 3]))
    assert math.isnan(metrics.pearson_ic([5, 5, 5], [1, 2, 3]))


def test_pearson_ic_known():
    assert metrics.pearson_ic([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Snapshot.hit — the NULL-is-not-a-miss rule
# ---------------------------------------------------------------------------

def test_snapshot_hit_up_down_null():
    sn = Snapshot(ticker="X", decision="WATCHLIST", final_score=70, recorded_at=0,
                  entry=100.0, px={"1h": 101.0, "24h": 99.0, "5d": None})
    assert sn.hit("1h") == 1          # up
    assert sn.hit("24h") == 0         # down
    assert sn.hit("5d") is None       # unresolved -> NOT a miss


def test_snapshot_hit_bad_entry_is_none():
    sn = Snapshot(ticker="X", decision="WATCHLIST", final_score=70, recorded_at=0,
                  entry=0.0, px={"1h": 5.0})
    assert sn.hit("1h") is None       # entry <= 0 -> unusable


def test_resolved_only_rate_differs_from_naive():
    # 4 rows: 2 up, 1 down, 1 NULL. correct rate = 2/3, naive = 2/4.
    rows = [
        Snapshot("A", "W", 70, 0, 100.0, {"1h": 110.0}),
        Snapshot("B", "W", 70, 0, 100.0, {"1h": 120.0}),
        Snapshot("C", "W", 70, 0, 100.0, {"1h": 90.0}),
        Snapshot("D", "W", 70, 0, 100.0, {"1h": None}),
    ]
    resolved = [r.hit("1h") for r in rows if r.hit("1h") is not None]
    assert sum(resolved) / len(resolved) == pytest.approx(2 / 3)
    assert sum(resolved) / len(rows) == pytest.approx(0.5)  # the WRONG naive number


# ---------------------------------------------------------------------------
# Feature extraction from the real (nested-dict) json shape
# ---------------------------------------------------------------------------

def test_extract_features_newer_shape():
    fv = (
        '{"n_opposing": 1, "shadow_score": 65.0, "shadow_prob": 0.5,'
        ' "regime_context": {"z_score": 0.21, "threshold_shift": 0, "cold_start": false},'
        ' "consolidation_result": {"fired": true, "effective_n_clusters": 2,'
        ' "combined_log_odds": 1.3, "consensus_boost": 1},'
        ' "sector_verdict": {"aligned": true, "sector_change_pct": null},'
        ' "contradiction_verdict": {"apply_penalty": true}}'
    )
    f = extract_features(fv)
    assert f["n_opposing"] == 1.0
    assert f["shadow_score"] == 65.0
    assert f["regime_z"] == pytest.approx(0.21)
    assert f["consol_fired"] == 1.0
    assert f["consol_log_odds"] == pytest.approx(1.3)
    assert f["sector_aligned"] == 1.0
    assert f["sector_change_pct"] == 0.0   # null -> 0.0
    assert f["contra_penalty"] == 1.0


def test_extract_features_legacy_all_zero_vector():
    # the 22-row legacy shape: flat 15 keys, all zero except score -> yields no
    # nested features (the point of the §6a finding)
    fv = '{"final_score": 61.0, "total_sources": 0, "has_news": 0, "bull_count": 0}'
    f = extract_features(fv)
    assert "regime_z" not in f and "shadow_score" not in f


def test_extract_features_bad_json():
    assert extract_features(None) == {}
    assert extract_features("not json") == {}
    assert extract_features("[1,2,3]") == {}
